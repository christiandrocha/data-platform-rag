"""Hybrid search — dense (pgvector) + sparse (tsvector) fused by RRF.

Implements ADR-003. The fusion happens in one query, not in Python: both ranked
lists are computed over the same pre-filtered candidate set and joined, so a
single round trip returns the fused ordering.

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

# ADR-003 fixes the RRF rank constant at 60 (Cormack et al., 2009). It is a
# module constant rather than a settings field on purpose: tuning it belongs to
# ADR-008 under RAGAS, not to a runtime knob that could be turned by accident.
RRF_K = 60

VALID_COLLECTIONS: frozenset[str] = frozenset(get_args(Collection))

# Every column ChunkMetadata needs, plus the three scores. `content_tsv` is not
# selected: it is the sparse index's input, never output.
#
# The sparse side is plain `plainto_tsquery`, which ANDs every term, so it is
# empty for most question-shaped input (ADR-003 Amendment 1 §B). OR-joining the
# lexemes was tried and rejected by measurement (ADR-015, Outcome).
#
# Ties in either ranked list break by id, so a rank never depends on the
# physical order of rows in the heap.
HYBRID_QUERY = """
WITH candidates AS (
  SELECT
    id, content, collection,
    source_project, source_type, source_path, source_anchor,
    adr_id, topic, status, keywords, chunk_index, token_count,
    embedding <=> %(query_vector)s::vector AS dense_dist,
    ts_rank_cd(content_tsv, plainto_tsquery('english', %(query_text)s)) AS sparse_score
  FROM chunks
  WHERE collection = ANY(%(collections)s::text[])
),
dense_ranked AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY dense_dist ASC, id ASC) AS dense_rank
  FROM candidates
  ORDER BY dense_dist ASC, id ASC
  LIMIT %(top_k)s
),
sparse_ranked AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY sparse_score DESC, id ASC) AS sparse_rank
  FROM candidates
  WHERE sparse_score > 0
  ORDER BY sparse_score DESC, id ASC
  LIMIT %(top_k)s
)
SELECT
  c.id, c.content, c.collection,
  c.source_project, c.source_type, c.source_path, c.source_anchor,
  c.adr_id, c.topic, c.status, c.keywords, c.chunk_index, c.token_count,
  c.dense_dist, c.sparse_score,
  d.dense_rank, s.sparse_rank,
  COALESCE(1.0 / (%(rrf_k)s + d.dense_rank), 0)
  + COALESCE(1.0 / (%(rrf_k)s + s.sparse_rank), 0) AS rrf_score
FROM candidates c
LEFT JOIN dense_ranked  d USING (id)
LEFT JOIN sparse_ranked s USING (id)
WHERE d.dense_rank IS NOT NULL OR s.sparse_rank IS NOT NULL
ORDER BY rrf_score DESC, c.id ASC
LIMIT %(top_k)s
"""


def build_hybrid_query(collections: list[str]) -> str:
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
    return HYBRID_QUERY


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
    query_text: str,
    query_vector: Sequence[float],
    collections: list[Collection],
    top_k: int,
) -> list[RetrievedChunk]:
    """Run the fused query and return ranked chunks.

    Takes an embedding rather than producing one, and takes an open connection
    rather than opening one -- the same split `indexer/writer.py` uses. It lets
    an integration test drive ranking with hand-chosen vectors and assert on the
    RRF arithmetic without loading a model.
    """
    from psycopg.rows import dict_row

    query = build_hybrid_query(list(collections))
    params = {
        "query_vector": list(query_vector),
        "query_text": query_text,
        "collections": list(collections),
        "top_k": top_k,
        "rrf_k": RRF_K,
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return [row_to_chunk(row) for row in cur.fetchall()]
