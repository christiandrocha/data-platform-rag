"""Measure system-prompt rule 3, the out-of-scope gate (ADR-020).

Since ADR-019 the LinkedIn fallback is sent by the LLM under rule 3. This script
runs the real generation step over 45 in-scope and 35 out-of-scope questions, 3
times at temperature 0, classifies every output (`generation.fallback`), and
writes one artifact holding all of it.

It prints numbers, not a verdict. The rule lives in ADR-020, and code that
re-implemented it could drift from it, as `retrieval_recall.py` reasons too.

**Without a key it stops.** An empty `ANTHROPIC_API_KEY`, a missing `anthropic`
package, an invalid question file or a population other than 45 + 35 each exit 2
before anything is retrieved or written. There is no stub fallback: a stub
reading would look like a measurement.

**Retrieval runs once per question,** before the first call, and its chunks are
reused by all 3 runs. Exact-scan retrieval is deterministic (ADR-018), so this
makes the context identical across runs by construction: only the LLM varies.

**A failed call is not a reading.** If a call still fails after the SDK's own
retries, or the run is interrupted, the artifact is written with
`complete: false`, the reason, and the outputs so far, and **no number is
computed**. ADR-020's Outcome lists every artifact this script produced,
incomplete ones included.

`--dry-run` needs no key: it retrieves, prints the size of every assembled user
message and the first one in full, calls nothing and writes nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from validate_golden_set import (
    GOLDEN_SET,
    OUT_OF_SCOPE_SET,
    load_question_file,
    should_fallback,
    validate_golden,
    validate_out_of_scope_set,
)

from data_platform_rag.config import Settings, get_settings
from data_platform_rag.contracts import (
    FallbackEvalItem,
    FallbackEvalReport,
    FallbackRunSummary,
    IndexedSnapshot,
    QuestionSource,
    RetrievedChunk,
    RetrievedSource,
)
from data_platform_rag.generation.client import LLMClient, build_user_message, generate
from data_platform_rag.generation.fallback import classify_output
from data_platform_rag.generation.prompt import (
    CONTEXT_FORMAT_VERSION,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_VERSION,
)

REPORT_DIR = Path(".claude/dev/reports")

# DEFINE Q3: 3 runs, the worst one decides.
RUNS = 3
# The rule's denominators (ADR-020): 45 in-scope golden questions, and the golden
# 5 out-of-scope plus the 30 of the new set. A measurement on any other
# population would read thresholds written for these counts.
IN_SCOPE_TOTAL = 45
OUT_OF_SCOPE_TOTAL = 35

EXIT_PREFLIGHT = 2
EXIT_INCOMPLETE = 1

Retriever = Callable[[str], list[RetrievedChunk]]


@dataclass(frozen=True)
class EvalQuestion:
    """One question as this script uses it, from either file."""

    id: str
    question: str
    source: QuestionSource
    intent: str
    band: str | None
    expects_fallback: bool


class PreflightError(Exception):
    """A reason to stop before anything is retrieved, called or written."""


# ─── Questions ───────────────────────────────────────────────────────────────


def build_questions(golden: list[dict], out_of_scope: list[dict]) -> list[EvalQuestion]:
    """Every golden question, then every out-of-scope set question, in file order."""

    def one(q: dict, source: QuestionSource) -> EvalQuestion:
        return EvalQuestion(
            id=q["id"],
            question=q["question"],
            source=source,
            intent=q["intent"],
            band=q.get("band"),
            expects_fallback=should_fallback(q),
        )

    return [one(q, "golden") for q in golden] + [one(q, "out_of_scope_set") for q in out_of_scope]


def load_questions() -> list[EvalQuestion]:
    """Both files, loaded and validated. Raises PreflightError on any error."""
    try:
        golden = load_question_file(GOLDEN_SET)
        out_of_scope = load_question_file(OUT_OF_SCOPE_SET)
    except ValueError as exc:
        raise PreflightError(str(exc)) from exc
    errors = [f"{GOLDEN_SET.name}: {e}" for e in validate_golden(golden)[0]]
    errors += [
        f"{OUT_OF_SCOPE_SET.name}: {e}" for e in validate_out_of_scope_set(out_of_scope, golden)[0]
    ]
    if errors:
        raise PreflightError(
            "question files do not validate (run `make golden-set-check`):\n  "
            + "\n  ".join(errors)
        )
    return build_questions(golden, out_of_scope)


def population_problem(questions: list[EvalQuestion]) -> str | None:
    """Why this population cannot be measured under ADR-020's rule, or None."""
    in_scope = sum(1 for q in questions if not q.expects_fallback)
    out_of_scope = sum(1 for q in questions if q.expects_fallback)
    if (in_scope, out_of_scope) == (IN_SCOPE_TOTAL, OUT_OF_SCOPE_TOTAL):
        return None
    return (
        f"the rule is written for {IN_SCOPE_TOTAL} in-scope and {OUT_OF_SCOPE_TOTAL} "
        f"out-of-scope questions; the files hold {in_scope} and {out_of_scope}. "
        "Finish curating the out-of-scope set first."
    )


# ─── Preflight ───────────────────────────────────────────────────────────────


def load_settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as exc:
        raise PreflightError(f"configuration does not load: {exc}") from exc


def require_key(settings: Settings) -> str:
    key = settings.anthropic_api_key.get_secret_value().strip()
    if not key:
        raise PreflightError(
            "ANTHROPIC_API_KEY is empty. Set it in .env to measure; "
            "`make fallback-eval-dry` runs without one."
        )
    return key


def make_client(api_key: str) -> LLMClient:
    """The real SDK client. The only place this script imports `anthropic`."""
    try:
        import anthropic
    except ImportError as exc:
        raise PreflightError(
            "the `anthropic` package is not installed (pip install -e .)."
        ) from exc
    return anthropic.Anthropic(api_key=api_key)


# ─── Retrieval ───────────────────────────────────────────────────────────────


@contextmanager
def retrieval_session(settings: Settings) -> Iterator[tuple[Retriever, list[IndexedSnapshot]]]:
    """A retriever over one connection, and what the index holds right now."""
    from data_platform_rag.indexer.writer import connect, current_snapshots
    from data_platform_rag.retrieval.pipeline import retrieve

    with connect(str(settings.database_url)) as conn:
        snapshots = sorted(current_snapshots(conn).values(), key=lambda s: s.source_project)

        def retriever(question: str) -> list[RetrievedChunk]:
            return retrieve(question, top_k=settings.rerank_top_k, conn=conn)

        yield retriever, snapshots


def retrieve_contexts(
    questions: list[EvalQuestion], retriever: Retriever
) -> dict[str, list[RetrievedChunk]]:
    """Each question's chunks, retrieved once. Raises if any comes back empty."""
    contexts = {q.id: retriever(q.question) for q in questions}
    empty = [qid for qid, chunks in contexts.items() if not chunks]
    if empty:
        raise PreflightError(f"retrieval returned no chunks for {empty}: is the index populated?")
    return contexts


def to_sources(chunks: list[RetrievedChunk]) -> list[RetrievedSource]:
    return [
        RetrievedSource(
            chunk_id=c.id,
            source_project=c.metadata.source_project,
            source_path=c.metadata.source_path,
            source_anchor=c.metadata.source_anchor,
            adr_id=c.metadata.adr_id,
            dense_distance=c.dense_distance,
        )
        for c in chunks
    ]


# ─── Measurement ─────────────────────────────────────────────────────────────


def measure(
    questions: list[EvalQuestion],
    contexts: dict[str, list[RetrievedChunk]],
    client: LLMClient,
    runs: int = RUNS,
) -> tuple[list[FallbackEvalItem], str | None]:
    """Every question, `runs` times. Returns the items and why it stopped early, if it did.

    Run 1 covers every question before run 2 starts. A failure or an interrupt
    ends the measurement where it is: the items so far are kept for the record,
    and the reason makes the artifact incomplete.
    """
    items: list[FallbackEvalItem] = []
    try:
        for run in range(1, runs + 1):
            for q in questions:
                chunks = contexts[q.id]
                result = generate(q.question, chunks, client)
                items.append(
                    FallbackEvalItem(
                        run=run,
                        question_id=q.id,
                        source=q.source,
                        intent=q.intent,
                        band=q.band,
                        expects_fallback=q.expects_fallback,
                        retrieved=to_sources(chunks),
                        output_text=result.text,
                        output_class=classify_output(result.text),
                        stop_reason=result.stop_reason,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                    )
                )
    except KeyboardInterrupt:
        return items, "interrupted"
    except Exception as exc:  # noqa: BLE001 - any failure makes the run incomplete
        return items, f"{type(exc).__name__}: {exc}"
    return items, None


def summarize_run(run: int, items: list[FallbackEvalItem]) -> FallbackRunSummary:
    """The two numbers ADR-020 reads for one run, and the ids behind each failure."""
    mine = [i for i in items if i.run == run]
    oos = [i for i in mine if i.expects_fallback]
    in_scope = [i for i in mine if not i.expects_fallback]
    false_fallback = [i for i in in_scope if i.output_class != "answer"]
    return FallbackRunSummary(
        run=run,
        out_of_scope_total=len(oos),
        out_of_scope_fallback=sum(1 for i in oos if i.output_class == "fallback"),
        in_scope_total=len(in_scope),
        in_scope_false_fallback=len(false_fallback),
        missed_ids=[i.question_id for i in oos if i.output_class != "fallback"],
        non_compliant_out_of_scope_ids=[
            i.question_id for i in oos if i.output_class == "non_compliant_refusal"
        ],
        false_fallback_ids=[i.question_id for i in false_fallback],
        empty_ids=[i.question_id for i in mine if i.output_class == "empty"],
        non_end_turn_ids=[i.question_id for i in mine if i.stop_reason != "end_turn"],
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble_report(
    items: list[FallbackEvalItem],
    incomplete_reason: str | None,
    *,
    settings: Settings,
    runs: int,
    snapshots: list[IndexedSnapshot],
    golden_set_sha256: str,
    out_of_scope_set_sha256: str,
) -> FallbackEvalReport:
    """The artifact. Summaries only for a complete measurement: no number otherwise."""
    complete = incomplete_reason is None
    return FallbackEvalReport(
        created_at=datetime.now(UTC),
        complete=complete,
        incomplete_reason=incomplete_reason,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        runs_requested=runs,
        top_k=settings.rerank_top_k,
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        system_prompt_sha256=hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        context_format_version=CONTEXT_FORMAT_VERSION,
        golden_set_sha256=golden_set_sha256,
        out_of_scope_set_sha256=out_of_scope_set_sha256,
        snapshots=snapshots,
        summaries=[summarize_run(r, items) for r in range(1, runs + 1)] if complete else [],
        items=items,
        total_input_tokens=sum(i.input_tokens for i in items),
        total_output_tokens=sum(i.output_tokens for i in items),
    )


def write_report(report: FallbackEvalReport, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.created_at.strftime("%Y%m%d-%H%M%S")
    suffix = "" if report.complete else "-incomplete"
    out = report_dir / f"fallback-eval-{stamp}{suffix}.json"
    out.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n")
    return out


# ─── Output ──────────────────────────────────────────────────────────────────


def ids(values: list[str]) -> str:
    return ", ".join(values) if values else "-"


def print_report(report: FallbackEvalReport, path: Path) -> None:
    print(
        f"model {report.model}  temperature {report.temperature}  "
        f"max_tokens {report.max_tokens}  top_k {report.top_k}"
    )
    print(
        f"system prompt {report.system_prompt_version} "
        f"(sha256 {report.system_prompt_sha256[:12]})  "
        f"context format {report.context_format_version}"
    )
    for s in report.snapshots:
        print(f"  {s.source_project}@{s.commit_sha[:8]}  {s.embedding_model}")

    if not report.complete:
        print(f"\nINCOMPLETE: {report.incomplete_reason}")
        print(
            f"  {len(report.items)} output(s) kept for the record. Not a reading "
            "(ADR-020): no number is computed. Run it again from the start."
        )
    else:
        print("\nNumbers only. The rule that reads them is in ADR-020.")
        for s in report.summaries:
            print(
                f"\nRun {s.run}: out-of-scope fallback {s.out_of_scope_fallback}/"
                f"{s.out_of_scope_total}   in-scope false fallback "
                f"{s.in_scope_false_fallback}/{s.in_scope_total}"
            )
            print(f"  out-of-scope missed:        {ids(s.missed_ids)}")
            print(f"    of which non-compliant:   {ids(s.non_compliant_out_of_scope_ids)}")
            print(f"  in-scope false fallback:    {ids(s.false_fallback_ids)}")
            print(f"  empty output:               {ids(s.empty_ids)}")
            print(f"  stop_reason not end_turn:   {ids(s.non_end_turn_ids)}")
            by_band: dict[str, list[int]] = {}
            for i in report.items:
                if i.run == s.run and i.band is not None:
                    got = by_band.setdefault(i.band, [0, 0])
                    got[0] += i.output_class == "fallback"
                    got[1] += 1
            bands = "  ".join(f"{b} {f}/{n}" for b, (f, n) in sorted(by_band.items()))
            print(f"  fallback by band:           {bands}")

    print(f"\ntokens: {report.total_input_tokens} input, {report.total_output_tokens} output")
    print(f"artifact: {path}")


# ─── Entry point ─────────────────────────────────────────────────────────────


def dry_run(questions: list[EvalQuestion], contexts: dict[str, list[RetrievedChunk]]) -> None:
    problem = population_problem(questions)
    if problem:
        print(f"note: {problem}\n")
    messages = [(q, build_user_message(q.question, contexts[q.id])) for q in questions]
    for q, message in messages:
        print(f"  {q.id:<7} {'OOS' if q.expects_fallback else 'in ':<4}{len(message):>6} chars")
    q, message = messages[0]
    print(f"\n{'=' * 70}\n{q.id}: the user message as the LLM would read it\n{'=' * 70}")
    print(message)
    print(
        f"\n{len(questions)} question(s), {RUNS} run(s) = {len(questions) * RUNS} call(s) "
        "when measured. Nothing called, nothing written."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Retrieve and print the user messages. No key, no call, no file.",
    )
    args = parser.parse_args(argv)

    # Everything that can stop the run is checked before retrieval and before any
    # write, so a refusal leaves no trace and spends nothing.
    try:
        settings = load_settings()
        client: LLMClient | None = None
        if not args.dry_run:
            client = make_client(require_key(settings))
        questions = load_questions()
        if not args.dry_run:
            problem = population_problem(questions)
            if problem:
                raise PreflightError(problem)
        with retrieval_session(settings) as (retriever, snapshots):
            if not snapshots:
                raise PreflightError("nothing is indexed. Run `make index-corpus` first.")
            contexts = retrieve_contexts(questions, retriever)
    except PreflightError as exc:
        print(f"fallback-eval: {exc}", file=sys.stderr)
        return EXIT_PREFLIGHT

    if args.dry_run:
        dry_run(questions, contexts)
        return 0

    assert client is not None  # noqa: S101 - set above whenever not a dry run
    items, reason = measure(questions, contexts, client, RUNS)
    report = assemble_report(
        items,
        reason,
        settings=settings,
        runs=RUNS,
        snapshots=snapshots,
        golden_set_sha256=sha256_file(GOLDEN_SET),
        out_of_scope_set_sha256=sha256_file(OUT_OF_SCOPE_SET),
    )
    path = write_report(report, REPORT_DIR)
    print_report(report, path)
    return 0 if report.complete else EXIT_INCOMPLETE


if __name__ == "__main__":
    sys.exit(main())
