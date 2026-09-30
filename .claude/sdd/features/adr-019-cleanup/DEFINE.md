# DEFINE: Remove the fields and the setting that carry nothing

> The follow-up ADR-019 committed to. It changes the contract and config, and
> nothing that ranks.

## Metadata

| Field | Value |
|-------|-------|
| Feature | adr-019-cleanup |
| Date | 2026-09-30 |
| Author | christiandrocha (decisions), Claude (draft) |
| Status | Ready for Design |
| Clarity Score | 14/15 |
| ADR | No new ADR. The decision is ADR-019's ("`settings.fallback_threshold` is removed in the ADR-019 follow-up"; "`rrf_score` … leaves with the next ADR's contract change"). Recorded as ADR-019 Amendment 1 |
| Brainstorm | None, by the author's choice (2026-09-30). There were no options to explore, because the decision already exists |

## Problem statement

Since ADR-018 and ADR-019, four things in the code carry no information:

- `RetrievedChunk.rrf_score` is `1/(60 + dense_rank)`, the rank written as a
  float.
- `RetrievedChunk.sparse_score` is always 0.0, and `sparse_rank` is always None.
- `RRF_K` exists only to compute `rrf_score`.
- `settings.fallback_threshold` (0.35) is read by nothing, and ADR-019 measured
  that no threshold on similarity separates in-scope from out-of-scope questions.

A reader of the contract, the config or a recall artifact sees fields that look
meaningful and are not. The last one is also a trap: it invites code to start
gating on it.

## Users

| User | Role | Pain point |
|------|------|-----------|
| The author, and any coding agent | Reads `contracts.py` and `config.py` as the source of truth (ADR-010) | Three fields and a setting describe mechanisms that were removed or disproved |
| The curator | Reads recall artifacts | Every ranked chunk carries `rrf_score` and `sparse_rank` that never vary |

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | `RetrievedChunk` loses `rrf_score`, `sparse_score` and `sparse_rank` (author, 2026-09-30: all constant fields, one contract change). `RerankedChunk` still extends it |
| MUST | `RRF_K` is removed. The query returns no constant columns |
| MUST | `settings.fallback_threshold` and `FALLBACK_THRESHOLD` in `.env.example` are removed. `extra="ignore"` means a deployment that still sets the variable keeps starting |
| MUST | Retrieval does not move: `make retrieval-recall baseline=<ADR-019 artifact>` gives 38/44/46 and all 50 rankings identical |
| MUST | The recall script still reads old artifacts as baselines, which carry `sparse_rank` and `rrf_score` |
| MUST | The KB mirrors (`pydantic/models.md`, `pydantic/config-pattern.md`, `rag/dense-retrieval.md`) change in the same pass |
| SHOULD | The recall artifact stops writing `rrf_score`, `sparse_rank`, `top_rrf_score(s)`, `has_sparse_rows` and `questions_with_sparse_rows` |

## Success criteria (measurable)

- [ ] `grep -rnE "rrf_score|sparse_score|sparse_rank|RRF_K|rrf_k|fallback_threshold|FALLBACK_THRESHOLD"`
      over `data_platform_rag/`, `scripts/`, `sql/` and `.env.example` finds only
      the recall script's reading of old baselines
- [ ] Recall against `retrieval-recall-20260930-185210.json`: k=3/10/20 = 38/44/46,
      0 top-3 paths lost, rankings identical 50/50
- [ ] `make lint` and `make test` pass

## Acceptance tests

- [ ] Constructing `RetrievedChunk` with `rrf_score=` is rejected (unit test). The
      contract's fields are exactly what retrieval produces
- [ ] `Settings()` starts with `FALLBACK_THRESHOLD=0.35` in the environment and
      has no `fallback_threshold` attribute (unit test)
- [ ] The dense query selects no `rrf_score`, `sparse_score` or `sparse_rank`
      column (unit test)
- [ ] The recall script computes identical rankings against an old-format
      baseline that has `sparse_rank` keys (unit test)
- [ ] The recall neutrality run above

## Non-goals

- A `similarity` field. ADR-019 found no gate that would read it, and `make ask`
  computes it where it prints it.
- `settings.hybrid_top_k`'s name (README Known Gaps).
- `query_log` columns. The schema is untouched.
- Historical ADRs, feature records and old artifacts. They keep the names they used.

## Open questions

None. The author settled scope and process on 2026-09-30.

## Clarity Score self-check

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | Four named items, each proven constant or unread by an accepted ADR |
| Users are named and their pain is real | 4 | Readers of the contract. Nobody has been misled yet, and this removes the chance |
| Success criteria include numbers | 5 | 38/44/46, 50/50 identical, and a grep with a named allowed residue |
| **Total** | **14/15** | |
