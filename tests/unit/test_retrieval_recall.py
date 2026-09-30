"""Tests for the pure parts of scripts/retrieval_recall.py (ADR-014, ADR-017).

The decision rule's inputs are computed here, so they are tested on hand-built
artifacts rather than read off a live run.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from retrieval_recall import (  # noqa: E402
    baseline_deltas,
    comparability_problems,
    has_sparse_rows,
    summarise,
)

SNAPSHOT = {
    "sdd-kafka-snowflake-2": {"commit_sha": "a" * 40, "embedding_model": "m"},
}


def row(sparse_rank=None):
    return {"sparse_rank": sparse_rank}


def result(qid, found_at, *, sparse=False, intent="decision"):
    """One question declaring path `p`, found at rank `found_at` (or None)."""
    def within(k):
        return found_at if found_at is not None and found_at <= k else None

    return {
        "id": qid,
        "intent": intent,
        "declared_paths": ["proj/p"],
        "top_rrf_score": 0.016,
        "retrieved_at_k": {str(k): {"proj/p": within(k)} for k in (3, 10, 20)},
        "ranking": [row(1 if sparse else None)],
    }


def artifact(results):
    return {"snapshot": SNAPSHOT, "summary": summarise(results), "results": results}


def test_has_sparse_rows_reads_any_sparse_rank() -> None:
    assert has_sparse_rows([row(), row(4)])
    assert not has_sparse_rows([row(), row()])
    assert not has_sparse_rows([])


def test_summary_counts_questions_with_sparse_rows() -> None:
    summary = summarise([result("q1", 1, sparse=True), result("q2", 1)])
    assert summary["questions_with_sparse_rows"] == 1
    assert summary["questions"] == 2


def test_deltas_list_a_path_that_left_the_top_3() -> None:
    before = artifact([result("q1", 1), result("q2", 2), result("q3", 15)])
    now = [result("q1", 1, sparse=True), result("q2", 4, sparse=True), result("q3", 2)]
    d = baseline_deltas(before, now, summarise(now))
    assert d["k3"] == (2, 2)
    assert d["lost_top3"] == [("q2", "proj/p")]
    assert d["k10"] == (2, 3)
    assert d["k20"] == (3, 3)
    assert d["sparse_rows"] == (0, 2)


def test_comparable_artifacts_have_no_problems() -> None:
    results = [result("q1", 1)]
    assert comparability_problems(artifact(results), SNAPSHOT, results) == []


def test_a_different_commit_is_refused() -> None:
    results = [result("q1", 1)]
    other = {"sdd-kafka-snowflake-2": {"commit_sha": "b" * 40, "embedding_model": "m"}}
    problems = comparability_problems(artifact(results), other, results)
    assert len(problems) == 1
    assert "snapshot differs" in problems[0]


def test_a_different_model_is_refused() -> None:
    results = [result("q1", 1)]
    other = {"sdd-kafka-snowflake-2": {"commit_sha": "a" * 40, "embedding_model": "n"}}
    assert comparability_problems(artifact(results), other, results)


def test_a_different_golden_set_is_refused() -> None:
    before = artifact([result("q1", 1)])
    changed = [result("q1", 1), result("q2", 1)]
    problems = comparability_problems(before, SNAPSHOT, changed)
    assert problems == ["golden set differs (question ids or declared paths): ['q2']"]


def test_a_changed_declared_path_is_refused() -> None:
    before = artifact([result("q1", 1)])
    moved = [result("q1", 1)]
    moved[0]["declared_paths"] = ["proj/other"]
    assert comparability_problems(before, SNAPSHOT, moved)
