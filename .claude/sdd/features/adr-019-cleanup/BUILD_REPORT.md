# BUILD REPORT: Remove the fields and the setting that carry nothing

## Metadata

| Field | Value |
|-------|-------|
| Feature | adr-019-cleanup |
| DEFINE | [DEFINE.md](DEFINE.md) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| ADR | [ADR-019](../../../../docs/adr/ADR-019-similarity-separability-decides-the-fallback-gate.md) Amendment 1 (no new ADR, author 2026-09-30) |
| Start date | 2026-09-30 |
| End date | 2026-09-30 |
| PR | [#26](https://github.com/christiandrocha/data-platform-rag/pull/26), merged by rebase 2026-10-02 |

## What was built

One commit:

- `contracts.py`: `RetrievedChunk` = `id`, `content`, `metadata`,
  `dense_distance`, `dense_rank` (required). `extra="forbid"`
- `retrieval/dense_search.py`: `RRF_K` and the constant columns removed.
  `row_to_chunk` maps five fields
- `config.py`, `.env.example`: `fallback_threshold` / `FALLBACK_THRESHOLD` removed
- `scripts/retrieval_recall.py`: new artifacts drop `rrf_score`, `sparse_rank`,
  `top_rrf_score(s)`, `has_sparse_rows` and `questions_with_sparse_rows`.
  `has_sparse_rows` reads `.get("sparse_rank")`, so old baselines still work. The
  "sparse rows" printouts were removed, and the identical-rankings line was
  relabelled
- `scripts/ask.py`: columns `# dense sim source`
- `sql/99_verify.sql` §5: the mirrored query drops the constant columns
- tests: contract (removed fields rejected, `dense_rank` required),
  `tests/unit/test_config.py` (new: `FALLBACK_THRESHOLD` ignored), query shape
  (no constant columns), integration (order and determinism asserted on
  `dense_rank` and `dense_distance`), and recall (old-format baseline, new-format
  rows). The test count went from 227 to 232
- KB: `pydantic/models.md`, `pydantic/config-pattern.md`, `rag/dense-retrieval.md`.
  Also README Known Gaps and ADR-019 Amendment 1

## The neutrality check

`make retrieval-recall baseline=.claude/dev/reports/retrieval-recall-20260930-185210.json`
→ `-20260930-192021.json`:

```
  A1  k=3 found:   38 -> 38 /57  (+0)
  A2  top-3 paths lost: 0
  A3  k=10 found:  44 -> 44 /57
      k=20 found:  46 -> 46 /57
      questions ranked identically: 50/50
```

Every `dense_distance` and `top_similarity` is equal to the baseline's, and the
separability numbers are unchanged (0.6040 / 0.7360).

## What deviated from design

- **DEFINE's grep allowed only the recall script's reading of old baselines.** It
  also finds three comments that name the removed fields as history
  (`contracts.py` docstring, the `dense_search.py` comment, and the
  `has_sparse_rows` docstring). They explain why the fields are gone. No code
  reads them.
- **The "sparse rows" printouts were removed** entirely rather than kept for old
  baselines. With new artifacts they always read 0, and ADR-017's A4 is history.

## RAGAS delta

Not measured: `make eval` is a stub. This change is behaviour-neutral by the
check above.

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | pending | pending | — |
| Context Precision | pending | pending | — |
| Answer Relevance | pending | pending | — |
| Context Recall | pending | pending | — |
| Fallback rate | pending | pending | — |

## Known gaps at merge time

- `settings.hybrid_top_k` keeps its name (README Known Gaps).
- The flagged older items still stand: README "golden set holds 5 of 50", KB
  reranking claims, 3 skipped integration tests without `/tmp/dpr-corpus-*`.

## Verification

- [x] `make lint` clean
- [x] `make test`: 232 passed, 3 skipped
- [ ] `make eval`: not possible, stub
- [x] Neutrality: 38/44/46, 50/50 identical, distances equal
