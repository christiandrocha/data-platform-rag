"""Unit tests for the rerank stage (ADR-005).

No model is loaded, ever. `get_model` is replaced for the whole module by a
function that raises, and a test that needs a model installs a fake one: a
cross-encoder whose scores are scripted per chunk text, and a tokenizer that
counts words. A test that reached the real loader would fail loudly instead of
downloading 92 MB or 1,134 MB in CI.
"""

from __future__ import annotations

import pytest

from data_platform_rag.config import get_settings_without_llm
from data_platform_rag.contracts import ChunkMetadata, RerankedChunk, RetrievedChunk
from data_platform_rag.retrieval import pipeline, reranker

QUESTION = "why one unified pipeline"


class FakeTokenizer:
    """Pair length = words in question + words in text."""

    def __call__(self, question: str, text: str, **_: object) -> dict:
        return {"input_ids": [0] * (len(question.split()) + len(text.split()))}


class FakeCrossEncoder:
    def __init__(self, scores: dict[str, float], window: int = 512) -> None:
        self.scores = scores
        self.max_seq_length = window
        self.tokenizer = FakeTokenizer()
        self.calls: list[list[tuple[str, str]]] = []

    def predict(self, pairs, **_: object) -> list[float]:
        self.calls.append(list(pairs))
        return [self.scores[text] for _, text in pairs]


def chunk(chunk_id: int, content: str, rrf: float) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        content=content,
        metadata=ChunkMetadata(
            source_project="sdd-kafka-databricks",
            source_type="adr",
            source_path=f"docs/adr/{chunk_id:03d}.md",
            source_anchor="Context",
            chunk_index=0,
            token_count=10,
        ),
        dense_distance=0.2,
        sparse_score=0.0,
        rrf_score=rrf,
        dense_rank=chunk_id,
        sparse_rank=None,
    )


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch: pytest.MonkeyPatch):
    """Any path to the real loader fails the test. Settings caches start clean."""

    def refuse() -> None:
        raise AssertionError("a unit test tried to load the real reranker model")

    monkeypatch.setattr(reranker, "get_model", refuse)
    get_settings_without_llm.cache_clear()
    yield
    get_settings_without_llm.cache_clear()


def install(monkeypatch: pytest.MonkeyPatch, model: FakeCrossEncoder) -> FakeCrossEncoder:
    monkeypatch.setattr(reranker, "get_model", lambda: model)
    return model


def ids(chunks) -> list[int]:
    return [c.id for c in chunks]


def test_reorders_by_rerank_score(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeCrossEncoder({"a": 0.1, "b": 0.9, "c": 0.5}))
    candidates = [chunk(1, "a", 0.03), chunk(2, "b", 0.02), chunk(3, "c", 0.01)]
    assert ids(reranker.rerank(QUESTION, candidates, top_k=3)) == [2, 3, 1]


def test_a_rerank_tie_breaks_by_rrf_score(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeCrossEncoder({"a": 0.5, "b": 0.5}))
    candidates = [chunk(1, "a", 0.01), chunk(2, "b", 0.03)]
    assert ids(reranker.rerank(QUESTION, candidates, top_k=2)) == [2, 1]


def test_a_tie_on_both_scores_breaks_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Candidates arrive in reverse id order: the key must not rely on input order."""
    install(monkeypatch, FakeCrossEncoder({"a": 0.5, "b": 0.5}))
    candidates = [chunk(9, "a", 0.02), chunk(4, "b", 0.02)]
    assert ids(reranker.rerank(QUESTION, candidates, top_k=2)) == [4, 9]


def test_no_candidates_returns_empty_without_loading_the_model() -> None:
    """The autouse fixture makes get_model raise; reaching it fails this test."""
    assert reranker.rerank(QUESTION, []) == []


def test_top_k_cuts_the_list_and_tolerates_fewer_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install(monkeypatch, FakeCrossEncoder({t: float(i) for i, t in enumerate("abcde")}))
    five = [chunk(i + 1, t, 0.01) for i, t in enumerate("abcde")]
    assert len(reranker.rerank(QUESTION, five, top_k=3)) == 3
    assert len(reranker.rerank(QUESTION, five[:2], top_k=3)) == 2


def test_top_k_defaults_to_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANK_TOP_K", "2")
    install(monkeypatch, FakeCrossEncoder({t: float(i) for i, t in enumerate("abcde")}))
    five = [chunk(i + 1, t, 0.01) for i, t in enumerate("abcde")]
    assert len(reranker.rerank(QUESTION, five)) == 2


def test_top_k_below_one_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeCrossEncoder({"a": 0.1}))
    with pytest.raises(ValueError, match="top_k must be >= 1"):
        reranker.rerank(QUESTION, [chunk(1, "a", 0.01)], top_k=0)


def test_a_pair_over_the_window_is_flagged_not_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """QUESTION is 4 words; with a window of 6, a 3-word chunk makes a 7-token pair."""
    long_text, short_text = "one two three", "one"
    install(monkeypatch, FakeCrossEncoder({long_text: 0.9, short_text: 0.1}, window=6))
    result = reranker.rerank(
        QUESTION, [chunk(1, long_text, 0.02), chunk(2, short_text, 0.01)], top_k=2
    )
    flags = {c.id: c.truncated for c in result}
    assert flags == {1: True, 2: False}


def test_every_retrieved_field_survives_into_the_reranked_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install(monkeypatch, FakeCrossEncoder({"a": 0.7}))
    original = chunk(7, "a", 0.0164)
    (result,) = reranker.rerank(QUESTION, [original], top_k=1)
    assert isinstance(result, RerankedChunk)
    assert result.model_dump(exclude={"rerank_score", "truncated"}) == original.model_dump()
    assert result.rerank_score == pytest.approx(0.7)


def test_predict_is_called_once_with_pairs_in_candidate_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = install(monkeypatch, FakeCrossEncoder({"a": 0.1, "b": 0.2, "c": 0.3}))
    candidates = [chunk(1, "a", 0.03), chunk(2, "b", 0.02), chunk(3, "c", 0.01)]
    reranker.rerank(QUESTION, candidates, top_k=3)
    assert model.calls == [[(QUESTION, "a"), (QUESTION, "b"), (QUESTION, "c")]]


def test_retrieve_and_rerank_asks_each_stage_for_its_own_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYBRID_TOP_K", "17")
    monkeypatch.setenv("RERANK_TOP_K", "4")
    seen: dict = {}
    candidates = [chunk(1, "a", 0.01)]

    def fake_retrieve(question, collections=None, top_k=None, conn=None):
        seen["retrieve_top_k"] = top_k
        return candidates

    def fake_rerank(question, given, top_k=None):
        seen["rerank_top_k"] = top_k
        seen["handed_over"] = given
        return []

    monkeypatch.setattr(pipeline, "retrieve", fake_retrieve)
    monkeypatch.setattr(pipeline, "rerank", fake_rerank)
    pipeline.retrieve_and_rerank(QUESTION)
    assert seen == {"retrieve_top_k": 17, "rerank_top_k": 4, "handed_over": candidates}
