"""RAGAS evaluation of the golden set, in two stages (ADR-008).

    generate [--out-dir DIR]     stage 1: an answer per question, into a run file
    score RUN_FILE [--rescore]   stage 2: RAGAS scores, into RUN_FILE's report
    all [--out-dir DIR]          generate, then score
    compare REPORT_A REPORT_B    B minus A per metric, or why they are not comparable
    baseline REPORT              copy a report and its run file to docs/eval-baselines/

`make eval` runs `verify_adversarials.py` before `all` (ADR-011): a contamination
failure stops the run before anything is generated.

Everything that can stop a stage is checked before its first call, so a refusal
spends nothing: the key, the `ragas` import, the database, and a full git
history for the golden set's SHA. A refusal is one line on stderr and exit 2.
`compare` exits 1 when the reports are not comparable.

No regression threshold exists yet (ADR-008, Decision 7): `compare` reports
deltas and never fails on one.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from data_platform_rag.config import Settings, get_settings
from data_platform_rag.evaluation import golden_set_loader, report
from data_platform_rag.evaluation.generate import (
    StaleIndexError,
    generate_run,
    now_utc,
    read_provenance,
    run_id_for,
)

DEFAULT_OUT_DIR = Path(".claude/dev/reports")


class PreflightError(Exception):
    """A reason to stop before anything is called or written."""


# ─── Preflight ───────────────────────────────────────────────────────────────


def load_settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as exc:
        raise PreflightError(f"configuration does not load: {exc}") from exc


def require_key(settings: Settings) -> str:
    key = settings.anthropic_api_key.get_secret_value().strip()
    if not key:
        raise PreflightError("ANTHROPIC_API_KEY is empty. Set it in .env to run the evaluation.")
    return key


def require_ragas() -> None:
    from data_platform_rag.evaluation.ragas_runner import disable_ragas_telemetry

    disable_ragas_telemetry()
    try:
        import ragas  # noqa: F401
    except ImportError as exc:
        raise PreflightError(
            f'`ragas` does not import ({exc}). Install it with pip install -e ".[eval]".'
        ) from exc


def connector(settings: Settings):  # noqa: ANN201 - a connect function
    from data_platform_rag.indexer.writer import connect

    def connect_fn():  # noqa: ANN202
        return connect(str(settings.database_url))

    try:
        connect_fn().close()
    except Exception as exc:  # noqa: BLE001 - any connection failure is a preflight stop
        raise PreflightError(f"the database is not reachable: {exc}") from exc
    return connect_fn


def make_client(api_key: str):  # noqa: ANN201 - an LLMClient
    from data_platform_rag.generation.sdk import build_client

    try:
        return build_client(api_key)
    except ImportError as exc:
        raise PreflightError(
            "the `anthropic` package is not installed (pip install -e .)."
        ) from exc


# ─── Stages ──────────────────────────────────────────────────────────────────


def generate(out_dir: Path) -> Path:
    settings = load_settings()
    key = require_key(settings)
    try:
        sha, dirty = golden_set_loader.version()
    except golden_set_loader.GoldenSetVersionError as exc:
        raise PreflightError(str(exc)) from exc
    questions = golden_set_loader.load()
    connect_fn = connector(settings)
    client = make_client(key)

    now = now_utc()
    conn = connect_fn()
    try:
        provenance = read_provenance(conn, settings, sha, dirty, now)
    except StaleIndexError as exc:
        raise PreflightError(str(exc)) from exc
    finally:
        conn.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_id_for(now)}.json"
    if dirty:
        print("warning: the golden set has uncommitted changes; this run will not be comparable")
    generate_run(questions, client, provenance, connect_fn=connect_fn, out_path=out_path)
    print(f"run file: {out_path}")
    return out_path


def score(run_file: Path, rescore: bool) -> Path:
    settings = load_settings()
    key = require_key(settings)
    require_ragas()
    from data_platform_rag.contracts import EvalRun
    from data_platform_rag.evaluation import ragas_runner
    from data_platform_rag.evaluation.langfuse_scorer import get_pusher

    try:
        run = EvalRun.model_validate_json(run_file.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise PreflightError(f"{run_file} is not a run file: {exc}") from exc
    report_file = report.report_path_for(run_file)
    existing = None
    if report_file.exists() and not rescore:
        existing = report.load_report(report_file)

    judge = ragas_runner.judge_config(settings)
    metrics = ragas_runner.build_metrics(
        ragas_runner.build_judge(settings, key),
        ragas_runner.build_embeddings(),
        settings.answer_relevancy_strictness,
    )
    result = ragas_runner.score_run(
        run,
        str(run_file),
        metrics,
        judge,
        get_pusher(run.run_id),
        write=lambda r: report.write_report(r, report_file),
        existing=existing,
    )
    print(report.table(result))
    print(f"report: {report_file}")
    return report_file


def compare(a: Path, b: Path) -> int:
    try:
        ra, rb = report.load_report(a), report.load_report(b)
    except (OSError, ValidationError) as exc:
        raise PreflightError(f"not a report: {exc}") from exc
    result = report.compare(ra, rb)
    print(report.comparison_table(ra, rb, result))
    return 0 if result.comparable else 1


def baseline(report_file: Path) -> None:
    try:
        copied = report.copy_baseline(report_file)
    except (OSError, ValidationError) as exc:
        raise PreflightError(f"{report_file} cannot be a baseline: {exc}") from exc
    for path in copied:
        print(f"copied: {path}")
    print("Commit both files. README badges are taken from a committed baseline only.")


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "all"):
        p = sub.add_parser(name)
        p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p = sub.add_parser("score")
    p.add_argument("run_file", type=Path)
    p.add_argument("--rescore", action="store_true", help="ignore an existing report")
    p = sub.add_parser("compare")
    p.add_argument("report_a", type=Path)
    p.add_argument("report_b", type=Path)
    p = sub.add_parser("baseline")
    p.add_argument("report", type=Path)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if args.command == "generate":
            generate(args.out_dir)
        elif args.command == "score":
            score(args.run_file, args.rescore)
        elif args.command == "all":
            # Stage 2's checks run before stage 1 spends anything.
            require_key(load_settings())
            require_ragas()
            score(generate(args.out_dir), rescore=False)
        elif args.command == "compare":
            return compare(args.report_a, args.report_b)
        elif args.command == "baseline":
            baseline(args.report)
    except PreflightError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
