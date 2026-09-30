"""Dense search — pgvector cosine distance, exact, one ranked list (ADR-018).

Implemented ADR-003's fusion of a dense and a sparse list until ADR-018, which
ranks by cosine distance alone. The ranking happens in one query, not in Python.

Three things about the previous version of this module are corrected here, and
all three are recorded in the feature's DESIGN:

1. It used `$1`/`$2`/`$3`, which is asyncpg syntax. This project uses psycopg.
   The query had never been executed.
2. Its `SELECT` returned two of the five fields `ChunkMetadata` requires, so it
   could not build the contract it was supposed to produce.
3. It used `COALESCE(rank, 999)` for a missing side, which contributes
   `1/(60+999)` -- 5.8% of a rank-1 contribution, not the zero ADR-003
   specifies. See ADR-003 Amendment 1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, get_args

from data_platform_rag.contracts import ChunkMetadata, Collection, RetrievedChunk

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    import psycopg

# ADR-003 fixed the RRF rank constant at 60 (Cormack et al., 2009). Since ADR-018
# it only computes `rrf_score = 1/(60 + dense_rank)`, kept so the contract and
# artifacts stay comparable across the change. It is a
# module constant rather than a settings field on purpose: tuning it belongs to
# ADR-008 under RAGAS, not to a runtime knob that could be turned by accident.
RRF_K = 60

VALID_COLLECTIONS: frozenset[str] = frozenset(get_args(Collection))

# ADR-018: retrieval ranks by cosine distance alone. The sparse side and the
# fusion were removed after two repairs were measured and rejected (ADR-015,
# ADR-017), both on RRF's equal ballot. This module was `hybrid_search.py` until
# ADR-018 was accepted; superseded and rejected ADRs still use that name.
#
# Every column ChunkMetadata needs, plus the scores RetrievedChunk carries. The
# contract is unchanged: `sparse_score` is 0.0 and `sparse_rank` NULL, which it
# already reads as "the sparse side did not rank this chunk", and `rrf_score` is
# 1/(60 + dense_rank) -- exactly what a dense-only chunk scored under the fusion,
# so artifacts stay comparable across the change.
#
# The search is exact: every candidate's distance, then ORDER BY with an id
# tiebreak. An HNSW index scan would be approximate and could reorder a ranking
# with no change to the corpus (ADR-018, Decision).
DENSE_QUERY = """
WITH candidates AS (
  SELECT
    id, content, collection,
    source_project, source_type, source_path, source_anchor,
    adr_id, topic, status, keywords, chunk_index, token_count,
    embedding <=> %(query_vector)s::vector AS dense_dist
  FROM chunks
  WHERE collection = ANY(%(collections)s::text[])
),
dense_ranked AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY dense_dist ASC, id ASC) AS dense_rank
  FROM candidates
  ORDER BY dense_dist ASC, id ASC
  LIMIT %(top_k)s
)
SELECT
  c.id, c.content, c.collection,
  c.source_project, c.source_type, c.source_path, c.source_anchor,
  c.adr_id, c.topic, c.status, c.keywords, c.chunk_index, c.token_count,
  c.dense_dist, 0.0 AS sparse_score,
  d.dense_rank, NULL::bigint AS sparse_rank,
  1.0 / (%(rrf_k)s + d.dense_rank) AS rrf_score
FROM candidates c
JOIN dense_ranked d USING (id)
ORDER BY d.dense_rank ASC
"""


def build_dense_query(collections: list[str]) -> str:
    """Validate the collection filter and return the query.

    The previous version accepted `collections` and ignored it. It is now
    validated against the `Collection` literal: an unknown name would otherwise
    filter to nothing and return an empty result that looks like "no matches"
    rather than "you asked for a collection that does not exist".
    """
    if not collections:
        raise ValueError("At least one collection must be specified")
    unknown = sorted(set(collections) - VALID_COLLECTIONS)
    if unknown:
        raise ValueError(
            f"Unknown collection(s): {', '.join(unknown)}. "
            f"Valid: {', '.join(sorted(VALID_COLLECTIONS))}"
        )
    return DENSE_QUERY


def row_to_chunk(row: dict[str, Any]) -> RetrievedChunk:
    """Map one result row onto the contract.

    No field is defaulted or invented: every value comes from the row, and a
    missing key raises rather than being filled in. ADR-010 makes the contract
    the source of truth, and a silently defaulted `token_count` would be a lie
    told in a citation.
    """
    return RetrievedChunk(
        id=row["id"],
        content=row["content"],
        metadata=ChunkMetadata(
            source_project=row["source_project"],
            source_type=row["source_type"],
            source_path=row["source_path"],
            source_anchor=row["source_anchor"],
            adr_id=row["adr_id"],
            topic=row["topic"],
            status=row["status"],
            keywords=row["keywords"],
            chunk_index=row["chunk_index"],
            token_count=row["token_count"],
        ),
        dense_distance=float(row["dense_dist"]),
        sparse_score=float(row["sparse_score"]),
        rrf_score=float(row["rrf_score"]),
        dense_rank=row["dense_rank"],
        sparse_rank=row["sparse_rank"],
    )


def search(
    conn: psycopg.Connection,
    *,
    query_vector: Sequence[float],
    collections: list[Collection],
    top_k: int,
) -> list[RetrievedChunk]:
    """Run the dense-only query and return ranked chunks.

    Takes an embedding rather than producing one, and takes an open connection
    rather than opening one -- the same split `indexer/writer.py` uses. It lets
    an integration test drive ranking with hand-chosen vectors without loading a
    model. It takes no query text: since ADR-018 the text's only role is to be
    embedded, which `pipeline.retrieve` does, and none of it reaches SQL.
    """
    from psycopg.rows import dict_row

    query = build_dense_query(list(collections))
    params = {
        "query_vector": list(query_vector),
        "collections": list(collections),
        "top_k": top_k,
        "rrf_k": RRF_K,
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return [row_to_chunk(row) for row in cur.fetchall()]
