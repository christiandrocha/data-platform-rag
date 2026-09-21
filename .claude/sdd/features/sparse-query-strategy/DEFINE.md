# DEFINE: The tsquery function — making the sparse side exist

> Give the sparse half of hybrid retrieval a populated result list for
> question-shaped input, and decide by measurement whether that helps, hurts, or
> changes nothing.

## Metadata

| Field | Value |
|-------|-------|
| Feature | sparse-query-strategy |
| Date | 2026-09-21 |
| Author | christiandrocha |
| Status | Ready for Design |
| Clarity Score | 14/15 |
| BRAINSTORM | [BRAINSTORM.md](BRAINSTORM.md) — emerging preference: Option 1, conditional on measurement |

## Problem statement

`plainto_tsquery` conjoins every term of the query, so a natural-language
question requires one chunk to contain all of them. Across the golden set the
sparse side returns **0 chunks for four of five questions**. The RRF fusion is
arithmetically correct and hand-asserted in tests, but it has only ever had one
list to fuse: **this project's "hybrid" retrieval is dense-only for questions,
and has been since the query was written** (ADR-003 Amendment 1 §B).

It is not dead for every input. Measured live on 2026-09-21,
`make ask q="why Snowpipe Streaming?"` — three words, not a sentence — returns
sparse scores of 0.2091 and 0.3118 and fused scores of 0.03202, which is two
contributions summed rather than one. The sparse side is **inert for questions
and alive for keywords**, and nothing in the system currently knows which of the
two it will be given.

## Users

| User | Role | Pain point |
|------|------|-----------|
| The curator (repo author) | Runs `make ask` and `make retrieval-recall` to judge retrieval | Cannot tune or trust a hybrid retriever whose second half never votes. Half the machinery described in ADR-003, the README and AGENTS.md is decorative |
| The reranker, once ADR-005 lands | Downstream consumer of the top-20 | Receives candidates from a retriever that cannot match exact identifiers (`ADR-0029`, `Lakeflow`, `Unity Catalog`) except by embedding similarity — the case a sparse side exists to cover |
| The end user, once a UI exists | Asks about platform decisions | Today hypothetical: no UI exists (`ui/app.py` is a stub). Their input shape — question or keywords — is the open question this feature cannot answer alone |

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | The sparse side returns at least one row for **5 of 5** golden-set questions |
| MUST | The change is a query-construction change only — no schema change, no new dependency, no index rebuild |
| MUST | A before/after `make retrieval-recall` on the **same snapshot** decides whether it ships, per the decision rule below |
| MUST | The tsquery is built inside Postgres from `plainto_tsquery`'s own output, so no user text reaches the query as syntax |
| SHOULD | The fused ordering stays explainable: one retriever, one code path, no branch selected by a property of the data |
| SHOULD | `make ask` shows `sparse_rank` populated, so the second voter is visible to the curator |
| COULD | Drop generic terms by corpus document frequency before OR-joining (BRAINSTORM Option 2) — only if the measurement says Option 1 costs precision |
| COULD | A weight on the sparse side of the RRF sum, if the equal ballot proves to be the problem |

## Success criteria (measurable)

The before-reading was taken on 2026-09-21 against snapshot
`/tmp/dpr-corpus-20260921-142450` (`sdd-kafka-databricks@f1295df9`,
`sdd-kafka-snowflake-2@82a2e269`), artifact
`.claude/dev/reports/retrieval-recall-20260921-142654.json`. It reproduces the
2026-09-18 baseline exactly — same ranks, same numbers — so the comparison is
against a stable reference, not a moving one.

- [ ] Sparse rows returned for **5/5** golden-set questions, up from **1/5**
- [ ] Source recall at k=3 is **≥ 3/6**, i.e. never worse than today's 50 %
- [ ] Source recall at k=10 and k=20 are **≥ 5/6**, i.e. never worse than today's 83 %
- [ ] q001's declared path (`0029_snowpipe_streaming…`) **stays at rank 1**
- [ ] Two consecutive `make retrieval-recall` runs produce **identical** rankings
- [ ] `make test` green, with **at least 6** new tests covering the new query shape

**The decision rule, fixed before the measurement so the result cannot be
rationalised after it:**

| reading at k=3 | verdict |
|---|---|
| improves (≥ 4/6) | Option 1 ships as the answer |
| flat at 3/6, and k=10 or k=20 improves | retrieval is not the bottleneck; the case passes to ADR-005 and Option 1 ships only if nothing regressed |
| degrades (< 3/6) | Option 1 is rejected. The equal-ballot risk is real, and the decision becomes Option 2 (term filtering) or Option 4 (honest dense-only) |

## Acceptance tests

- [ ] `make ask q="Why does the Databricks project use one unified Lakeflow pipeline instead of many parametrized notebooks?"` — a full-sentence question — prints a populated `sparse` column and at least one non-null `sparse_rank`
- [ ] The same command on today's code prints an empty sparse side, so the two outputs differ observably
- [ ] `EXPLAIN ANALYZE` of the fused query shows the sparse subquery returning `rows > 0` where today it reports `rows=0` with `Rows Removed by Filter: 304`
- [ ] A unit test asserts the generated tsquery contains `|` and no `&` for a multi-term question, without touching a database
- [ ] An integration test with hand-chosen content asserts a chunk matching **one** query term is ranked by the sparse side and contributes exactly `1/(60+rank)` to the fused score
- [ ] An integration test asserts that a query containing a `'` or a `:` cannot produce a syntax error or alter the query shape — the sanitising must still come from `plainto_tsquery`
- [ ] `make retrieval-recall` writes a second artifact, and both JSONs name the same snapshot commit SHAs

## Non-goals

- **Implementing the reranker.** ADR-005 stays Planned. This feature changes what
  reaches it, not what it does.
- **The `fallback_threshold` question.** Separate and already open: the threshold
  is 0.35 against an RRF score whose maximum is 0.0164, and it belongs to ADR-005
  and ADR-006, not here. This feature must not make it worse and must not pretend
  to fix it.
- **Tuning `RRF_K`.** Fixed at 60 by ADR-003; a different constant cannot turn an
  empty list into a populated one.
- **Growing the golden set** from 5 towards 50. Needed, and a different feature.
  Its absence is why every number here carries its denominator.
- **Any schema change**, new index, or new dependency.
- **Deciding whether the product receives questions or keywords.** That is a UI
  question and there is no UI.

## Open questions

- [ ] **Does the sparse side need a weight?** RRF adds `1/(60+dense_rank)` and
      `1/(60+sparse_rank)` with no coefficient, so a sparse list of ~200 rows
      votes as loudly as a dense list of 20. There is no weight field in the
      query or in `config.py`. ADR-003 says weights are RAGAS-tuned; RAGAS does
      not exist. **Deferred to DESIGN**, which must at least say whether the
      field is introduced now or deliberately left absent.
- [ ] **Where does term filtering live, if it is needed?** Option 2 needs
      document frequencies, and they can be recomputed per query, cached in a
      table tied to `corpus_snapshot`, or frozen as a constant that rots. Only
      opened if the measurement rejects Option 1.
- [ ] **Which input shape will the product receive?** Unanswerable until a UI
      exists. It decides whether Option 3's AND-first branch is a rare shortcut
      or the common path. Recorded so that the UI feature inherits it rather than
      rediscovering it.

## Clarity Score self-check

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | Stated as a measurement with a query plan behind it: `rows=0`, `Rows Removed by Filter: 304`, 0 chunks for 4 of 5 questions. The opposite case is equally concrete — 0.2091 and 0.3118 on a keyword query, measured today |
| Users are named and their pain is real | 4 | The curator's pain is real and current; the reranker's is real and imminent. The end user is honestly hypothetical — there is no UI — and the criterion is marked down for it rather than inflated |
| Success criteria include numbers | 5 | Every criterion carries one, all derived from a before-reading taken today and reproducible from its artifact. The decision rule is fixed in advance, including the reading that rejects the preferred option |

**Total: 14/15** — above the 12/15 gate. Proceed to DESIGN.
