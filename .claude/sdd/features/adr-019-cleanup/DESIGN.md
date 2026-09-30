# DESIGN: Remove the fields and the setting that carry nothing

> Implements [DEFINE.md](DEFINE.md). Decision: ADR-019, recorded as its Amendment 1.

## Metadata

| Field | Value |
|-------|-------|
| Feature | adr-019-cleanup |
| Depends on | [DEFINE.md](DEFINE.md), 14/15 |
| Status | Approved (lean process, author 2026-09-30) |
| ADR needed | No new ADR. ADR-019 Amendment 1 records the removal |

## Architecture overview

One commit. It is behaviour-neutral, and a recall run proves it.

| File | Change |
|---|---|
| `contracts.py` | `RetrievedChunk` = `id`, `content`, `metadata`, `dense_distance`, `dense_rank`. `dense_rank` becomes required (`int`, ≥ 1): dense-only means every returned chunk has one |
| `retrieval/dense_search.py` | `DENSE_QUERY` drops `sparse_score`, `sparse_rank`, `rrf_score` and the `%(rrf_k)s` parameter. `RRF_K` removed. `row_to_chunk` maps five fields |
| `config.py`, `.env.example` | `fallback_threshold` / `FALLBACK_THRESHOLD` removed |
| `scripts/retrieval_recall.py` | Ranking rows = rank, project, path, anchor, dense_rank, dense_distance. `has_sparse_rows` reads `row.get("sparse_rank")`, so old baselines still work. `top_rrf_score(s)`, `has_sparse_rows`, `questions_with_sparse_rows` and the "sparse rows" printouts are dropped. The identical-rankings line stays, relabelled for today's baselines, where every question qualifies |
| `scripts/ask.py` | Columns `# dense sim source` |
| `sql/99_verify.sql` §5 | The mirrored query drops the constant columns |
| tests | contract, query shape, integration, recall (old-format baseline) |
| KB | `pydantic/models.md`, `pydantic/config-pattern.md`, `rag/dense-retrieval.md` |
| ADR-019 | Amendment 1, listing what was removed and the neutrality run |

**Why `dense_rank` becomes required.** It was optional because a chunk could come
from the sparse side alone. That case no longer exists, and an optional field that
is never None describes a mechanism that is gone.

**Ordering is unchanged:** `ORDER BY d.dense_rank ASC`. The fields removed never
took part in it.

## Data contracts

```python
class RetrievedChunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: int
    content: str
    metadata: ChunkMetadata
    dense_distance: float = Field(ge=0.0)
    dense_rank: int = Field(ge=1)
```

`extra="forbid"` makes a stale `rrf_score=` fail loudly instead of being silently
dropped. That is the acceptance test. It applies to `RerankedChunk` by
inheritance. Its `rerank_score` is declared, so it is unaffected.

## Retrieval and RAG-specific concerns

- [x] Chunking, HNSW, schema: untouched.
- [x] Query pattern: the same plan, three fewer constant columns. `99_verify.sql` §5
      is updated to match, and its plan shape (Seq Scan, WindowAgg) is unchanged.
- [x] RAGAS: cannot run. Regression risk: none. The neutrality run proves it.

## Test plan

- Unit: the contract rejects `rrf_score`, and `dense_rank` is required and ≥ 1;
  `Settings` ignores `FALLBACK_THRESHOLD` and lacks the attribute; the query has
  no constant columns and no `rrf_k`; `row_to_chunk` round-trips; the recall
  script's `identical_rankings` works on an old-format baseline
- Integration: the existing dense-search tests, with score assertions moved from
  `rrf_score` to `dense_rank`
- Manual: `make retrieval-recall baseline=.claude/dev/reports/retrieval-recall-20260930-185210.json`
  → 38/44/46, 0 lost, 50/50 identical. Then the DEFINE grep

## Rollout plan

- No migration, no flag. One commit.
- Rollback: `git revert`. Nothing downstream reads the removed fields: there is no
  generation, UI or Langfuse wiring yet.
- A deployment that still sets `FALLBACK_THRESHOLD` keeps starting
  (`extra="ignore"`), which the unit test asserts.
