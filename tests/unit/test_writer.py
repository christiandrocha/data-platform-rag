"""Unit tests for the pgvector writer's pre-transaction guards.

These are the checks that must run before a connection is opened (ADR-013): a
wrong-length vector is a refusal, not a rollback. They are database-free on
purpose, which is also what makes them worth testing without one.
"""

from __future__ import annotations

import pytest

from data_platform_rag.contracts import Chunk, ChunkMetadata
from data_platform_rag.indexer.writer import (
    DimensionMismatch,
    EmbeddingCountMismatch,
    guard_dimensions,
)

DIM = 384


def make_chunk(path: str = "docs/adr/ADR-0001.md", chunk_index: int = 0) -> Chunk:
    return Chunk(
        content="Context. Decision. Consequences.",
        collection="decisions",
        metadata=ChunkMetadata(
            source_project="sdd-kafka-databricks",
            source_type="adr",
            source_path=path,
            chunk_index=chunk_index,
            token_count=7,
        ),
    )


def test_matching_dimensions_pass() -> None:
    chunks = [make_chunk(), make_chunk(chunk_index=1)]
    embeddings = [[0.1] * DIM, [0.2] * DIM]
    guard_dimensions(chunks, embeddings, DIM)  # does not raise


def test_wrong_dimension_raises_naming_the_chunk() -> None:
    """The message must name the chunk, not a parameter index.

    Postgres would reject the vector too, but from inside a batch insert, where
    the only identifier available is a position in a parameter list.
    """
    chunks = [make_chunk(), make_chunk(path="docs/adr/ADR-0007.md", chunk_index=3)]
    embeddings = [[0.1] * DIM, [0.2] * 768]

    with pytest.raises(DimensionMismatch) as exc:
        guard_dimensions(chunks, embeddings, DIM)

    message = str(exc.value)
    assert "docs/adr/ADR-0007.md" in message
    assert "chunk_index=3" in message
    assert "768" in message and "384" in message


def test_empty_batch_is_allowed() -> None:
    """A project with no chunks is a data question, not a guard failure."""
    guard_dimensions([], [], DIM)


@pytest.mark.parametrize(
    ("n_chunks", "n_embeddings"),
    [(2, 1), (1, 2), (3, 0)],
)
def test_length_mismatch_raises(n_chunks: int, n_embeddings: int) -> None:
    """zip() would truncate to the shorter list and write a corpus missing its tail."""
    chunks = [make_chunk(chunk_index=i) for i in range(n_chunks)]
    embeddings = [[0.0] * DIM for _ in range(n_embeddings)]

    with pytest.raises(EmbeddingCountMismatch) as exc:
        guard_dimensions(chunks, embeddings, DIM)

    assert str(n_chunks) in str(exc.value)
    assert str(n_embeddings) in str(exc.value)


def test_guard_checks_every_chunk_not_just_the_first() -> None:
    """A guard that only sampled would pass a batch with one bad vector in it."""
    chunks = [make_chunk(chunk_index=i) for i in range(5)]
    embeddings = [[0.0] * DIM for _ in range(5)]
    embeddings[4] = [0.0] * 383

    with pytest.raises(DimensionMismatch) as exc:
        guard_dimensions(chunks, embeddings, DIM)
    assert "chunk_index=4" in str(exc.value)
