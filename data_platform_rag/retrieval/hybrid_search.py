"""Hybrid search — dense (pgvector) + sparse (tsvector) fused by RRF.

Implements ADR-003, with the sparse side filtered by document frequency per
ADR-017. The fusion happens in one query, not in Python: both ranked
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

from data_platform_rag.contracts import (
    ChunkMetadata,
    Collection,
    RetrievedChunk,
    SparseTerm,
    SparseTerms,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    import psycopg

# ADR-003 fixes the RRF rank constant at 60 (Cormack et al., 2009). It is a
# module constant rather than a settings field on purpose: tuning it belongs to
# ADR-008 under RAGAS, not to a runtime knob that could be turned by accident.
RRF_K = 60

VALID_COLLECTIONS: frozenset[str] = frozenset(get_args(Collection))

# ADR-017: the sparse side OR-joins the lexemes `plainto_tsquery` produces, minus
# every lexeme found in more chunks than the largest single source file contains.
#
# One fragment, shared by the search and by `sparse_terms`, so the report of what
# the filter did cannot describe a different filter from the one that ranked.
#
# - `query_terms` splits Postgres' own tsquery output on the separator
#   `plainto_tsquery` writes. Each fragment is already quoted by Postgres and is
#   cast straight back to `tsquery`, so no user text reaches tsquery syntax and
#   sanitising stays with `plainto_tsquery`. A lexeme never contains a space, so
#   ' & ' cannot occur inside one.
# - `df_cutoff` and `term_df` read `chunks` in the same statement that searches
#   it. `chunks` holds one live snapshot per project (ADR-013), so both numbers
#   always describe the snapshot being searched. Both are taken over the whole
#   index, not the collection filter: the rule is a property of the corpus.
SPARSE_TERMS_CTES = """
query_terms AS (
  SELECT DISTINCT term
  FROM regexp_split_to_table(
         plainto_tsquery('english', %(query_text)s)::text, ' & ') AS term
  WHERE term <> ''
),
df_cutoff AS (
  SELECT max(file_chunks) AS max_file_chunks
  FROM (
    SELECT count(*) AS file_chunks
    FROM chunks
    GROUP BY source_project, source_path
  ) AS per_file
),
term_df AS (
  SELECT t.term,
         (SELECT count(*) FROM chunks WHERE content_tsv @@ t.term::tsquery) AS df
  FROM query_terms t
)"""

# Every column ChunkMetadata needs, plus the three scores. `content_tsv` is not
# selected: it is the sparse index's input, never output.
#
# When every lexeme is above the cutoff, `string_agg` over nothing is NULL,
# `ts_rank_cd(..., NULL)` is NULL, and the COALESCE makes it 0: the sparse list is
# empty, as it is today for a zero match -- not an error, not the unfiltered OR
# that ADR-015 rejected.
#
# Ties in either ranked list break by id, so a rank never depends on the
# physical order of rows in the heap.
_HYBRID_TAIL = """,
sparse_query AS (
  SELECT string_agg(term, ' | ' ORDER BY term)::tsquery AS tsq
  FROM term_df, df_cutoff
  WHERE df <= max_file_chunks
),
candidates AS (
  SELECT
    id, content, collection,
    source_project, source_type, source_path, source_anchor,
    adr_id, topic, status, keywords, chunk_index, token_count,
    embedding <=> %(query_vector)s::vector AS dense_dist,
    COALESCE(ts_rank_cd(content_tsv, (SELECT tsq FROM sparse_query)), 0) AS sparse_score
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
# Module constants only: user text reaches the query as %(query_text)s, never here.
HYBRID_QUERY = "WITH" + SPARSE_TERMS_CTES + _HYBRID_TAIL  # nosec B608

# The filter's decision per lexeme. The cutoff comes back on every row and, via
# the LEFT JOIN, also when the query has no lexemes at all.
_SPARSE_TERMS_TAIL = """
SELECT c.max_file_chunks AS cutoff, t.term, t.df, t.df <= c.max_file_chunks AS kept
FROM df_cutoff c
LEFT JOIN term_df t ON TRUE
ORDER BY t.df DESC, t.term ASC
"""
SPARSE_TERMS_QUERY = "WITH" + SPARSE_TERMS_CTES + _SPARSE_TERMS_TAIL  # nosec B608


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


def sparse_terms(conn: psycopg.Connection, query_text: str) -> SparseTerms:
    """Report what the ADR-017 filter keeps and drops for one query.

    Runs the same CTEs as `search`, so it cannot disagree with the ranking. It is
    for tracing a result to the filter (the recall report, `make ask`), not for
    retrieval: `search` does not call it.
    """
    with conn.cursor() as cur:
        cur.execute(SPARSE_TERMS_QUERY, {"query_text": query_text})
        rows = cur.fetchall()
    cutoff = rows[0][0] if rows else None
    terms = [
        SparseTerm(term=term, df=df, kept=bool(kept))
        for _, term, df, kept in rows
        if term is not None
    ]
    return SparseTerms(cutoff=cutoff, terms=terms)
