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

from data_platform_rag.config import get_settings_without_llm

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_INSTALL_HINT = (
    "  pip install sentence-transformers    # the full runtime, per pyproject\n"
    "  A first run needs network access to fetch the model weights; cached after."
)


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Load the embedding model once per process.

    The model name comes from `settings.embedding_model`, not a literal: ADR-004
    is still Planned, and when it lands the model changes in config, not here.
    ADR-013 records the name on the snapshot row so a swap forces a re-embed
    rather than silently mixing two embedding spaces.

    Loading is deliberately not silent about failing. A missing runtime is an
    environment problem with a one-line fix, and the alternative — an embedder
    that degrades to something that is not the configured model — would write
    384 floats per row that nothing could later identify as wrong.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise SystemExit(
            f"ERROR: sentence-transformers is not installed, so the corpus cannot "
            f"be embedded.\n{_INSTALL_HINT}"
        ) from exc

    model_name = get_settings_without_llm().embedding_model
    try:
        return SentenceTransformer(model_name)
    except Exception as exc:  # pragma: no cover - network/cache-dependent
        raise SystemExit(
            f"ERROR: could not load the embedding model {model_name!r}: {exc}\n"
            f"{_INSTALL_HINT}"
        ) from exc


@lru_cache(maxsize=100)
def embed_query(text: str) -> tuple[float, ...]:
    """Embed a single query string. Cached per Section 5I.

    Returns a tuple rather than a list on purpose: `lru_cache` hands every
    caller the *same* object, and a mutable list would let one caller corrupt
    the cached value for every subsequent one. Call sites that need a list for
    the pgvector adapter convert explicitly with `list(...)`.

    Chunk text must never be embedded through this function — see
    `embed_documents`.
    """
    vector = get_model().encode(text, normalize_embeddings=True)
    return tuple(float(value) for value in vector)


def embed_documents(texts: list[str], batch_size: int | None = None) -> list[list[float]]:
    """Embed a batch of chunk texts at index time. Deliberately not cached.

    Every chunk that reaches this function must already respect the token
    budget set in ADR-007 — the model truncates silently past its context
    window, and this function does not detect that. The budget assertion lives
    in the chunker, upstream.

    Vectors are L2-normalised at write time. That is not cosmetic: the HNSW index
    in `sql/02_indexes.sql` is built with `vector_cosine_ops`, and normalising
    keeps cosine distance and inner product equivalent — which is what lets a
    later retrieval change swap operators without a reindex.
    """
    if not texts:
        return []
    # An explicit override has to be a parameter: the settings accessor is an
    # lru_cache singleton, so a caller's `model_copy` would never be seen here.
    if batch_size is None:
        batch_size = get_settings_without_llm().embedding_batch_size
    vectors = get_model().encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [[float(value) for value in vector] for vector in vectors]
