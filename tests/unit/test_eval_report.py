"""Aggregates, comparison and baseline (ADR-008). No RAGAS call, no API."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from data_platform_rag.contracts import (
    METRIC_NAMES,
    EvalProvenance,
    EvalReport,
    JudgeConfig,
    MetricValue,
    RAGASReport,
)
from data_platform_rag.evaluation import report as rep


def in_scope(qid: str, value: float | None, *, fallback: bool = False) -> RAGASReport:
    metric = MetricValue(value=value) if value is not None else MetricValue(error="NaN")
    return RAGASReport(
        question_id=qid,
        intent="decision",
        trace_id=None,
        metrics=dict.fromkeys(METRIC_NAMES, metric),
        fallback_fired=fallback,
        fallback_correct=None,
        pushed_to_langfuse=False,
    )


def out_of_scope(qid: str, fired: bool) -> RAGASReport:
    return RAGASReport(
        question_id=qid,
        intent="out-of-scope",
        trace_id=None,
        metrics=None,
        fallback_fired=fired,
        fallback_correct=fired,
        pushed_to_langfuse=False,
    )


def provenance(**changes) -> EvalProvenance:
    base = {
        "created_at": datetime(2026, 10, 5, tzinfo=UTC),
        "golden_set_sha": "a" * 40,
        "golden_set_dirty": False,
        "corpus_commits": ["sdd-kafka-databricks@" + "f" * 40],
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "generation_model": "claude-sonnet-4-6",
        "system_prompt_version": "v1.1.0",
        "context_format_version": "v1.0.0",
        "rerank_top_k": 3,
    }
    return EvalProvenance(**{**base, **changes})


def judge(**changes) -> JudgeConfig:
    base = {
        "model": "claude-opus-5-5",
        "max_tokens": 4096,
        "temperature": 0.0,
        "ragas_version": "0.4.3",
        "answer_relevancy_strictness": 3,
    }
    return JudgeConfig(**{**base, **changes})


def report_of(reports, *, prov=None, jdg=None, run_id="eval-run-a", run_file="run.json"):
    return EvalReport(
        run_id=run_id,
        run_file=run_file,
        provenance=prov or provenance(),
        judge=jdg or judge(),
        scored_at=datetime(2026, 10, 5, tzinfo=UTC),
        reports=reports,
        aggregate=rep.aggregate(reports),
    )


# ─── aggregate ───────────────────────────────────────────────────────────────


def test_a_mean_covers_scored_questions_only_and_carries_its_coverage():
    agg = rep.aggregate([in_scope("q1", 0.8), in_scope("q2", 0.6), in_scope("q3", None)])
    faith = agg.metrics["faithfulness"]
    assert faith.mean == pytest.approx(0.7)  # not (0.8 + 0.6 + 0) / 3
    assert (faith.n_scored, faith.n_expected) == (2, 3)


def test_nothing_scored_is_no_mean_not_zero():
    agg = rep.aggregate([in_scope("q1", None)])
    assert agg.metrics["context_recall"].mean is None


def test_fallback_counts():
    agg = rep.aggregate(
        [
            in_scope("q1", 0.9),
            in_scope("q2", 0.1, fallback=True),
            out_of_scope("oos1", True),
            out_of_scope("oos2", False),
        ]
    )
    assert (agg.fallback_correct, agg.n_out_of_scope) == (1, 2)
    assert (agg.in_scope_fallbacks, agg.n_in_scope) == (1, 2)


def test_the_table_shows_coverage_and_missing_values():
    shown = rep.table(report_of([in_scope("q1", 0.8), in_scope("q2", None)]))
    assert "0.800 (1/2)" in shown
    assert "missing values: 4" in shown


# ─── compare ─────────────────────────────────────────────────────────────────


def test_compare_gives_b_minus_a():
    a = report_of([in_scope("q1", 0.6)])
    b = report_of([in_scope("q1", 0.8)], run_id="eval-run-b")
    result = rep.compare(a, b)
    assert result.comparable
    assert result.deltas["faithfulness"] == pytest.approx(0.2)


@pytest.mark.parametrize(
    ("prov_b", "judge_b", "reason"),
    [
        ({"golden_set_sha": "b" * 40}, {}, "golden set differs"),
        ({"golden_set_dirty": True}, {}, "uncommitted golden set"),
        ({}, {"model": "claude-haiku-4-5"}, "judge model differs"),
        ({}, {"ragas_version": "0.4.4"}, "judge ragas_version differs"),
        ({}, {"answer_relevancy_strictness": 5}, "judge answer_relevancy_strictness"),
        ({}, {"temperature": 0.5}, "judge temperature differs"),
    ],
)
def test_compare_refuses_and_says_why(prov_b, judge_b, reason):
    a = report_of([in_scope("q1", 0.6)])
    b = report_of([in_scope("q1", 0.8)], prov=provenance(**prov_b), jdg=judge(**judge_b))
    result = rep.compare(a, b)
    assert not result.comparable
    assert any(reason in r for r in result.refusals)
    assert "not comparable" in rep.comparison_table(a, b, result)


def test_compare_allows_and_prints_what_is_being_evaluated():
    a = report_of([in_scope("q1", 0.6)])
    b = report_of(
        [in_scope("q1", 0.8)],
        prov=provenance(system_prompt_version="v1.2.0", rerank_top_k=5),
    )
    result = rep.compare(a, b)
    assert result.comparable
    assert "system_prompt_version: v1.1.0 -> v1.2.0" in result.differences
    assert "rerank_top_k: 3 -> 5" in result.differences
    assert "not verdicts" in rep.comparison_table(a, b, result)


def test_a_delta_with_a_side_unscored_is_none():
    a = report_of([in_scope("q1", None)])
    b = report_of([in_scope("q1", 0.8)])
    assert rep.compare(a, b).deltas["faithfulness"] is None


# ─── files and baseline ──────────────────────────────────────────────────────


def test_report_path_sits_next_to_the_run_file(tmp_path):
    run = tmp_path / "eval-run-x.json"
    assert rep.report_path_for(run) == tmp_path / "eval-run-x.report.json"


def test_baseline_copies_the_report_and_its_run_file(tmp_path):
    run_file = tmp_path / "eval-run-a.json"
    run_file.write_text("{}", encoding="utf-8")
    report_file = tmp_path / "eval-run-a.report.json"
    rep.write_report(report_of([in_scope("q1", 0.8)], run_file=str(run_file)), report_file)
    dest = tmp_path / "baselines"
    copied = rep.copy_baseline(report_file, dest)
    assert sorted(p.name for p in copied) == ["eval-run-a.json", "eval-run-a.report.json"]
    assert rep.load_report(dest / "eval-run-a.report.json").run_id == "eval-run-a"


def test_baseline_refuses_a_file_that_is_not_a_report(tmp_path):
    other = tmp_path / "fallback-eval.json"
    other.write_text(json.dumps({"items": []}), encoding="utf-8")
    with pytest.raises(ValidationError):
        rep.copy_baseline(other, tmp_path / "baselines")
    assert not (tmp_path / "baselines").exists()


def test_baseline_refuses_a_report_whose_run_file_is_gone(tmp_path):
    report_file = tmp_path / "eval-run-a.report.json"
    rep.write_report(
        report_of([in_scope("q1", 0.8)], run_file=str(tmp_path / "gone.json")), report_file
    )
    with pytest.raises(FileNotFoundError, match="run file is missing"):
        rep.copy_baseline(report_file, tmp_path / "baselines")


# ─── contracts ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("fields", [{}, {"value": 0.5, "error": "x"}])
def test_a_metric_value_holds_exactly_one_of_value_and_error(fields):
    with pytest.raises(ValidationError, match="exactly one"):
        MetricValue(**fields)
