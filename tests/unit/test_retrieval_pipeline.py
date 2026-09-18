"""Unit tests for `retrieve` — its validation and its defaults.

No model, no database: `embed_query` and `search` are both stubbed. What is under
test is the decision-making around them, which is where the behaviour DEFINE
specified actually lives.
"""

from __future__ import annotations

import pytest

from data_platform_rag.retrieval import pipeline

DIM = 384


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Stub the model and the database, and record what `search` was asked for."""
    calls: dict = {}

    monkeypatch.setattr(pipeline, "embed_query", lambda text: tuple([0.1] * DIM))

    def fake_search(conn, *, query_text, query_vector, collections, top_k):
        calls.update(
            query_text=query_text,
            query_vector=query_vector,
            collections=collections,
            top_k=top_k,
        )
        return []

    monkeypatch.setattr(pipeline, "search", fake_search)

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(pipeline, "connect", lambda dsn: FakeConn())
    return calls


@pytest.mark.parametrize("question", ["", "   ", "\n"])
def test_blank_question_raises(question: str, captured: dict) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        pipeline.retrieve(question)


def test_default_searches_both_collections(captured: dict) -> None:
    """The intent classifier deferred to a default, per DEFINE's non-goal."""
    pipeline.retrieve("why Snowpipe Streaming?")
    assert sorted(captured["collections"]) == ["architecture", "decisions"]


def test_empty_collections_list_raises_rather_than_meaning_everything(captured: dict) -> None:
    """`None` means both; `[]` is a caller error. Conflating them widens a search silently."""
    with pytest.raises(ValueError, match="At least one collection"):
        pipeline.retrieve("a question", collections=[])


def test_unknown_collection_raises(captured: dict) -> None:
    with pytest.raises(ValueError, match="Unknown collection"):
        pipeline.retrieve("a question", collections=["adrs"])


def test_explicit_collection_is_passed_through(captured: dict) -> None:
    pipeline.retrieve("a question", collections=["decisions"])
    assert captured["collections"] == ["decisions"]


def test_top_k_defaults_to_settings(captured: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        pipeline, "get_settings", lambda: SimpleNamespace(hybrid_top_k=7, database_url="x")
    )
    pipeline.retrieve("a question")
    assert captured["top_k"] == 7


def test_explicit_top_k_overrides_settings(captured: dict) -> None:
    pipeline.retrieve("a question", top_k=3)
    assert captured["top_k"] == 3


@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_top_k_raises(bad: int, captured: dict) -> None:
    with pytest.raises(ValueError, match="top_k"):
        pipeline.retrieve("a question", top_k=bad)


def test_question_text_reaches_the_sparse_side_unmodified(captured: dict) -> None:
    """The same string embeds and drives plainto_tsquery; neither may be pre-mangled."""
    question = "How does each project handle CDC deletes?"
    pipeline.retrieve(question)
    assert captured["query_text"] == question


def test_supplied_connection_is_used_without_opening_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "embed_query", lambda text: tuple([0.1] * DIM))
    monkeypatch.setattr(pipeline, "search", lambda conn, **kw: ["sentinel"])

    def explode(dsn):  # pragma: no cover - must never run
        raise AssertionError("retrieve opened a connection despite being given one")

    monkeypatch.setattr(pipeline, "connect", explode)
    assert pipeline.retrieve("a question", conn=object()) == ["sentinel"]
