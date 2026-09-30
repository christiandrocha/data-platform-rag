# Dense retrieval — one exact cosine ranking

Retrieval is dense-only since ADR-018 (2026-09-30), which superseded ADR-003's
hybrid dense + sparse fusion. This page was `rag/hybrid-retrieval.md` until then.

## The one-query implementation

Source of truth: `DENSE_QUERY` in `data_platform_rag/retrieval/dense_search.py`.
This is a copy for reading; if the two differ, the code wins and this page is the
defect. Placeholders are psycopg (`%(name)s`), bound by `search()`.

```sql
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
  c.*,  -- every ChunkMetadata column, plus dense_dist
  d.dense_rank
FROM candidates c
JOIN dense_ranked d USING (id)
ORDER BY d.dense_rank ASC
```

Four details worth knowing before changing it:

- **The search is exact.** Every candidate's distance, then an `ORDER BY` with an
  `id` tiebreak: a Seq Scan at 304 rows. An HNSW index scan would be approximate
  and could reorder a ranking with no change to the corpus. `sql/99_verify.sql`
  §6 proves the index usable; ADR-004 owns when it becomes worth using.
- **`RetrievedChunk` has five fields**: `id`, `content`, `metadata`,
  `dense_distance`, `dense_rank`. ADR-018 kept `rrf_score`, `sparse_score` and
  `sparse_rank` as constants for comparability. ADR-019 Amendment 1 removed them,
  and `extra="forbid"` rejects a caller that still passes one.
- **No user text reaches SQL.** `search()` takes a vector; `pipeline.retrieve`
  embeds the question.
- **Ties break by `id`.** Without it a tied rank follows heap order and can change
  after a reindex. Found under ADR-015 on the sparse side.

## How the sparse side left

- `plainto_tsquery` ANDs every term, so the sparse side was empty for question
  input: rows for 7 of 50 golden questions (ADR-003 Amendment 1 §B).
- **ADR-015** OR-joined every lexeme: rejected, recall did not move, q001 lost
  rank 1 to an exact RRF tie.
- **ADR-017** OR-joined only lexemes at or below a document-frequency cutoff (the
  chunk count of the largest file, 68): rejected. Sparse rows for 49/50, but k=3
  moved +1 against a margin of +2, and q007 lost its top-3 path. Chunks ranked
  mid-list on both sides outscored a dense rank 1.
- **ADR-018** removed it: k=3 38 → 38, nothing lost from the top 3, the 43
  sparse-empty questions ranked identically.

Both repairs failed on RRF's equal ballot. A sparse side comes back only with a
weight RAGAS can tune. `content_tsv` and its GIN index stay in the schema,
unused, so that would be a query change, not a migration.

## Parameters and rationale

| Parameter | Value | Justification |
|-----------|-------|--------------|
| dense limit | `settings.hybrid_top_k` (currently 20) | Cover-and-rerank pattern. The setting keeps its pre-ADR-018 name (README Known Gaps) |
| final limit | `settings.hybrid_top_k` | Feed to reranker, keep `settings.rerank_top_k` (currently 3) |

## What the score cannot do

**No retrieval score can drive the fallback.**

- `rrf_score` was `1/61` for every top chunk, in scope or not (ADR-018 P2,
  measured). It was removed in ADR-019 Amendment 1.
- Top-1 cosine similarity (`1 - dense_distance`) was measured by ADR-019 and does
  not separate either. The highest out-of-scope question (q005, 0.7360) outscores
  14 of the 45 in-scope ones (lowest: q027, 0.6040). Similarity measures topic
  proximity, not answerability: "Flink versus Kafka Streams" sits next to a corpus
  about Kafka.

ADR-006's score gate is superseded. The LLM sends the fallback under rule 3.
`settings.fallback_threshold` was removed in ADR-019 Amendment 1.
`make retrieval-recall` prints the four separability numbers on every run, so a
new embedding model (ADR-004) can re-test the question.
