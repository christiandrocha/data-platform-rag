# ADR-017 — Document-frequency-filtered OR for the sparse side of hybrid retrieval

**Status**: Rejected — 2026-09-30, by the measurement this ADR fixed in advance. See [Outcome](#outcome)
**Date**: 2026-09-30

> Planned on 2026-09-30 with the decision rule below, and rejected the same day by
> BUILD's measurement. The Context, Decision and Consequences sections are kept
> exactly as written before the measurement. They are the prediction the outcome
> is judged against, as in ADR-015.

## Context

ADR-003 specifies hybrid retrieval: dense (pgvector cosine) and sparse
(PostgreSQL `tsvector`) fused by reciprocal rank fusion. For question-shaped input
the sparse half is empty. `plainto_tsquery` ANDs every term, so a question
demands one chunk containing all of them (ADR-003 Amendment 1 §B). On 2026-09-29
the sparse side returned rows for **7 of 50** golden-set questions
(`.claude/dev/reports/retrieval-recall-20260929-190639.json`). In practice
retrieval is dense-only, and the README's "hybrid" claim does not hold for the
input the product exists to answer.

ADR-015 OR-joined every lexeme and was rejected by its own measurement. Every
lexeme voted equally. Generic lexemes (`snowflak` in 31% of chunks, `stream` in
24%) spread the sparse vote across many documents. On q001 that produced an exact
RRF tie between the right ADR and a wrong one, and the id tiebreak picked the
wrong one. ADR-015's Outcome named its Alternative 2 as the next candidate: drop
generic lexemes by document frequency, then OR. This ADR is that candidate.

The before-reading, fixed and not re-measured (snapshot
`sdd-kafka-databricks@f1295df9`, `sdd-kafka-snowflake-2@82a2e269`, embedding
`BAAI/bge-small-en-v1.5`, 304 chunks from 47 files, golden set q001–q050):

| | k=3 | k=10 | k=20 |
|---|---|---|---|
| all (57 declared paths) | **38** | 44 | 46 |
| decision (22) | 20 | 22 | 22 |
| architecture (24) | 15 | 18 | 20 |
| comparison (11) | 3 | 4 | 4 |

k=3 decides, because it is what reaches the LLM: ADR-005 rejected the reranker,
and `settings.rerank_top_k` = 3 is the context cut.

## Decision

**The sparse side OR-joins the lexemes `plainto_tsquery` produces, minus every
lexeme that occurs in more chunks than the largest single source file
contains.**

The cutoff is a rule derived from the corpus, not a constant. A sparse vote is
useful when it points toward one document. A lexeme in more chunks than any single
document has cannot be concentrated in one document, so it can only spread votes.
Today the rule evaluates to **68** (`sdd-kafka-snowflake-2/README.md`, 68 of 304
chunks, 22.4%), and 26 of 2,740 lexemes are above it. The author chose the
largest file of any kind over the largest ADR (30) on 2026-09-30, before any
measurement, so that the rule does not treat one file type differently.

Everything happens in SQL, in the same statement as the fusion:

```sql
WITH query_terms AS (
  SELECT DISTINCT term
  FROM regexp_split_to_table(
         plainto_tsquery('english', %(query_text)s)::text, ' & ') AS term
  WHERE term <> ''
),
df_cutoff AS (
  SELECT max(file_chunks) AS max_file_chunks
  FROM (SELECT count(*) AS file_chunks
        FROM chunks GROUP BY source_project, source_path) AS per_file
),
term_df AS (
  SELECT t.term,
         (SELECT count(*) FROM chunks WHERE content_tsv @@ t.term::tsquery) AS df
  FROM query_terms t
),
sparse_query AS (
  SELECT string_agg(term, ' | ' ORDER BY term)::tsquery AS tsq
  FROM term_df, df_cutoff
  WHERE df <= max_file_chunks
),
candidates AS (
  ... COALESCE(ts_rank_cd(content_tsv, (SELECT tsq FROM sparse_query)), 0) AS sparse_score
```

- **Sanitising stays with `plainto_tsquery`.** Each `term` is a fragment of
  Postgres' own tsquery output, already quoted by Postgres, and cast straight back
  to `tsquery`. No user text and no Python-built string reaches tsquery syntax.
  The split on `' & '` is the separator `plainto_tsquery` writes. Its lexemes
  contain no spaces, so the separator cannot occur inside one.
- **Document frequency and cutoff come from `chunks`, in the same statement.**
  `chunks` holds exactly one live snapshot per project (ADR-013), so both numbers
  always describe the snapshot being searched. No table stores them, so none can
  go stale.
- **Both are computed over the whole index, not over the collection filter.** The
  rule is a property of the corpus. Today every query searches both collections,
  because no intent classifier exists.
- **When every lexeme is above the cutoff, the sparse side returns no rows.**
  `string_agg` over nothing is `NULL`, `ts_rank_cd(…, NULL)` is `NULL`, the
  `COALESCE` makes it 0, and `WHERE sparse_score > 0` empties the list. That is
  today's behaviour for a zero match, not an error and not the unfiltered OR.

**Status is Planned, not Accepted.** BUILD runs `make retrieval-recall` on the
before-reading's snapshot, model and golden set, and this rule alone decides the
Status. It is copied byte for byte from the feature's DEFINE, and BUILD checks
that before measuring:

**Accepted** only if all four hold:

- [ ] **A1.** Recall at k=3 is **≥ 40/57** (the before-reading plus at least 2
      paths). A single path is excluded as a margin because ADR-015 showed one
      exact tie deciding a rank. A gain that rests on one path could be a tie
      breaking by `id`.
- [ ] **A2.** **None of the 38 paths in today's top 3 leaves the top 3.** This is
      the named-case guard, generalised from ADR-015's q001 to every path the LLM
      sees today.
- [ ] **A3.** Recall at k=10 is **≥ 44/57** and at k=20 **≥ 46/57**, so nothing
      regresses further down.
- [ ] **A4.** The sparse side returns rows for **more than 7 of 50** questions.
      Without this, any change in recall cannot be the filter's doing.

**Rejected** if any of A1–A4 fails. That covers every other reading:

| reading | outcome |
|---|---|
| k=3 up by 2+ paths, no top-3 path lost, k=10/k=20 not worse | **Accepted** |
| k=3 up by exactly 1 path | Rejected (A1). Recorded as "directional, below margin" |
| k=3 flat | Rejected (A1): the sparse vote changed nothing the LLM sees |
| k=3 down, or any top-3 path lost | Rejected (A1/A2) |
| k=3 up by 2+ paths, but k=10 or k=20 worse | Rejected (A3) |
| **nothing moves at any k** | Rejected (A1). A sparse side that changes nothing is decoration, and the rejection branch removes it |

On rejection the query reverts to `plainto_tsquery`, ADR-017 is marked Rejected in
place with the numbers, and the author's pre-agreed next step is the honest
dense-only ADR.

## Consequences

**The sparse side votes for most questions, if the rule holds.** The number of
questions with sparse rows is A4. It is not predicted here.

**Pre-registered predictions, not gating** (copied from DEFINE and judged in the
Outcome):

- P1. Comparison recall at k=3 stays **≤ 4/11**. The comparison misses look
  structural, not lexical.
- P2. Every out-of-scope top score **rises** above 0.01639. The rise is **smaller
  than ADR-015's +81%** on q005.
- P3. Any k=3 gain comes from `decision` or `architecture`, not `comparison`.

**The out-of-scope questions look more confident, not less.** As in ADR-015, a
populated sparse side adds a second RRF contribution to every question, including
the ones that should fall back. The fallback is the LLM's job under the system
prompt's rule 3, measured only by `make eval`, so this is reported and does not
gate.

**RRF still gives the two sides an equal ballot.** No weight is introduced. The
filter changes which lexemes may vote, not how loud the sparse vote is. A weight
would be a second knob with nothing to tune it against while RAGAS cannot run.

**The cutoff moves with the corpus.** If the Snowflake README grows, the cutoff
grows with it and fewer lexemes are dropped. That follows from the rule the
author chose, and an integration test asserts it.

**Cost per query.** The query does one GIN-backed count per distinct query
lexeme, plus one `GROUP BY` over 304 rows. Measured on 2026-09-30 on a
non-golden 10-lexeme text: 0.66 ms execution. `sql/99_verify.sql` gets the new
plan as its baseline in BUILD.

**No schema change, no reindex, no new setting, no new dependency.** A revert is a
revert of `HYBRID_QUERY`.

**Test fixtures must describe files, not only chunks.** The cutoff counts chunks
per file. A fixture that puts every chunk in its own file has a cutoff of 1, so a
lexeme in two chunks is dropped. `test_a_sparse_tie_breaks_by_id_not_by_heap_order`
seeds two identical chunks in two files. Under this rule they have no sparse rows,
and the test would fail for a reason unrelated to tiebreaks. Its fixture moves
both chunks into one file (cutoff 2), which keeps what the test asserts.

## Alternatives considered

**1. Unfiltered OR (ADR-015).** Rejected on 2026-09-21 by measurement. Not re-run.

**2. Largest ADR (30 chunks) as the cutoff.** It drops more lexemes and does not
depend on the README's size, but it treats one file type as special. The author
chose the largest file of any kind on 2026-09-30, before measuring.

**3. A cutoff swept against the golden set.** Rejected before any number existed.
The golden set also grades the answers, through RAGAS, so tuning retrieval on it
overfits both. One value, fixed by a structural rule, and no second value if it
fails.

**4. Document frequencies in a table refreshed at index time.** Saves the per-query
counts, but adds a table, a writer step and a way to disagree with `chunks`.
The per-query cost is under a millisecond at 304 chunks. Revisit if the corpus
grows by an order of magnitude.

**5. `ts_stat` per query.** Computes every lexeme of the corpus (2,740) to read
the ones in the query (about 10). A count per query lexeme on the GIN index does
the same with less work, and gives identical numbers for plain lexemes.

**6. A weight on the sparse RRF term.** A second knob with nothing to tune it
against. Out of scope.

**7. Honest dense-only.** The author's pre-agreed next step if this ADR is
rejected, as a new ADR.

## Outcome

**Rejected (A1 and A2).** Measured on 2026-09-30 on the before-reading's snapshot
(`sdd-kafka-databricks@f1295df9`, `sdd-kafka-snowflake-2@82a2e269`,
`BAAI/bge-small-en-v1.5`, golden set q001–q050). Before:
`.claude/dev/reports/retrieval-recall-20260929-190639.json`. After:
`retrieval-recall-20260930-173857.json` and `-173912.json`: two runs, identical
rankings and scores. Code measured: commit
`feat(retrieval): DF-filtered OR on the sparse side (ADR-017, pre-measurement)`.
The rule was checked byte-identical to DEFINE's immediately before the first run.

| | before | after | rule | |
|---|---|---|---|---|
| A1: recall at k=3 | 38/57 | **39/57** (+1) | ≥ 40/57 | **fails** |
| A2: today's top-3 paths that left the top 3 | — | **1** (q007) | 0 | **fails** |
| A3: recall at k=10 / k=20 | 44 / 46 | 46 / 49 | ≥ 44 / ≥ 46 | holds |
| A4: questions with sparse rows | 7/50 | 49/50 | > 7/50 | holds |

The reading falls in the table's row "k=3 up by exactly 1 path", recorded as
**directional, below margin**, and A2 fails independently. The rule is the
decision. What follows describes the reading and does not reopen it.

**By intent at k=3:** decision 20 → **19**, architecture 15 → **17**, comparison
3 → 3. At k=20, comparison 4 → 6 and architecture 20 → 21.

**Declared paths that changed rank** (22 of 57). Rank at k ≤ 20, `—` for absent:

| moved into or up within the top 3 | left or lost ground within the top 3 |
|---|---|
| q031 README (databricks) — → **1** | q007 `0025_bronze_is_append_only` **1 → 5** |
| q032 README (second path) 9 → **3** | q003, q004, q008, q011, q023, q032, q036, q043: 1 → 2 |
| q016 `003_parametrized_notebooks` 2 → 1 | |
| q042 README 3 → 1 | |

Below the top 3: q029 17 → 6 and 12 → 15, q044 — → 5, q045 — → 20 and 2 → 3,
q046 5 → 12, q002 7 → 8, q003 5 → 8, q015 6 → 7.

**Why q007 fell.** The question is *"Why is the Bronze layer strictly
insert-only…"*. The filter dropped `bronz` (162 chunks) and `layer` (86). Those
are the question's subject, but the corpus uses them everywhere. It kept `row`
at exactly 68, the cutoff, because equality keeps. The declared ADR's four chunks
held dense ranks 1–4 and got no sparse rank in the top 20. Three other chunks
each had a contribution from both sides: `resolve_cdc.sql` (dense 13, sparse 2)
and two sections of the Databricks `005_gold_dimension_join_integrity` (dense
12 and 10, sparse 11 and 18). Two mid-list votes outweigh one first-place vote.
Any chunk that ranks moderately on both sides beats a chunk that ranks first on
one side only. This is ADR-015's lesson in a different case. **The filter changed
which lexemes vote, not the equal ballot**, which the Consequences said it would
not touch.

**The predictions, checked:**

- *P1, comparison recall at k=3 stays ≤ 4/11*: **right**, 3/11.
- *P2, every out-of-scope top score rises, by less than ADR-015's +81%*:
  **right in direction, wrong in size.** q005 0.01639 → 0.03252 (+98%), q047
  +95%, q048 +84%, q049 +84%, q050 +81%. The filter did not make out-of-scope
  questions look less confident than the unfiltered OR did. q005 rose more.
- *P3, any k=3 gain comes from `decision` or `architecture`*: **right.** The net
  +1 is architecture +2 and decision −1.

**Cost, measured:** `EXPLAIN ANALYZE` of the filtered query on q002 (the
`sql/99_verify.sql` question, run after the recall measurement): `sparse_query`
is evaluated once (InitPlan), the per-lexeme counts use
`Bitmap Index Scan on idx_chunks_content_tsv_gin` (11 loops), and execution took
5.17 ms. The plan is in the feature's BUILD_REPORT.

**What was reverted.** `HYBRID_QUERY` is back to `plainto_tsquery`. `sparse_terms`,
the `SparseTerm`/`SparseTerms` contracts and `make ask`'s filter line are removed,
since they described a filter that is not in use. After the revert,
`make retrieval-recall` against the before-reading prints 38 / 0 lost / 44 / 46 /
7, identical to the before-reading (`retrieval-recall-20260930-174033.json`).

**What survives the rejection:**

- **`make retrieval-recall baseline=FILE`.** It prints the four A1–A4 inputs and
  refuses to compare artifacts from a different snapshot, embedding model or
  golden set. The next retrieval ADR reads its rule off this.
- **`questions with sparse rows`** in every recall artifact.
- **The sanitising tests** gained quote, backslash, `:*`, `(` and `!` inputs.
  **`seed(..., file_of=…)`** lets a fixture say which chunks share a file, and
  the tiebreak test now uses it.

**What this reopens.** Both lexical repairs of the sparse side have now been
measured and rejected. The unfiltered OR (ADR-015) and the filtered OR (this ADR)
both failed on an equal RRF ballot. The author's pre-agreed next step is the
honest dense-only ADR (Alternative 7), as a new ADR. A sparse *weight* (Alternative
6) remains out of scope for the reason given: nothing can tune it while RAGAS
cannot run.
