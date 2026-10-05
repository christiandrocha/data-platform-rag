# ADR-008 — The RAGAS runner: two stages, an Opus judge, no invented score

**Status**: Planned — 2026-10-05. Accepted when BUILD lands. The regression
threshold is chosen after the measurement in Decision 7, and recorded here in place
**Date**: 2026-10-05

## Context

The project has no answer-quality number. `make eval` runs a stub, the README
badges read `pending`, and no change to the prompt, retrieval or model can be shown
to help or hurt. ADR-014's source recall measures retrieval only, and says so.

This ADR was planned from the start and never written. Meanwhile other decisions
have put constraints on it:

- **ADR-011** requires every run to record the golden set's git SHA, comparisons
  across different SHAs to refuse, and `verify_adversarials.py` to gate every run.
- **AGENTS.md** requires RAGAS scores to attach to the Langfuse trace that produced
  the answer, and forbids inventing a score.
- **ADR-021** made `answer()` the product path: one `query_log` row and one trace
  per query.
- **ADR-020** measures the out-of-scope gate on its own 30 questions, with its own
  rule.

The artefacts written before those decisions cannot hold a real run:

- `RAGASReport` requires four scores for every question, including the 5
  out-of-scope ones, which have no reference answer.
- The `eval` extra pins `ragas>=0.2`. The current API is 0.4.
- The regression rule, "> 0.05 from the previous run", has no measurement behind it.

The API key does not exist yet. Everything below is built and tested without it.

## Decision

1. **Two stages.**
   - **`generate`** calls `answer(..., origin="eval")` for every question in
     `evaluation_questions.yml`. It writes a run file: provenance, plus each
     question's `AnswerResult` and the text of its contexts.
   - **`score`** reads a run file and writes a report.

   Answers are generated once and can be scored many times. Every score points to
   the text it judged.

2. **Eval queries are real product queries, marked.** `query_log.origin`
   (`sql/05`, `'visitor'` by default) is `'eval'` for stage 1. The product trace is
   what the scores attach to.

3. **The judge is Claude Opus 5.5** (`settings.judge_model`), not the generator
   (`settings.llm_model`, Sonnet). A model judging its own output tends to score
   it more kindly, and a weaker judge makes the scores noisier.
   - The judge runs through RAGAS 0.4's `llm_factory(provider="anthropic")` on an
     `AsyncAnthropic` client.
   - `judge_max_tokens = 4096`, not measured. A reply truncated by it is a missing
     value (Decision 5), not a score.

4. **Metrics per question.**
   - The 45 in-scope questions get faithfulness, answer relevancy, context
     precision with reference, and context recall.
   - The 5 out-of-scope questions get `fallback_correct` (`AnswerResult.fallback_fired`)
     only. Two of the four metrics need a reference they do not have.
   - An in-scope question that got the fallback is scored as it is, and counted
     separately.
   - Embeddings for answer relevancy are the local `bge-small-en-v1.5`, through
     `embed_query`.

5. **No invented score.** A metric that raises, returns NaN, or belongs to a failed
   generation is recorded as missing, with its reason. A mean covers scored
   questions only and is always reported with its coverage, `mean (n/45)`. A
   missing value is never a 0.

6. **Comparability.** Every run records ADR-011's provenance:
   - the golden-set SHA, and whether the file was modified;
   - corpus commits, embedding model, generation model;
   - prompt and context versions, `rerank_top_k`.

   Every report also records the judge model, `max_tokens`, the RAGAS version and
   answer relevancy's strictness. `compare` refuses, and says why, when the
   golden-set SHA, a modified golden set, the judge model, the RAGAS version or the
   strictness differ. Differences in what is being evaluated (prompt, model, k) are
   allowed and printed.

7. **The regression gate: its form now, its number from a measurement fixed now.**
   - **Form:** a metric's mean falling below the baseline's by more than T(metric)
     fails `compare --gate`.
   - **How T is chosen, decided before measuring:**
     1. Generate 2 runs, and score each twice.
     2. T(metric) is the largest difference between any two of those 4 means for
        that metric.
     3. The 4 means and each T are recorded here in place.
   - Until then, `compare` reports and never fails on a delta. `ragas.yml` stays
     `workflow_dispatch`.
   - The "> 0.05" rule is withdrawn: it was never measured.

8. **Gates on every run.** `make eval` and `make eval-ci` run
   `verify_adversarials.py` first, and a non-zero exit stops the run before
   anything is generated (ADR-011). Without a key, every stage that calls an API
   exits before its first call.

9. **Scores go to Langfuse** on the record's trace id: one score per metric, and
   `fallback_correct` as a boolean. Pushing is fire-and-forget. A failure is logged
   and recorded per question as `pushed_to_langfuse=False`.

10. **RAGAS telemetry is off.** RAGAS reports usage to its maintainers unless
    `RAGAS_DO_NOT_TRACK=true`. The runner sets it, with `setdefault`, before
    importing `ragas`. That is the only place it is written.

11. **The baseline is committed.** Runs stay in `.claude/dev/reports/`
    (gitignored). A chosen report and its run file are copied to
    `docs/eval-baselines/` by `make eval-baseline`. README badges are taken from a
    committed baseline only.

## Consequences

**Positive**
- The first key turns into numbers with one command, and every number can be
  traced to a file and a trace.
- A judge bug or a configuration change costs a rescoring, not a regeneration.
- The tests run RAGAS's own metric code against a fake judge, so the wiring is
  tested before the first paid run.
- `query_log` stays honest as an analytics table: eval traffic can be filtered out.

**Negative**
- **Two Claude models** to pay for. The judge's cost is unmeasured. The first run
  records the tokens, and that is the number this ADR will cite.
- **RAGAS brings a heavy dependency set** (`langchain`, `openai`, `instructor`,
  and others) into the `eval` extra, and into CI's test job, so its tests do not
  skip.
- **The first real run is 2 generations and 4 scorings**, not one, because of
  Decision 7.
- **The gate does not exist until that measurement has run.** Until then a
  regression is visible in `compare`, and nothing blocks it.
- **50 questions is a small set.** One question moves a mean by about 2 points.
  Decision 7's noise measurement is what keeps that from being read as a signal.

**Neutral**
- ADR-014's source recall stays: it is retrieval-only and free.
- ADR-020's out-of-scope measurement stays separate: a different question set and a
  different rule.

## Alternatives Considered

- **One pass (generate and score together).** The least code. Rejected: every
  rescoring regenerates, and a late failure loses the run.
- **Own LLM-as-judge metrics, no RAGAS.** No heavy dependencies. Rejected: the
  scores would carry RAGAS's names without RAGAS's definitions. That would need a
  new stack decision, not a quiet substitution.
- **Sonnet as the judge.** One model, cheaper. Rejected: it would be judging its
  own answers.
- **OpenAI as the judge** (RAGAS's default). Rejected: a second vendor and key for
  no gain. 0.4 supports Anthropic.
- **Write eval rows unmarked, or not at all.** Rejected: unmarked rows corrupt
  visitor analytics, and no rows means no product trace for the scores.
- **Keep "> 0.05 from the previous run".** Rejected: unmeasured, and "previous run"
  is not a baseline: a slow slide passes every step.
- **Score the 30 ADR-020 out-of-scope questions here too.** Rejected: two numbers
  for one claim, under two rules.
