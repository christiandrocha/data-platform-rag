# ADR-019 — Cosine-similarity separability decides the out-of-scope gate

**Status**: Accepted — 2026-09-30. Branch taken: **not separable**. See [Outcome](#outcome)
**Date**: 2026-09-30
**Supersedes in part**: ADR-006 (its score gate; the fallback itself stays)

> Written before any similarity was measured. The Context, Decision and
> Consequences sections are kept exactly as written before the Outcome was
> added. They are the prediction the outcome is judged against, as in ADR-015,
> ADR-017 and ADR-018. Unlike those, this ADR is Accepted whichever way the
> measurement goes: what it decides is the *method*, and the Outcome records which
> branch the method took.

## Context

ADR-006 decided that when the top-ranked chunk falls below "0.35 cosine", the
system returns the fixed LinkedIn message and does not call the LLM. Nothing
implements it. Three facts stand in the way:

- **The score retrieval reports cannot do it.** Since ADR-018, `rrf_score` is
  `1/(60 + dense_rank)`, so the top score is `1/61` for every question (ADR-018
  P2, measured).
- **The number ADR-006 means has never been looked at.** Cosine similarity is
  `1 − dense_distance`, already in `RetrievedChunk`. No artifact records it: the
  recall reports hold rank, path, anchor and `rrf_score` (checked 2026-09-30).
- **0.35 was never measured.** ADR-006 calls it "a magic number". Whether
  bge-small-en-v1.5's similarities for this corpus even fall near 0.35 is
  unknown.

A second gate is designed as well. The system prompt's rule 3 tells the LLM to
return the same message when "the retrieved context does not directly answer the
question". ADR-006 rejected relying on the LLM alone, because LLMs fabricate
under weak context. Neither gate is built, because generation does not exist.

Every design for the fallback assumes an answer to one question: **can cosine
similarity tell an in-scope question from an out-of-scope one, for this model and
this corpus?** The golden set has 45 in-scope and 5 out-of-scope questions (q005,
q047–q050). q047–q050 were written to sit close to the corpus (ADR-016). Fitting
a threshold on those 5 would fit it on the test.

## Decision

**Measure the top-1 cosine similarity of every golden question once, and let a
fork fixed here, before the measurement, decide which gate the project builds.**

- A question's **top similarity** is `1 − dense_distance` of its rank-1 chunk, as
  `pipeline.retrieve(question)` returns it with default collections.
- `make retrieval-recall` records `dense_distance` per ranked chunk and
  `top_similarity` per question. It prints four numbers: the lowest in-scope top
  similarity, the highest out-of-scope one, and the count of each class on the
  wrong side of the other's extreme. It prints numbers, not a verdict.
- **No gate is built and `settings.fallback_threshold` is not changed here.** The
  branch decides the next ADR.
- **`rrf_score` stays for now** (author, 2026-09-30). It leaves with the next ADR's
  contract change, whichever branch.

The fork, copied byte for byte from the feature's DEFINE. BUILD checks that
before measuring:

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

## Consequences

**Pre-registered predictions, not deciding** (copied from DEFINE and judged in the
Outcome):

- P1. **Not separable.** q047–q050 were written to sit close to the corpus
  (ADR-016).
- P2. At least **2** of the 5 out-of-scope questions sit at or above the lowest
  in-scope top similarity.
- P3. q005 has the **lowest** top similarity of the 5 out-of-scope questions.

**In the separable branch, the golden set stops being enough.** The threshold
needs its own out-of-scope questions, written for calibration and disjoint from
the golden set, or the value is fitted on the test. That is new curation work, and
it is the next ADR's first task.

**In the not-separable branch, the fallback does not go away.** AGENTS.md forbids
removing it, and it is a product decision. What goes is the *score gate*: the
LinkedIn message is then sent by the LLM under rule 3. ADR-006 is superseded in
part, not in whole. AGENTS.md's RAG-discipline line ("if retrieval score falls
below threshold, use the fixed fallback message") is rewritten to match. The cost
ADR-006 feared, tokens spent on out-of-scope queries and fabrication under weak
context, becomes something `make eval` must measure once it exists.

**Separable on 50 questions is necessary, not sufficient.** With 5 negatives, a
clean split can be luck. That is why the separable branch does not pick the value
here.

**Nothing in retrieval moves.** The feature adds fields to the recall artifact
and a column to `make ask`. Rankings and recall must equal ADR-018's artifact.

## Alternatives considered

**1. Calibrate the threshold now, on the golden set.** It fits the value on the
50 questions that grade the system, 5 of them negative. That is the overfitting
ADR-017's "no swept cutoff" rule exists to prevent.

**2. Supersede the score gate now, and let the LLM decide.** It reverses ADR-006
without a measurement, and `make eval` cannot measure the replacement today.

**3. Two gates: a conservative score gate plus rule 3.** Probably the end state if
similarity separates. It still needs a threshold, so it waits for this fork.

**4. Wire 0.35 as it is.** Never measured. It could fire on everything or on
nothing.

**5. A relative score** (the gap between the top 1 and the top k, or a z-score).
Another number to calibrate, and nothing shows the absolute similarity has failed.

**6. Tolerate one question on the wrong side.** Rejected by the author on
2026-09-30. A threshold that already misclassifies one curated question has
nothing to stand on with 5 negatives.

## Outcome

**Not separable. ADR-006's score gate is superseded. Out of scope is rule 3's
job.** Measured on 2026-09-30 on snapshot `sdd-kafka-databricks@f1295df9`,
`sdd-kafka-snowflake-2@82a2e269`, `BAAI/bge-small-en-v1.5`, golden set
q001–q050: `.claude/dev/reports/retrieval-recall-20260930-185210.json` and
`-185224.json`, two runs, identical results. Code measured: commit
`feat(eval): top-1 similarity separability in the recall report (ADR-019,
pre-measurement)`. The fork was checked byte-identical to DEFINE's immediately
before the first run.

| | value | question |
|---|---|---|
| lowest in-scope top similarity | 0.6040 | q027 (architecture) |
| highest out-of-scope top similarity | **0.7360** | q005 |
| in-scope questions at or below 0.7360 | **14** of 45 | |
| out-of-scope questions at or above 0.6040 | **4** of 5 | |

Out of scope, by top similarity: q050 0.5628 (prompt extraction), q049 0.6228
(React frontends), q048 0.6519 (Apache Iceberg), q047 0.7194 (why not Airflow),
q005 0.7360 (Flink versus Kafka Streams). The lowest in-scope ones: q027 0.6040,
q046 0.6292 (comparison), q031 0.6387, q029 0.6393, q044 0.6483 (comparison),
q035 0.6748. The highest in-scope top similarity is 0.9005.

Retrieval did not move. Against the ADR-018 artifact
(`retrieval-recall-20260930-182208.json`), k=3/10/20 were 38/44/46, no top-3
path was lost, and all 50 rankings were identical.

**Only one out-of-scope question sits below every in-scope one:** q050, the
prompt-extraction probe, the question least like the corpus in subject. Every
question that asks about a real data-engineering topic the corpus does not cover
(Flink, Airflow, Iceberg) scores like an in-scope question, because the corpus is
about neighbouring topics. No threshold on this number separates "about Kafka
Streams" from "about Kafka". Any cut that rejects q005 also rejects 14 in-scope
questions, about a third of the set, and any cut that keeps every in-scope
question lets 4 of the 5 out-of-scope questions through.

**The predictions, checked:**

- *P1, not separable*: **right.**
- *P2, at least 2 of the 5 out-of-scope questions at or above the lowest in-scope
  one*: **right**, 4.
- *P3, q005 has the lowest top similarity of the 5*: **wrong, and inverted.** q005
  has the *highest* (0.7360). It asks about stream-processing engines next to a
  corpus about Kafka pipelines. The prediction assumed the oldest, least
  adversarial question would be the easiest to reject. Similarity measures topic
  proximity, not answerability.

**What follows, per the fork:**

- ADR-006 is superseded in part, in place: its score gate goes, and its fallback
  message and product decision stay. AGENTS.md forbids removing the fallback, and
  the fallback does not leave. What changes is who sends it: the LLM, under the
  system prompt's rule 3.
- AGENTS.md's RAG-discipline line, the README's architecture text and diagrams,
  and the KB pages that describe a `threshold_check` are rewritten to match.
- **`settings.fallback_threshold` stays until the ADR-019 follow-up removes it**
  (DEFINE). Nothing reads it, and removing a setting is an interface change of its
  own. It is marked unused.
- **The cost ADR-006 feared is now the thing to measure.** Every out-of-scope
  query reaches the LLM, so it spends tokens and the LLM may fabricate under weak
  context. `make eval`'s `fallback_accuracy` (in `RAGASAggregate`) is the number.
  It cannot run until generation exists and an API key is configured.

## Amendment 1 — 2026-09-30, the follow-up: constant fields and the unused setting removed

The Outcome said `settings.fallback_threshold` leaves "in the ADR-019 follow-up",
and the Decision said `rrf_score` "leaves with the next ADR's contract change".
The author chose (2026-09-30) to remove every field that has been constant since
ADR-018 in the same change, and to run it as a lean feature
(`.claude/sdd/features/adr-019-cleanup/`) with no new ADR.

**Removed:**

- `RetrievedChunk.rrf_score` (the rank as `1/(60 + rank)`), `sparse_score`
  (always 0.0) and `sparse_rank` (always None). `RetrievedChunk` now has five
  fields, `dense_rank` is required, and `extra="forbid"` rejects a caller still
  passing a removed field.
- `RRF_K` and the query's `%(rrf_k)s` parameter. The query returns no constant
  columns.
- `settings.fallback_threshold` and `FALLBACK_THRESHOLD` in `.env.example`.
  `Settings` has `extra="ignore"`, so a deployment still setting the variable keeps
  starting (unit test).
- `rrf_score`, `sparse_rank`, `top_rrf_score(s)`, `has_sparse_rows` and
  `questions_with_sparse_rows` from new recall artifacts. The script still reads
  old artifacts as baselines.

**Neutral, measured:** `make retrieval-recall baseline=retrieval-recall-20260930-185210.json`
→ `retrieval-recall-20260930-192021.json`: k=3/10/20 38/44/46, 0 top-3 paths lost,
50/50 rankings identical, and every `dense_distance` and `top_similarity` equal.
