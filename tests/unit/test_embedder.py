"""Unit tests for the embedder's caching contract.

The docstrings in `embedder.py` state behaviour that is easy to regress silently:
`embed_query` is cached and returns a tuple so callers cannot corrupt the shared
cached value, and `embed_documents` is deliberately NOT cached because index-time
texts are unique by construction.

A fake encoder is injected throughout, so the suite needs no model and no
network — the same posture slice 1's tests took.

`get_settings` is stubbed for the same reason. `Settings` requires
`anthropic_api_key`, which is read from a gitignored `.env`; a unit test that
constructs it passes on the author's machine and fails in CI, where no `.env`
exists. These tests are about caching and batching and have no business needing
a credential.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from data_platform_rag.indexer import embedder

DIM = 384
BATCH = 32


@pytest.fixture(autouse=True)
def stub_settings(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """No real Settings, so no `.env` and no credential are needed."""
    settings = SimpleNamespace(embedding_batch_size=BATCH, embedding_model="stub/model")
    monkeypatch.setattr(embedder, "get_settings", lambda: settings)
    return settings


class FakeEncoder:
    """Counts calls, so "was this cached?" is an assertion rather than a belief."""

    def __init__(self) -> None:
        self.calls = 0

    def encode(self, text_or_texts, **kwargs):
        self.calls += 1
        if isinstance(text_or_texts, str):
            return [0.5] * DIM
        return [[0.5] * DIM for _ in text_or_texts]


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> FakeEncoder:
    encoder = FakeEncoder()
    embedder.embed_query.cache_clear()
    monkeypatch.setattr(embedder, "get_model", lambda: encoder)
    yield encoder
    embedder.embed_query.cache_clear()


def test_embed_query_returns_a_tuple(fake_model: FakeEncoder) -> None:
    """A list would let one caller mutate the value every later caller receives."""
    assert isinstance(embedder.embed_query("what is CDC?"), tuple)


def test_embed_query_is_cached(fake_model: FakeEncoder) -> None:
    first = embedder.embed_query("what is CDC?")
    second = embedder.embed_query("what is CDC?")
    assert first is second
    assert fake_model.calls == 1


def test_embed_query_distinguishes_queries(fake_model: FakeEncoder) -> None:
    embedder.embed_query("question one")
    embedder.embed_query("question two")
    assert fake_model.calls == 2


def test_embed_documents_is_not_cached(fake_model: FakeEncoder) -> None:
    """Index-time texts are unique, so a cache would only consume memory."""
    embedder.embed_documents(["a chunk"])
    embedder.embed_documents(["a chunk"])
    assert fake_model.calls == 2


def test_embed_documents_returns_one_vector_per_text(fake_model: FakeEncoder) -> None:
    vectors = embedder.embed_documents(["one", "two", "three"])
    assert len(vectors) == 3
    assert all(len(v) == DIM for v in vectors)


def test_embed_documents_short_circuits_on_empty(fake_model: FakeEncoder) -> None:
    """An empty batch must not load a model to answer with an empty list."""
    assert embedder.embed_documents([]) == []
    assert fake_model.calls == 0


def test_embed_documents_normalises(monkeypatch: pytest.MonkeyPatch) -> None:
    """normalize_embeddings=True is load-bearing: the HNSW index is cosine.

    Asserted by capturing the kwarg rather than by measuring a norm, because a
    fake encoder's output norm says nothing about what the real model was asked.
    """
    captured: dict = {}

    class Recorder:
        def encode(self, texts, **kwargs):
            captured.update(kwargs)
            return [[1.0] * DIM for _ in texts]

    monkeypatch.setattr(embedder, "get_model", lambda: Recorder())
    embedder.embed_documents(["chunk"])
    assert captured["normalize_embeddings"] is True


def test_embed_documents_honours_an_explicit_batch_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--batch-size` has to arrive as a parameter, not via settings.

    `get_settings()` is an `lru_cache` singleton, so a caller that builds a
    modified copy of Settings changes nothing that this function can see. The
    first version of the CLI did exactly that and the flag was silently ignored.
    """
    captured: dict = {}

    class Recorder:
        def encode(self, texts, **kwargs):
            captured.update(kwargs)
            return [[0.0] * DIM for _ in texts]

    monkeypatch.setattr(embedder, "get_model", lambda: Recorder())
    embedder.embed_documents(["a", "b"], batch_size=7)
    assert captured["batch_size"] == 7


def test_embed_documents_falls_back_to_configured_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class Recorder:
        def encode(self, texts, **kwargs):
            captured.update(kwargs)
            return [[0.0] * DIM for _ in texts]

    monkeypatch.setattr(embedder, "get_model", lambda: Recorder())
    embedder.embed_documents(["a"])
    assert captured["batch_size"] == BATCH
