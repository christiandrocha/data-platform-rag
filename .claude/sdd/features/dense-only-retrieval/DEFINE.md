# DEFINE: Honest dense-only retrieval

> Rank by cosine distance alone, say so everywhere, and let a rule written before
> the measurement confirm it costs nothing the LLM sees.

## Metadata

| Field | Value |
|-------|-------|
| Feature | dense-only-retrieval |
| Date | 2026-09-30 |
| Author | christiandrocha (decisions), Claude (draft) |
| Status | Ready for Design (Q1, Q2 settled by the author on 2026-09-30, before any measurement) |
| Clarity Score | 14/15 |
| ADR | ADR-018 (written in DESIGN, Status Planned until BUILD's measurement) |
| Brainstorm | [BRAINSTORM.md](BRAINSTORM.md), Option 1, confirmed by the author on 2026-09-30. It is ADR-017's pre-agreed rejection branch |

## Problem statement

The project says "hybrid retrieval" in its README, AGENTS.md, ADR-003 and KB. For
question-shaped input that is false. The sparse side returned rows for **7 of 50**
golden questions, because `plainto_tsquery` ANDs every term. Two repairs
(ADR-015, ADR-017) were measured and rejected on the same mechanism: an equal
RRF ballot. What remains is a sparse vote that switches on only when one chunk
happens to contain every query term. That is a ranking policy chosen by the
input's wording, not by a decision. This feature removes it and makes every
public claim true.

## Users

| User | Role | Pain point |
|------|------|-----------|
| The author | Owns the public claims | README "Why it exists" names hybrid retrieval as part of the point of the project, and README Known Gaps says it does not hold. Both cannot stay |
| A technical interviewer | Reads the repo, then the code | Finds "hybrid" in the README and a sparse side that is empty for almost every question. That is the kind of gap the project exists to show it does not have |
| The curator (the author, running `make retrieval-recall`) | Judges retrieval changes | Today a recall number averages two retrievers: dense-only for 43 questions, fused for 7. After this, one retriever for every question |

## The before-reading (fixed, not re-measured)

The same reading ADR-017 used:
`.claude/dev/reports/retrieval-recall-20260929-190639.json`, snapshot
`sdd-kafka-databricks@f1295df9`, `sdd-kafka-snowflake-2@82a2e269`, embedding
`BAAI/bge-small-en-v1.5`, 304 chunks, golden set q001–q050. On 2026-09-30,
after ADR-017's revert, the same state measured identically
(`retrieval-recall-20260930-174033.json`: 38 / 44 / 46, 7 with sparse rows).

| | k=3 | k=10 | k=20 |
|---|---|---|---|
| all (57 declared paths) | **38** | 44 | 46 |

**What is known without measuring:** for the 43 questions with no sparse rows, the
fused ranking already is the dense ranking, so dense-only cannot change them.
**What is deliberately not looked at:** which declared paths of the 7
sparse-active questions carry a sparse rank today. The JSON holds it. Reading it
before the rule is fixed would let the result choose the rule.

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | Retrieval ranks by cosine distance alone, ties broken by `id`. No `tsquery` is built and no `ts_rank_cd` is computed at query time |
| MUST | `content_tsv`, `idx_chunks_content_tsv_gin` and `pg_trgm` stay in the schema, untouched. Their SQL comments say they are unused by retrieval and name ADR-018. No `DROP` anywhere (ADR-013 §5) |
| MUST | `RetrievedChunk` stays valid for every existing consumer (`ask.py`, `retrieval_recall.py`, the future generation step). What its score fields mean under one list is DESIGN's decision (Q3) |
| MUST | ADR-018 is written in DESIGN, Status Planned, with the rule below copied into it byte for byte **before** BUILD measures |
| MUST | Every hybrid claim is made true in the same change: README (Why it exists, mermaid diagram, architecture tree, stack table, Known Gaps, next steps), AGENTS.md (stack, repo map comment, pgvector discipline), ADR-003 (superseded in part, in place), the KB, and `sql/99_verify.sql` section 5 |
| SHOULD | `make retrieval-recall baseline=…` reports A1–A4 unchanged in meaning. A4 becomes "questions whose ranking is identical to the before-reading", counted over the 43 sparse-empty questions |
| SHOULD | The out-of-scope top scores (q005, q047–q050) are reported before and after, with no gate |
| COULD | The module name `hybrid_search.py` is revisited (DESIGN, Q4) |

## Success criteria (measurable): the decision rule

Applied once, to the first BUILD reading. Runs are deterministic (ADR-015 and
ADR-017 each measured two identical runs), so one reading is the reading.

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

**Predictions, pre-registered and not gating** (judged in ADR-018's Outcome):

- P1. Of the 7 sparse-active questions, **at most 2** see any declared path change
  rank.
- P2. Every out-of-scope top score stays **exactly 0.01639** (`1/61`). Under one
  list, rank 1 always scores the same, which is the reason ADR-006's threshold
  needs a different score (BRAINSTORM Option 4, deferred).
- P3. No declared path of a **comparison** question changes rank.

## Acceptance tests

- [ ] `make retrieval-recall baseline=<before-reading>` on the fixed snapshot prints
      A1–A3 and the A4 count of identical rankings, and the rule's outcome can be
      read off them by someone who has not read this file
- [ ] The query contains no `tsquery`, `ts_rank_cd` or `content_tsv` reference
      (unit test on the SQL constant)
- [ ] A chunk that matches the query text exactly but is far in vector space ranks
      by its distance alone (integration test: the fixture's chunk B, today
      rank 1 by the sparse vote, falls to its dense rank 3)
- [ ] Ties on distance break by `id`, independent of heap order (the existing
      tiebreak test, rewritten for the dense side)
- [ ] `make bootstrap` against the populated local database succeeds and changes
      nothing (no `DROP`, schema untouched)
- [ ] `grep -rniE "hybrid|sparse|tsvector"` over README.md, AGENTS.md and the KB
      returns only lines that describe the history or the unused schema, and each
      names ADR-018. The list of remaining hits goes in the BUILD_REPORT
- [ ] `make lint` and `make test` pass
- [ ] ADR-018's decision rule is byte-identical to this file's, checked right
      before the measurement

## Non-goals

Explicitly out of scope:

- **The score's meaning for the fallback** (BRAINSTORM Option 4). A cosine
  similarity score and a calibrated ADR-006 threshold are the fallback ADR's work.
  This feature only reports the out-of-scope scores.
- **Dropping `content_tsv` or its GIN index** (BRAINSTORM Option 2).
- **Any new sparse attempt**, weighted or not.
- **The per-project share for comparison questions** and the intent classifier.
  They retake their before-reading on the state this feature leaves.
- **Re-tuning HNSW or the embedding model** (ADR-004).
- **Answer quality.** RAGAS cannot run; source recall stands in (ADR-014).

## Open questions

- [x] **Q1 (author).** On rejection, is the fallback BRAINSTORM Option 3 (keep
      today's query, rewrite the claims honestly)? The alternative is to accept
      dense-only anyway with the lost path named, which would mean the rule did not
      decide. The draft proposes Option 3.
      **Settled 2026-09-30: Option 3.**
- [x] **Q2 (author).** Is zero tolerance right for A2? One lost top-3 path rejects
      dense-only, even if another path enters the top 3. The case for zero: the
      whole gain is non-recall, so it should not be bought with a path the LLM sees
      today. The cost: a trade that is neutral in count rejects the feature.
      **Settled 2026-09-30: zero. No top-3 path may leave.**
- [ ] **Q3 (DESIGN).** Under one list, what `RetrievedChunk.rrf_score` holds.
      Keep `1/(60 + dense_rank)`, so reports and ties read the same, or rename the
      field. Whatever it is, the contract stays valid for every consumer.
- [ ] **Q4 (DESIGN).** Whether `hybrid_search.py` and `HYBRID_QUERY` are renamed.
      The names become false. Renaming touches imports, tests and the ADR-015 and
      ADR-017 references.

## Clarity Score self-check

Rate each 1-5. Total must be ≥ 12/15 to proceed to Design.

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | A measured false claim (7/50), a fixed before-reading, and a rule that maps every reading to an outcome, including "nothing moved" |
| Users are named and their pain is real | 4 | The author's pain (two README sections that contradict each other) is concrete. The interviewer's is inferred, since no one has read the repo in that role yet |
| Success criteria include numbers | 5 | A1–A4 are numeric and fixed. The author confirmed the rejection fallback (Q1, Option 3) and A2's zero tolerance (Q2) on 2026-09-30, before any measurement |
| **Total** | **14/15** | Proceeds to DESIGN. Q3 and Q4 belong to DESIGN |
