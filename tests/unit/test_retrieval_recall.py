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
    identical_rankings,
    separability,
    summarise,
    top_similarity,
)

SNAPSHOT = {
    "sdd-kafka-snowflake-2": {"commit_sha": "a" * 40, "embedding_model": "m"},
}


def row(sparse_rank=None, rank=1, path="p", anchor="Context"):
    return {
        "sparse_rank": sparse_rank,
        "rank": rank,
        "project": "proj",
        "path": path,
        "anchor": anchor,
    }


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


# ─── ADR-018 A4: identical rankings over the sparse-empty questions ──────────


def with_ranking(qid, ranking):
    r = result(qid, 1)
    r["ranking"] = ranking
    return r


def test_identical_rankings_count_only_sparse_empty_baseline_questions() -> None:
    before = artifact([
        with_ranking("q1", [row(rank=1, path="a"), row(rank=2, path="b")]),
        with_ranking("q2", [row(sparse_rank=1, rank=1, path="a")]),
    ])
    now = [
        with_ranking("q1", [row(rank=1, path="a"), row(rank=2, path="b")]),
        with_ranking("q2", [row(rank=1, path="z")]),
    ]
    assert identical_rankings(before, now) == {"identical": 1, "of": 1, "differ": []}


def test_a_changed_anchor_is_a_different_ranking() -> None:
    before = artifact([with_ranking("q1", [row(anchor="Context")])])
    now = [with_ranking("q1", [row(anchor="Decision")])]
    assert identical_rankings(before, now) == {"identical": 0, "of": 1, "differ": ["q1"]}


def test_a_changed_order_is_a_different_ranking() -> None:
    before = artifact([with_ranking("q1", [row(rank=1, path="a"), row(rank=2, path="b")])])
    now = [with_ranking("q1", [row(rank=1, path="b"), row(rank=2, path="a")])]
    assert identical_rankings(before, now)["differ"] == ["q1"]


# ─── ADR-019: separability of top-1 cosine similarity ────────────────────────


def scored(qid, similarity, intent="decision", declared=True):
    return {
        "id": qid,
        "intent": intent,
        "declared_paths": ["proj/p"] if declared else [],
        "top_similarity": similarity,
    }


def oos(qid, similarity):
    return scored(qid, similarity, intent="out-of-scope", declared=False)


def test_top_similarity_is_one_minus_the_rank_1_distance() -> None:
    assert top_similarity([{"dense_distance": 0.25}, {"dense_distance": 0.4}]) == 0.75
    assert top_similarity([]) is None


def test_a_separable_set_has_both_counts_zero() -> None:
    sep = separability([
        scored("q1", 0.80), scored("q2", 0.70), oos("q9", 0.60), oos("q8", 0.50),
    ])
    assert sep["min_in_scope"] == 0.70 and sep["min_in_scope_id"] == "q2"
    assert sep["max_out_of_scope"] == 0.60 and sep["max_out_of_scope_id"] == "q9"
    assert sep["in_scope_at_or_below_max_oos"] == 0
    assert sep["oos_at_or_above_min_in_scope"] == 0
    assert (sep["in_scope"], sep["out_of_scope"]) == (2, 2)


def test_one_in_scope_question_below_an_out_of_scope_one_is_overlap() -> None:
    sep = separability([scored("q1", 0.80), scored("q2", 0.55), oos("q9", 0.60)])
    assert sep["in_scope_at_or_below_max_oos"] == 1
    assert sep["oos_at_or_above_min_in_scope"] == 1


def test_an_exact_tie_counts_as_overlap() -> None:
    """ADR-019: equality is overlap, on both sides."""
    sep = separability([scored("q1", 0.80), scored("q2", 0.60), oos("q9", 0.60)])
    assert sep["in_scope_at_or_below_max_oos"] == 1
    assert sep["oos_at_or_above_min_in_scope"] == 1


def test_the_population_comes_from_intent_not_ids() -> None:
    sep = separability([scored("q1", 0.80), oos("q999", 0.90)])
    assert sep["max_out_of_scope_id"] == "q999"
    assert sep["out_of_scope"] == 1


def test_in_scope_means_the_recall_population() -> None:
    """Not out-of-scope AND declaring paths: the set recall is computed over."""
    sep = separability([scored("q1", 0.80), scored("q2", 0.10, declared=False), oos("q9", 0.5)])
    assert sep["in_scope"] == 1
    assert sep["min_in_scope_id"] == "q1"


def test_a_missing_class_gives_none_not_a_crash() -> None:
    only_in = separability([scored("q1", 0.8)])
    assert only_in["max_out_of_scope"] is None
    assert only_in["in_scope_at_or_below_max_oos"] is None
    only_oos = separability([oos("q9", 0.5)])
    assert only_oos["min_in_scope"] is None
    assert only_oos["oos_at_or_above_min_in_scope"] is None
