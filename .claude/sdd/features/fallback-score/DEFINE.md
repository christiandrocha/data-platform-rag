# DEFINE: Does cosine similarity separate in scope from out of scope?

> Measure the top-1 similarity of every golden question once, and let a fork
> written before the measurement decide which fallback gets built.

## Metadata

| Field | Value |
|-------|-------|
| Feature | fallback-score |
| Date | 2026-09-30 |
| Author | christiandrocha (decisions), Claude (draft) |
| Status | Ready for Design (Q1, Q2 settled by the author on 2026-09-30, before any measurement) |
| Clarity Score | 14/15 |
| ADR | ADR-019 (written in DESIGN, Status Planned until BUILD's measurement; its Outcome records which branch the fork took) |
| Brainstorm | [BRAINSTORM.md](BRAINSTORM.md), Option 1, confirmed by the author on 2026-09-30 |

## Problem statement

ADR-006 says the system returns the LinkedIn fallback, without calling the LLM,
when the top retrieved chunk falls below "0.35 cosine". Nothing implements that,
and nothing can yet. The only score retrieval reports, `rrf_score`, is `1/61` for
every question since ADR-018. The number ADR-006 means, cosine similarity
(`1 − dense_distance`), has never been looked at. **Whether it can tell an
in-scope question from an out-of-scope one at all, for this model and this
corpus, is unknown.** Every design for the fallback (score gate, LLM-only, both)
assumes an answer. This feature gets the answer, with its meaning fixed before
it exists.

## Users

| User | Role | Pain point |
|------|------|-----------|
| The author | Owns the product decision in ADR-006 (honest scope, LinkedIn redirect) | The fallback is a product feature with a number nobody measured. Its design choice (gate before the LLM, or the LLM decides) has no evidence behind it |
| A visitor asking something the corpus does not cover | Would receive the fallback | Too strict a gate turns answerable questions into dead ends. Too loose a gate lets the LLM improvise |
| The curator (the author, running `make retrieval-recall`) | Judges retrieval and fallback changes | Needs the separability numbers in the same artifact as recall, tied to the same snapshot |

## The measurement (none exists yet)

No recall artifact records `dense_distance` (checked 2026-09-30). The artifacts
record rank, path, anchor and `rrf_score`. So there is no before-reading to
protect. There is one measurement to take, on:

- snapshot `sdd-kafka-databricks@f1295df9`, `sdd-kafka-snowflake-2@82a2e269`,
  embedding `BAAI/bge-small-en-v1.5`, 304 chunks
- golden set q001–q050: **45 in scope**, and **5 out of scope** (q005, q047, q048,
  q049, q050)
- retrieval as it ships after ADR-018: dense-only, both collections, exact scan

**Definition.** A question's **top similarity** is `1 − dense_distance` of its
rank-1 chunk, as `pipeline.retrieve(question)` returns it with default
collections.

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | `make retrieval-recall` records, per question, `top_similarity`, and per ranked chunk its `dense_distance`, so any later threshold can be recomputed from the artifact |
| MUST | The recall run prints four numbers: the lowest in-scope top similarity, the highest out-of-scope top similarity, how many in-scope questions sit at or below that highest out-of-scope value, and how many out-of-scope questions sit at or above that lowest in-scope value. It prints numbers, not a verdict |
| MUST | ADR-019 is written in DESIGN, Status Planned, with the fork below copied into it byte for byte **before** BUILD measures |
| MUST | No gate is built, and `settings.fallback_threshold` is not changed, in this feature. The fork only decides which ADR comes next and what it must do |
| MUST | Whichever branch the fork takes, ADR-006 and the README stop implying a calibrated 0.35 cosine gate exists |
| SHOULD | `make ask` prints each chunk's similarity, so a curator can see the number a gate would read |
| COULD | The recall report lists the out-of-scope questions sorted by top similarity next to the nearest in-scope ones, for the next ADR to read |

## Success criteria (measurable): the fork

Applied once, to the first BUILD reading. Retrieval is deterministic (ADR-015,
ADR-017 and ADR-018 each measured two identical runs), so one reading is the
reading. Similarities are compared at full float precision.

**Separable** if and only if **every** in-scope top similarity is **strictly
greater** than **every** out-of-scope top similarity. That is: the lowest of the
45 is above the highest of the 5. Equality counts as overlap.

**Not separable** otherwise: at least one in-scope question at or below at least
one out-of-scope question.

| reading | branch | what it commits the project to |
|---|---|---|
| **Separable** | **Score gate viable** | The next ADR builds ADR-006's gate. Its threshold is calibrated on a **calibration set** of out-of-scope questions written for that purpose, disjoint from the golden set. The golden set only verifies the chosen value, and a verification failure is a rejection, not a re-fit. ADR-006 stays Accepted, and its "0.35" is marked uncalibrated until then |
| **Not separable** | **Score gate superseded** | ADR-006's score gate is superseded in part: cosine similarity cannot tell even the curated set apart, so no threshold on it is defensible. Out of scope becomes the system prompt's rule 3 (the LLM decides), measured by `make eval` once it exists. `settings.fallback_threshold` is removed in the ADR-019 follow-up, since nothing may read it |

Both branches are outcomes, not failures. Neither is "rejected". ADR-019's Status
becomes Accepted either way, and its Outcome records the branch with the numbers.

**Predictions, pre-registered and not deciding** (judged in ADR-019's Outcome):

- P1. **Not separable.** q047–q050 were written to sit close to the corpus
  (ADR-016).
- P2. At least **2** of the 5 out-of-scope questions sit at or above the lowest
  in-scope top similarity.
- P3. q005 has the **lowest** top similarity of the 5 out-of-scope questions.

## Acceptance tests

- [ ] `make retrieval-recall` on the fixed snapshot prints the four numbers, and the
      branch can be read off them by someone who has not read this file
- [ ] The artifact's `results[*].ranking[*]` carries `dense_distance`, and
      `results[*].top_similarity` equals `1 − ranking[0].dense_distance`
- [ ] The four summary numbers are computed by a pure function, unit-tested on
      hand-built results: a separable set, a set overlapping at one question, and an
      exact tie (which counts as overlap)
- [ ] Out-of-scope questions are identified by `intent: out-of-scope`, the same
      field `summarise` already uses, not by a hardcoded id list
- [ ] Rankings and recall are unchanged from the ADR-018 artifact (38 / 44 / 46).
      This feature adds fields, and must not move anything
- [ ] Two consecutive runs produce identical similarities
- [ ] `make lint` and `make test` pass
- [ ] ADR-019's fork is byte-identical to this file's "Success criteria", checked
      right before the measurement

## Non-goals

Explicitly out of scope:

- **Building the gate**, in either branch.
- **Choosing a threshold value.** Not even a provisional one. In the separable
  branch, the calibration set chooses it in the next ADR.
- **Writing the calibration set.** That is the next ADR's first task, in the
  separable branch only.
- **A relative score** (gap, z-score). Discarded in BRAINSTORM.
- **Answer quality and rule 3's accuracy.** `make eval` does not exist.
- **Changing retrieval.** Rankings must not move (acceptance test).

## Open questions

- [x] **Q1 (author).** Is **strict separation** the right bar (the lowest of the 45
      above the highest of the 5, and a tie is overlap)? The alternative tolerates a
      small overlap (for example, one question on the wrong side). The case for
      strict: with only 5 negatives, a threshold that already misclassifies one of
      the curated questions has nothing to stand on. The cost: one borderline
      question decides the whole branch.
      **Settled 2026-09-30: strict. A tie is overlap.**
- [x] **Q2 (author).** What happens to `rrf_score`? It carries no information
      beyond the rank since ADR-018. The draft **keeps it** in this feature,
      because this feature must not move anything and every artifact reports it.
      Removing it would be a contract change for the gate ADR (separable branch) or
      the ADR-019 follow-up (not separable). The alternative is to replace it now
      with a `similarity` field.
      **Settled 2026-09-30: keep it in this feature. It leaves with the next ADR's
      contract change.**
- [ ] **Q3 (DESIGN).** Whether `similarity` becomes a field or a property of
      `RetrievedChunk`, or stays computed in the reports. `dense_distance` is
      already in the contract, so nothing is missing.

## Clarity Score self-check

Rate each 1-5. Total must be ≥ 12/15 to proceed to Design.

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | One unknown (separability), measured once, with every reading mapped to a branch |
| Users are named and their pain is real | 4 | The author's is concrete (a product feature on an unmeasured number). The visitor's is prospective: no UI yet |
| Success criteria include numbers | 5 | The fork is numeric and total. The author confirmed strict separation (Q1) and keeping `rrf_score` for now (Q2) on 2026-09-30, before any measurement |
| **Total** | **14/15** | Proceeds to DESIGN. Q3 belongs to DESIGN |
