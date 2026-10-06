"""The numbers of a scored run, and whether two runs can be compared (ADR-008).

- **Means cover scored questions only**, and every mean is shown with its
  coverage, `mean (n/45)`. A missing value never becomes a 0 (Decision 5).
- **`compare` refuses** what ADR-011 and ADR-008 say cannot be compared: a
  different golden-set SHA, an edited golden set, or a different judge. It
  allows, and prints, differences in what is being evaluated.
- **No regression threshold exists yet** (Decision 7). `compare` reports deltas
  and never judges them.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from data_platform_rag.contracts import (
    METRIC_NAMES,
    EvalReport,
    MetricAggregate,
    RAGASAggregate,
    RAGASReport,
    ReportComparison,
)

BASELINE_DIR = Path("docs/eval-baselines")


def aggregate(reports: list[RAGASReport]) -> RAGASAggregate:
    in_scope = [r for r in reports if r.metrics is not None]
    out_of_scope = [r for r in reports if r.metrics is None]
    metrics = {}
    for name in METRIC_NAMES:
        values = [
            r.metrics[name].value
            for r in in_scope
            if r.metrics is not None and r.metrics[name].value is not None
        ]
        metrics[name] = MetricAggregate(
            mean=sum(values) / len(values) if values else None,
            n_scored=len(values),
            n_expected=len(in_scope),
        )
    return RAGASAggregate(
        metrics=metrics,
        fallback_correct=sum(1 for r in out_of_scope if r.fallback_correct),
        n_out_of_scope=len(out_of_scope),
        in_scope_fallbacks=sum(1 for r in in_scope if r.fallback_fired),
        n_in_scope=len(in_scope),
    )


def _mean(agg: MetricAggregate) -> str:
    mean = "—" if agg.mean is None else f"{agg.mean:.3f}"
    return f"{mean} ({agg.n_scored}/{agg.n_expected})"


def table(report: EvalReport) -> str:
    """The aggregate as printed by `make eval`."""
    agg = report.aggregate
    rows = [f"{report.run_id}, judge {report.judge.model}, ragas {report.judge.ragas_version}"]
    rows += [f"  {name:<18} {_mean(agg.metrics[name])}" for name in METRIC_NAMES]
    rows.append(f"  {'fallback_correct':<18} {agg.fallback_correct}/{agg.n_out_of_scope}")
    rows.append(f"  {'in-scope fallbacks':<18} {agg.in_scope_fallbacks}/{agg.n_in_scope}")
    errors = sum(
        1 for r in report.reports for m in (r.metrics or {}).values() if m.error is not None
    )
    rows.append(f"  missing values: {errors}. Each one's reason is in the report file.")
    return "\n".join(rows)


def compare(a: EvalReport, b: EvalReport) -> ReportComparison:
    """B minus A, per metric, or the reasons they cannot be compared."""
    pa, pb = a.provenance, b.provenance
    refusals = []
    if pa.golden_set_sha != pb.golden_set_sha:
        refusals.append(f"golden set differs (ADR-011): {pa.golden_set_sha} vs {pb.golden_set_sha}")
    for side, p in (("A", pa), ("B", pb)):
        if p.golden_set_dirty:
            refusals.append(f"{side} was generated from an uncommitted golden set")
    for field in (
        "model",
        "ragas_version",
        "answer_relevancy_strictness",
        "temperature",
        "max_tokens",
    ):
        va, vb = getattr(a.judge, field), getattr(b.judge, field)
        if va != vb:
            refusals.append(f"judge {field} differs: {va} vs {vb}")

    differences = []
    for field in (
        "generation_model",
        "system_prompt_version",
        "context_format_version",
        "rerank_top_k",
        "embedding_model",
        "corpus_commits",
    ):
        va, vb = getattr(pa, field), getattr(pb, field)
        if va != vb:
            differences.append(f"{field}: {va} -> {vb}")

    deltas = {}
    for name in METRIC_NAMES:
        ma, mb = a.aggregate.metrics[name].mean, b.aggregate.metrics[name].mean
        deltas[name] = None if ma is None or mb is None else mb - ma
    return ReportComparison(
        comparable=not refusals, refusals=refusals, differences=differences, deltas=deltas
    )


def comparison_table(a: EvalReport, b: EvalReport, result: ReportComparison) -> str:
    if not result.comparable:
        return "not comparable:\n" + "\n".join(f"  - {r}" for r in result.refusals)
    rows = [f"{a.run_id} -> {b.run_id}"]
    rows += [f"  differs: {d}" for d in result.differences] or ["  differs: nothing evaluated"]
    for name in METRIC_NAMES:
        delta = result.deltas[name]
        shown = "—" if delta is None else f"{delta:+.3f}"
        rows.append(
            f"  {name:<18} {_mean(a.aggregate.metrics[name])} -> "
            f"{_mean(b.aggregate.metrics[name])}  {shown}"
        )
    rows.append("  No threshold exists yet (ADR-008, Decision 7): these are not verdicts.")
    return "\n".join(rows)


def load_report(path: Path) -> EvalReport:
    """A report file. Anything else raises ValidationError."""
    return EvalReport.model_validate_json(path.read_text(encoding="utf-8"))


def write_report(report: EvalReport, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def report_path_for(run_file: Path) -> Path:
    return run_file.with_name(run_file.stem + ".report.json")


def copy_baseline(report_file: Path, dest: Path = BASELINE_DIR) -> list[Path]:
    """Copy a report and the run file it scored. Refuses a file that is not a report.

    The run file goes with it (DESIGN D10): a score without the answer it judged
    cannot be audited.
    """
    report = load_report(report_file)
    run_file = Path(report.run_file)
    if not run_file.is_file():
        raise FileNotFoundError(f"the report's run file is missing: {run_file}")
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in (report_file, run_file):
        target = dest / src.name
        shutil.copyfile(src, target)
        copied.append(target)
    return copied
