# ADR-018 — Dense-only retrieval

**Status**: Accepted — 2026-09-30, by the measurement this ADR fixed in advance. See [Outcome](#outcome)
**Date**: 2026-09-30
**Supersedes**: ADR-003

> Planned on 2026-09-30 with the decision rule below, and accepted the same day by
> BUILD's measurement. The Context, Decision and Consequences sections are kept
> exactly as written before the measurement. They are the prediction the outcome
> is judged against, as in ADR-015 and ADR-017. They name the module as it was
> then (`hybrid_search.py`). The rename they announce happened after the Outcome.

## Context

ADR-003 specified hybrid retrieval: dense (pgvector cosine) and sparse (PostgreSQL
`tsvector`) fused by reciprocal rank fusion. The sparse side uses
`plainto_tsquery`, which ANDs every term. For question-shaped input it is
empty. On 2026-09-29 it returned rows for **7 of 50** golden questions
(`.claude/dev/reports/retrieval-recall-20260929-190639.json`).

Two repairs were measured and rejected:

- **ADR-015** (2026-09-21) OR-joined every lexeme. Recall did not move, and q001
  lost rank 1 to an exact RRF tie.
- **ADR-017** (2026-09-30) OR-joined only the lexemes at or below a
  document-frequency cutoff. Sparse rows rose to 49/50, but k=3 moved +1 against
  a required +2, and q007's declared path fell from rank 1 to 5.

Both failed on the same mechanism. RRF gives the two lists an equal ballot, so a
chunk ranked mid-list on both sides outscores the right chunk at dense rank 1. A
weight could change that, but nothing can tune one while RAGAS cannot run.

What remains is a sparse vote that switches on only when one chunk happens to
contain every query term. That is a ranking policy chosen by the wording of the
input, not by a decision. ADR-015 rejected that shape as its Alternative 3: "two
retrievers behind one entry point". Meanwhile the README, AGENTS.md and the KB
say "hybrid".

The author pre-agreed, in ADR-017's brainstorm, that its rejection opens this ADR.
The option was confirmed on 2026-09-30 (feature `dense-only-retrieval`,
BRAINSTORM Option 1).

## Decision

**Retrieval ranks by cosine distance alone.** The sparse CTE, the `tsquery` and the
fusion leave the query. What remains, exactly, is:

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
  c.id, c.content, c.collection,
  c.source_project, c.source_type, c.source_path, c.source_anchor,
  c.adr_id, c.topic, c.status, c.keywords, c.chunk_index, c.token_count,
  c.dense_dist, 0.0 AS sparse_score,
  d.dense_rank, NULL::bigint AS sparse_rank,
  1.0 / (%(rrf_k)s + d.dense_rank) AS rrf_score
FROM candidates c
JOIN dense_ranked d USING (id)
ORDER BY d.dense_rank ASC
```

- **The search stays exact.** Every candidate's distance is computed, then
  ordered with an `id` tiebreak. That is a sequential scan at 304 rows, as it is
  today. An HNSW index scan would make the result approximate and could change a
  ranking with no change to the corpus. That would break the identity check
  below (A4).
- **`RetrievedChunk` keeps its shape.** `rrf_score` is `1/(60 + dense_rank)`,
  which is exactly the score a dense-only chunk carries under today's fusion. The
  43 sparse-empty questions therefore keep identical scores as well as
  identical rankings, and every report stays comparable. `sparse_score` is 0.0
  and `sparse_rank` is None, which the contract already reads as "the sparse side
  did not rank it". The field's meaning for the fallback is left to the fallback
  ADR (see Consequences).
- **The user's text no longer reaches SQL.** `search()` drops its `query_text`
  parameter. `retrieve()` still takes the question and embeds it.
- **The schema is untouched.** `content_tsv`, `idx_chunks_content_tsv_gin` and
  `pg_trgm` stay. Removing them needs a `DROP`, which has no legal place outside
  `sql/90_reset.sql` (ADR-013 §5). Keeping them costs little at 304 rows and makes
  any future sparse attempt a query change, not a migration.

**Status is Planned, not Accepted.** BUILD runs `make retrieval-recall` on the
before-reading's snapshot, model and golden set, and this rule alone decides the
Status. It is copied byte for byte from the feature's DEFINE, and BUILD checks
that before measuring:

**Accepted** only if all four hold:

- [ ] **A1.** Recall at k=3 is **≥ 38/57**. The gain sought is honesty and a
      simpler hot path, not recall, so the test is non-inferiority: no margin
      above the before-reading is required, and none below it is tolerated.
- [ ] **A2.** **None of the 38 paths in today's top 3 leaves the top 3.** A path
      the LLM sees today is the cost this rule exists to catch.
- [ ] **A3.** Recall at k=10 is **≥ 44/57** and at k=20 **≥ 46/57**.
- [ ] **A4.** The **43 questions without sparse rows** in the before-reading have
      **identical rankings** (paths, anchors and order, top 20). This is a
      correctness check on the change. If it fails, the query changed more than
      the sparse side, and the result is Rejected until that is explained.

**Rejected** if any of A1–A4 fails. That covers every other reading:

| reading | outcome |
|---|---|
| k=3 ≥ 38, no top-3 path lost, k=10/k=20 not worse, the 43 identical | **Accepted** |
| nothing moves at any k | **Accepted**. The sparse vote changed nothing the LLM sees, and removing it is the point |
| k=3 up, nothing lost | **Accepted**. The gain is recorded, not claimed as the reason |
| any top-3 path lost, even with k=3 ≥ 38 | Rejected (A2) |
| k=3 below 38 | Rejected (A1) |
| k=10 or k=20 worse | Rejected (A3) |
| any of the 43 changes | Rejected (A4) |

On rejection the query reverts to today's `plainto_tsquery` fusion, ADR-018 is
marked Rejected in place with the numbers, and **the fallback is BRAINSTORM
Option 3**: keep today's query and rewrite every claim to say what it does,
"dense retrieval, plus an exact-match sparse vote that fires only when one chunk
contains every query term".

## Consequences

**ADR-003 is superseded.** Its decision was to fuse two lists, and one list
remains. What survives of it is compatibility only: `RRF_K` = 60 still computes
`rrf_score`, so artifacts compare across the change. ADR-003 is marked Superseded
in place, and its text is not rewritten.

**Pre-registered predictions, not gating** (copied from DEFINE and judged in the
Outcome):

- P1. Of the 7 sparse-active questions, **at most 2** see any declared path change
  rank.
- P2. Every out-of-scope top score stays **exactly 0.01639** (`1/61`). Under one
  list, rank 1 always scores the same, which is the reason ADR-006's threshold
  needs a different score (BRAINSTORM Option 4, deferred).
- P3. No declared path of a **comparison** question changes rank.

**The fallback still has no usable score, and now it is plain why.** Under one
list the top `rrf_score` is `1/61` for every question, in scope or not. ADR-006
wrote its threshold in cosine ("baseline: 0.35 cosine"). A score of
`1 - dense_distance` would give it something to act on. That is the fallback
ADR's decision, together with the threshold's value. It is not taken here, so that
this measurement reads one change.

**Keyword input loses exact matching.** `make ask q="why Snowpipe Streaming?"`
gets real sparse scores today (ADR-015 Context). After this change it does not.
Whether the sparse vote helped that input was never measured, and no UI exists to
say which input shape real users type.

**The names become false, and are fixed only on acceptance.** `hybrid_search.py`,
`HYBRID_QUERY` and `build_hybrid_query` describe a fusion that no longer happens.
If this ADR is Accepted, a separate behaviour-neutral commit renames them to
`dense_search.py`, `DENSE_QUERY` and `build_dense_query`. A recall run
after the rename must reproduce the measured artifact exactly.
`settings.hybrid_top_k` / `HYBRID_TOP_K` keeps its name. It is an environment
variable in every deployment, and renaming it is an interface change this ADR does
not need. It is recorded as a naming gap. Superseded and rejected ADRs keep the
old names, because they describe the code as it was.

**No schema change, no reindex, no new dependency, no new setting.**

## Alternatives considered

**1. Keep today's query and make the claims honest** (BRAINSTORM Option 3). Zero
risk to recall. It keeps a policy chosen by the input's wording, and it keeps
`1/61` as the only score. **It is the pre-agreed fallback if this ADR is
rejected.**

**2. Dense-only, and drop `content_tsv` and its index** (BRAINSTORM Option 2). No
legal place for the `DROP`, and it saves almost nothing at 304 rows.

**3. Dense-only, and the score becomes cosine similarity** (BRAINSTORM Option 4).
The right next step for the fallback, but it widens this change into the contract
and ADR-006. Deferred so that this measurement reads one change.

**4. A weighted sparse vote.** Nothing can tune the weight while RAGAS cannot run.
It was out of scope in ADR-015 and ADR-017 for the same reason.

**5. A third lexical repair** (another cutoff, BM25 via `pg_search`, trigrams).
Both measured failures shared the equal-ballot mechanism, and a different lexeme
set does not change the ballot.

**6. HNSW index scan for the dense side.** Approximate. At 304 rows the exact scan
is fast and deterministic. ADR-004 owns the index's tuning and when it becomes
worth using.

## Outcome

**Accepted.** Measured on 2026-09-30 on the before-reading's snapshot
(`sdd-kafka-databricks@f1295df9`, `sdd-kafka-snowflake-2@82a2e269`,
`BAAI/bge-small-en-v1.5`, golden set q001–q050). Before:
`.claude/dev/reports/retrieval-recall-20260929-190639.json`. After:
`retrieval-recall-20260930-182007.json` and `-182023.json`: two runs, identical
rankings and scores. Code measured: commit
`feat(retrieval): dense-only query (ADR-018, pre-measurement)`. The rule was
checked byte-identical to DEFINE's immediately before the first run.

| | before | after | rule | |
|---|---|---|---|---|
| A1: recall at k=3 | 38/57 | 38/57 | ≥ 38/57 | holds |
| A2: today's top-3 paths that left the top 3 | — | 0 | 0 | holds |
| A3: recall at k=10 / k=20 | 44 / 46 | 44 / 46 | ≥ 44 / ≥ 46 | holds |
| A4: sparse-empty questions ranked identically | — | 43/43 | 43/43 | holds |

The reading falls in the table's row **"nothing moves at any k"**, which DEFINE
fixed as Accepted: the sparse vote changed nothing the LLM sees, and removing it
is the point. The 43 sparse-empty questions also kept identical `rrf_score`
values, as the Decision predicted from `1/(60 + dense_rank)`.

**The 7 sparse-active questions** (q003, q006, q027, q033, q034, q038, q039):

- 2 of them (q003, q039) have identical top-20 rankings. Their sparse rows did not
  change even the order.
- 4 of them (q006, q027, q034, q038) changed order somewhere in the top 20, but
  no declared path moved.
- 1 of them (q033) moved a declared path: `sdd-kafka-snowflake-2/README.md`,
  rank 1 → 2. It stays in the top 3.

**The predictions, checked:**

- *P1, at most 2 of the 7 see a declared path change rank*: **right**, 1 (q033).
- *P2, every out-of-scope top score stays exactly 0.01639*: **right**, all five
  (q005, q047–q050) at `1/61`. That is also every in-scope question's top score,
  which is why the fallback needs a different score.
- *P3, no declared path of a comparison question changes rank*: **right.** None of
  the 7 sparse-active questions is a comparison, so this held by construction.
  It was not a test of anything.

**Cost, measured:** `EXPLAIN ANALYZE` of `sql/99_verify.sql` §5: Seq Scan over
304 rows, one WindowAgg, no reference to `content_tsv`, 1.8 ms execution. §6
still proves the HNSW index usable. The plan is in the feature's BUILD_REPORT.

**What followed the acceptance**, in a separate commit that does not change
behaviour: the rename to `retrieval/dense_search.py`, `DENSE_QUERY` and
`build_dense_query`, proven neutral by a recall run whose `results` equal the
measured artifact's. The public claims in README, AGENTS.md and the KB were
rewritten to match. ADR-003 was marked Superseded in place.
