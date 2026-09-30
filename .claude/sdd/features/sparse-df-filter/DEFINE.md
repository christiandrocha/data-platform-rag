# DEFINE: A sparse side that votes only on distinctive terms

> OR-join only the query lexemes that no single source file could outnumber, and
> let a rule written before the measurement decide whether that stays.

## Metadata

| Field | Value |
|-------|-------|
| Feature | sparse-df-filter |
| Date | 2026-09-29 |
| Author | christiandrocha (decisions), Claude (draft) |
| Status | Approved for DESIGN (Q1, Q2 settled by the author on 2026-09-30, before any measurement) |
| Clarity Score | 14/15 |
| ADR | ADR-017 (to be written in DESIGN, Status Planned until BUILD's measurement) |
| Brainstorm | [BRAINSTORM.md](BRAINSTORM.md), Option 1; author kept hybrid and chose the sparse side first |

## Problem statement

For question-shaped input the sparse half of hybrid retrieval is empty: it
returned rows for **7 of 50** golden-set questions on 2026-09-29, because
`plainto_tsquery` ANDs every term (ADR-003 Amendment 1 §B). Retrieval is therefore
dense-only in practice, and the README's hybrid claim does not hold for the input
the product exists to answer. ADR-015's unfiltered OR was rejected because generic
lexemes voted as loudly as specific ones. This feature tests whether removing the
generic lexemes gives the sparse side a vote worth having.

## Users

| User | Role | Pain point |
|------|------|-----------|
| The author | Owns the project and its public claims | The README and ADR-003 say "hybrid", and for 43 of 50 questions that is not true |
| A technical interviewer | Reads the repo and asks the system questions | Identifier-heavy questions (`cluster_by`, `ADR-0029`, `Snowpipe`) are where a 384-dim embedding is weakest, and nothing else is voting |
| The curator (the author, running `make retrieval-recall`) | Judges retrieval changes | Needs a rule fixed in advance, so a result cannot be argued into a different conclusion afterwards |

## The before-reading (fixed, not re-measured)

`.claude/dev/reports/retrieval-recall-20260929-190639.json`. Snapshot
`sdd-kafka-databricks@f1295df9`, `sdd-kafka-snowflake-2@82a2e269`, embedding
`BAAI/bge-small-en-v1.5`, 304 chunks from 47 files. The golden set is q001–q050
as in PR #22.

| | k=3 | k=10 | k=20 |
|---|---|---|---|
| all (57 declared paths) | **38** | 44 | 46 |
| decision (22) | 20 | 22 | 22 |
| architecture (24) | 15 | 18 | 20 |
| comparison (11) | 3 | 4 | 4 |

**k=3 is the bucket that decides**, because it is what reaches the LLM. The
reranker was rejected (ADR-005), and `settings.rerank_top_k` = 3 is the context
cut. If the snapshot, the embedding model or the golden set changes before BUILD
measures, this reading is **retaken** on the new state, never quoted across states.

## The cutoff, fixed here

**A lexeme is dropped when it occurs in more chunks than the largest single
source file contains.**

- **Why this rule.** A sparse vote is useful when it points toward one document. A
  lexeme that occurs in more chunks than any single document has cannot be
  concentrated in one document, so it can only spread votes across several. The
  rule is derived from the structure of the corpus, **not from the golden
  questions or their results**.
- **Today it evaluates to 68.** That is `sdd-kafka-snowflake-2/README.md`, 68 of
  304 chunks (22.4%). 26 of 2,740 lexemes are above it. (Measured with `ts_stat`
  over `content_tsv` and a count per file. Neither query touches a question.)
- **It is a rule, not a constant.** It is recomputed from the indexed corpus, so
  it cannot rot when the corpus changes. Where and when it is computed is DESIGN's
  decision.
- **Independent agreement, noted rather than used:** ADR-015 guessed "around a
  fifth of the corpus" from one question's lexemes. The structural rule lands at
  22.4% without using any question.
- **No second value will be tried.** If this cutoff fails the rule below, the
  outcome is rejection, not a new cutoff (BRAINSTORM, "Discarded early").

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | The sparse side OR-joins the lexemes `plainto_tsquery` produces, minus every lexeme above the cutoff. `plainto_tsquery` keeps doing the parsing, stemming and sanitising: user text never reaches the tsquery as syntax |
| MUST | When every lexeme of a query is above the cutoff, the sparse side returns no rows (today's behaviour), not an error and not the unfiltered OR |
| MUST | ADR-017 is written in DESIGN, Status Planned, with the decision rule below copied into it verbatim **before** BUILD runs the measurement |
| MUST | BUILD measures with `make retrieval-recall` on the before-reading's snapshot, model and golden set, and the rule alone decides the Status |
| MUST | Whichever way it goes, ADR-003 and the README stop claiming more than is true. On acceptance they state what the sparse side now does. On rejection, the honest dense-only path opens as a new ADR (BRAINSTORM Option 2), which the author has pre-agreed to |
| SHOULD | The recall report records, per question, how many lexemes the filter dropped and kept, so a result can be traced to the filter rather than inferred |
| SHOULD | The out-of-scope top scores (q005, q047–q050) are reported before and after, with no gate (see Non-goals) |
| COULD | `make ask` prints the kept lexemes, so a curator can see the filter act on a keyword query |

## Success criteria (measurable): the decision rule

Applied once, to the first BUILD reading. Runs are deterministic (ADR-015 measured
two identical runs), so one reading is the reading.

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

**Predictions, pre-registered and not gating** (judged in ADR-017's Outcome, as
ADR-015 judged its own):

- P1. Comparison recall at k=3 stays **≤ 4/11**. The comparison misses look
  structural, not lexical (BRAINSTORM, "A different problem").
- P2. Every out-of-scope top score **rises** above 0.01639. The rise is **smaller
  than ADR-015's +81%** on q005.
- P3. Any k=3 gain comes from `decision` or `architecture`, not `comparison`.

## Acceptance tests

- [ ] `make retrieval-recall` on the fixed snapshot prints the four numbers A1–A4
      evaluate, and the rule's outcome can be read off them by someone who has not
      read this file
- [ ] A query whose lexemes are all above the cutoff returns zero sparse rows and
      a normal dense list (integration test against Postgres)
- [ ] A query with SQL or tsquery metacharacters (`'`, `&`, `|`, `!`, `:*`, `(`)
      returns results or an empty sparse side, never an error. The existing
      sanitising tests pass unchanged
- [ ] Changing the corpus so that the largest file's chunk count changes changes
      the cutoff, without code changes (integration test)
- [ ] Two consecutive runs produce identical rankings and scores
- [ ] `make lint` and `make test` pass
- [ ] ADR-017's decision rule is byte-identical to the one in this file's
      "Success criteria", checked before the measurement is taken

## Non-goals

Explicitly out of scope:

- **A weight on the sparse RRF term** (BRAINSTORM Option 3). It is a second knob
  with nothing to tune it against, since RAGAS cannot run.
- **Trying a second cutoff value** if the first fails.
- **The per-project share for comparison questions** and the intent classifier it
  needs. That is its own future ADR, which will retake its before-reading after
  this feature.
- **The fallback threshold.** The out-of-scope scores are reported (SHOULD) but do
  not gate. Whether to fall back is the LLM's job under the system prompt's rule 3,
  measured only by `make eval`, which is blocked on an API key.
- **Answer quality.** Source recall says whether the right file reached the LLM,
  not whether the answer is right (ADR-014).
- **Re-running ADR-015's unfiltered OR.**

## Open questions

- [x] **Q1 (author).** Is **+2 paths** the right margin for A1, rather than +1?
      The case for 2 is above. The cost: a real but small improvement of exactly
      one path is rejected.
      **Settled 2026-09-30: +2 (A1 stays ≥ 40/57).**
- [x] **Q2 (author).** The cutoff is dominated by one file: the Snowflake README
      has 68 chunks, and the next largest file has 30. If that README grows, the
      cutoff grows with it, and fewer lexemes are dropped. The alternative
      structural rule would be "more chunks than the largest *ADR*" (30, 9.9%),
      which drops more. The draft keeps the largest file of any kind, because a
      README is a document like any other and the rule should not special-case
      file types. This is the choice to confirm or change **now**, since it cannot
      change after measuring.
      **Settled 2026-09-30: the largest file of any kind (68 today).**
- [ ] **Q3 (DESIGN).** Where the document frequencies live: `ts_stat` per query
      (a scan of 304 rows today), or a table refreshed with each indexed snapshot
      (ADR-013). Whichever it is, the cutoff must come from the same snapshot the
      chunks came from.
- [ ] **Q4 (DESIGN).** Whether the filtered tsquery can still be built from
      `plainto_tsquery`'s output inside SQL, as ADR-015 did, so that no user text
      is assembled into query syntax in Python.

## Clarity Score self-check

Rate each 1-5. Total must be ≥ 12/15 to proceed to Design.

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | Measured defect (7/50), a fixed before-reading, and a rule that maps every reading to an outcome |
| Users are named and their pain is real | 4 | The author's pain (a false public claim) is concrete. The interviewer's is inferred: no UI exists, so no real user has hit it yet |
| Success criteria include numbers | 5 | A1–A4 are numeric and fixed. The author confirmed the A1 margin (Q1, +2) and the cutoff rule (Q2, largest file) on 2026-09-30, before any measurement |
| **Total** | **14/15** | Proceeds to DESIGN. Q3 and Q4 belong to DESIGN |
