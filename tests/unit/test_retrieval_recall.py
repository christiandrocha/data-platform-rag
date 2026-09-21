"""Unit tests for the recall script's before/after reading (ADR-014, ADR-005).

`retrieve` and `rerank` are both replaced, so no model and no database are
involved. What is under test is that one retrieval feeds both orderings, and
that the two recall figures are counted over the same denominator.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from data_platform_rag.contracts import ChunkMetadata, RerankedChunk, RetrievedChunk

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import retrieval_recall  # noqa: E402

PROJECT = "sdd-kafka-databricks"


def chunk(position: int) -> RetrievedChunk:
    return RetrievedChunk(
        id=position,
        content=f"chunk {position}",
        metadata=ChunkMetadata(
            source_project=PROJECT,
            source_type="adr",
            source_path=f"docs/adr/{position:03d}.md",
            chunk_index=0,
            token_count=10,
        ),
        dense_distance=0.1,
        sparse_score=0.0,
        rrf_score=1 / (60 + position),
        dense_rank=position,
    )


QUESTION = {
    "id": "q999",
    "intent": "decision",
    "question": "why?",
    # Declared path sits at RRF rank 5; the fake reranker moves it to rank 1.
    "expected_source_paths": [{"project": PROJECT, "path": "docs/adr/005.md"}],
}


@pytest.fixture
def stages(monkeypatch: pytest.MonkeyPatch) -> dict:
    calls: dict = {"retrieve": 0}
    candidates = [chunk(i) for i in range(1, 21)]

    def fake_retrieve(question, top_k=None):
        calls["retrieve"] += 1
        return candidates[:top_k]

    def fake_rerank(question, given, top_k=None):
        calls["rerank_top_k"] = top_k
        moved = [given[4], *given[:4], *given[5:]]
        return [
            RerankedChunk(**c.model_dump(), rerank_score=1.0 - i / 100, truncated=False)
            for i, c in enumerate(moved)
        ][:top_k]

    monkeypatch.setattr(retrieval_recall, "retrieve", fake_retrieve)
    monkeypatch.setattr(retrieval_recall, "rerank", fake_rerank)
    return calls


def test_one_retrieval_feeds_a_full_reranking(stages: dict) -> None:
    retrieval_recall.evaluate(QUESTION, max_k=20)
    assert stages["retrieve"] == 1
    assert stages["rerank_top_k"] == 20


def test_a_path_is_read_off_both_orderings(stages: dict) -> None:
    result = retrieval_recall.evaluate(QUESTION, max_k=20)
    path = f"{PROJECT}/docs/adr/005.md"
    assert result["retrieved_at_k"]["3"][path] is None
    assert result["retrieved_at_k"]["10"][path] == 5
    assert result["reranked_at_k"]["3"][path] == 1
    assert result["truncated_pairs"] == 0


def test_summary_counts_both_recalls_over_one_denominator(stages: dict) -> None:
    summary = retrieval_recall.summarise([retrieval_recall.evaluate(QUESTION, max_k=20)])
    assert summary["source_recall_at_k"]["3"] == {"found": 0, "declared": 1, "recall": 0.0}
    assert summary["reranked_recall_at_k"]["3"] == {"found": 1, "declared": 1, "recall": 1.0}
    assert summary["source_recall_at_k"]["20"] == summary["reranked_recall_at_k"]["20"]
