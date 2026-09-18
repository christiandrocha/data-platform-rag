"""Retrieval pipeline — question in, ranked chunks out.

Today this is embed-then-search. It is the module the repo map reserves for the
retrieval stage, and it grows to carry intent classification (ADR-002) and
reranking (ADR-005) as those land. Both are deliberate non-goals here: the
`collections` default of "both" is what stands in for the classifier, stated as
a default rather than hidden inside a branch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from data_platform_rag.config import get_settings
from data_platform_rag.contracts import Collection, RetrievedChunk
from data_platform_rag.indexer.embedder import embed_query
from data_platform_rag.indexer.writer import connect
from data_platform_rag.retrieval.hybrid_search import build_hybrid_query, search

if TYPE_CHECKING:  # pragma: no cover - typing only
    import psycopg

ALL_COLLECTIONS: list[Collection] = list(get_args(Collection))


def retrieve(
    question: str,
    collections: list[Collection] | None = None,
    top_k: int | None = None,
    conn: psycopg.Connection | None = None,
) -> list[RetrievedChunk]:
    """Embed a question and return fused, ranked chunks.

    `collections=None` means both collections. That is the intent classifier's
    job deferred to a default, not an accident: choosing collections per question
    is BRAINSTORM Option 2 and has its own open question about whether it needs
    an LLM at all.

    An explicitly empty list still raises. "No collections" is a caller error,
    not a request for everything -- the two cases are far apart and conflating
    them would turn a bug into a silently broader search.

    `conn` is for callers that already hold one; the default opens and closes its
    own, which is what a one-shot CLI wants.
    """
    if not question or not question.strip():
        raise ValueError("question must be a non-empty string")
    if collections is None:
        collections = list(ALL_COLLECTIONS)

    # Validated here, before the model is loaded and before a connection is
    # opened. `search` validates too -- it is the boundary that must not be
    # bypassed -- but leaving it only there means an unknown collection name
    # costs an embedding call and then surfaces from inside the database layer.
    build_hybrid_query(list(collections))

    settings = get_settings()
    effective_top_k = settings.hybrid_top_k if top_k is None else top_k
    if effective_top_k < 1:
        raise ValueError(f"top_k must be >= 1, got {effective_top_k}")

    # Embedded before the connection is opened: the model load is the slow and
    # failure-prone step, and holding a connection across it buys nothing.
    query_vector = list(embed_query(question))

    if conn is not None:
        return search(
            conn,
            query_text=question,
            query_vector=query_vector,
            collections=collections,
            top_k=effective_top_k,
        )

    with connect(str(settings.database_url)) as own_conn:
        return search(
            own_conn,
            query_text=question,
            query_vector=query_vector,
            collections=collections,
            top_k=effective_top_k,
        )
