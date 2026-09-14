"""Embedder — turns text into dense vectors for storage and retrieval.

The model is selected by ADR-004 (embedding model benchmark). Until that ADR is
Accepted, `settings.embedding_model` holds the baseline `bge-small-en-v1.5`.

Two call sites, deliberately treated differently:

- `embed_query` — one short string per user query, and users repeat queries
  within a session. Cached (Section 5I: `@lru_cache(maxsize=100)`, zero
  infrastructure cost).
- `embed_documents` — a batch over chunk texts at index time. NOT cached:
  index-time texts are unique by construction, so a cache would only consume
  memory without ever hitting.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Load the embedding model once per process.

    TODO(BUILD): implement for feature: corpus-indexing.
    """
    raise NotImplementedError("Implement in BUILD phase for feature: corpus-indexing")


@lru_cache(maxsize=100)
def embed_query(text: str) -> tuple[float, ...]:
    """Embed a single query string. Cached per Section 5I.

    Returns a tuple rather than a list on purpose: `lru_cache` hands every
    caller the *same* object, and a mutable list would let one caller corrupt
    the cached value for every subsequent one. Call sites that need a list for
    the pgvector adapter convert explicitly with `list(...)`.

    Chunk text must never be embedded through this function — see
    `embed_documents`.

    TODO(BUILD): implement for feature: corpus-indexing.
    """
    raise NotImplementedError("Implement in BUILD phase for feature: corpus-indexing")


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed a batch of chunk texts at index time. Deliberately not cached.

    Every chunk that reaches this function must already respect the token
    budget set in ADR-007 — the model truncates silently past its context
    window, and this function does not detect that. The budget assertion lives
    in the chunker, upstream.

    TODO(BUILD): implement for feature: corpus-indexing.
    """
    raise NotImplementedError("Implement in BUILD phase for feature: corpus-indexing")
