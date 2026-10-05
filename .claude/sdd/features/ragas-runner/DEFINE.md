# DEFINE: The RAGAS runner

> `make eval` generates an answer for every golden-set question through the
> product path and stores the answers in a run file, then scores that file with
> RAGAS, using Claude as the judge. Built and tested without an API key. The first
> real scores wait for the key.

## Metadata

| Field | Value |
|-------|-------|
| Feature | ragas-runner |
| Date | 2026-10-05 |
| Author | christiandrocha (decisions), Claude (draft) |
| Status | Ready for Design (Q1–Q5 approved as proposed by the author on 2026-10-05) |
| Clarity Score | 13/15 |
| ADR | ADR-008 (written in DESIGN). It exists today only as a `Planned` row in `docs/adr/index.md` |
| Brainstorm | [BRAINSTORM.md](BRAINSTORM.md), Option 2, confirmed by the author on 2026-10-05 |
| Key | **No API key exists.** Everything is built and tested on a stub generator and a fake judge. The first real run waits for the key |

## Problem statement

The project has no answer-quality number. `make eval` runs a stub that prints
"not yet implemented", so the README badges read `pending`, and no change to the
prompt, retrieval or model can be shown to make answers better or worse. The
pieces that should hold a real run were written before ADR-011, ADR-018, ADR-020
and ADR-021, and cannot hold one. `RAGASReport` requires scores that are undefined
for out-of-scope questions. The `eval` extra pins a RAGAS API that has been
replaced. `ragas.yml` builds a database without `sql/04`. And the regression rule
"> 0.05" has no measurement behind it.

## Users

| User | Role | Pain point |
|------|------|-----------|
| The author | Changes prompt, retrieval and model, and makes public claims about quality | Cannot tell whether a change helped. Cannot publish a RAGAS number, because none exists |
| A reviewer of the repo (recruiter, engineer) | Reads the README badges and ADRs | Sees `pending` everywhere, with no path to a number |
| CI (`ragas.yml`) | Will run the regression gate (ADR-011's precondition) | Runs a stub, so it can only be dispatched by hand, and proves nothing |

## Definitions

- **Run file:** what stage 1 (`generate`) writes. A header with provenance, then
  one record per golden-set question: id, intent, question, the text shown, the
  contexts in rank order, the `AnswerResult` fields, and the trace id.
- **Report:** what stage 2 (`score`) writes next to the run file. One row per
  question, the aggregate, and the judge's configuration.
- **Provenance**, per ADR-011: the git SHA of `evaluation_questions.yml`, the
  corpus commits, the embedding model, the system prompt and context format
  versions, the generation model. The report adds the judge model and the RAGAS
  version.
- **In-scope / out-of-scope:** by the question's `intent` in
  `evaluation_questions.yml`: 45 in scope, 5 out of scope.

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | **Stage 1, `generate`:** call `answer()` for each of the 50 questions and write the run file, with provenance. A failed question is recorded as failed, and the run continues |
| MUST | **Stage 2, `score`:** read a run file. Score the 45 in-scope questions on faithfulness, answer relevancy, context precision (with reference) and context recall. Score the 5 out-of-scope questions on `fallback_correct` only (Q3) |
| MUST | **No invented score.** A metric RAGAS cannot compute (an error, a NaN) is recorded as missing with its reason, never as 0 or as a number. The aggregate gives each metric's mean together with how many questions it covers |
| MUST | **ADR-011's gates:** `make eval` and `make eval-ci` run `verify_adversarials.py` first, and its non-zero exit stops the run before anything is generated. Comparing two reports with different golden-set SHAs refuses and says why |
| MUST | **Eval queries are marked in `query_log`:** a new `origin` column (`sql/05`, `'visitor'` by default, `'eval'` from stage 1) (Q1) |
| MUST | **Scores go to Langfuse** on the record's trace id, one score per metric. Langfuse down or disabled does not stop or change the run |
| MUST | **RAGAS telemetry is off:** `RAGAS_DO_NOT_TRACK=true` is set in one place, before `ragas` is imported |
| MUST | **No key, no work:** both stages check for the key first and exit non-zero with one clear line, before any call |
| MUST | The `eval` extra pins ragas 0.4.x and its own requirements (`datasets>=4`). The judge is Claude through `llm_factory(provider="anthropic")`, and the embeddings are the local `bge-small-en-v1.5` |
| MUST | `RAGASReport` and `RAGASAggregate` are rewritten so they can hold a real run (optional metrics for out-of-scope questions, coverage counts, provenance). The KB is mirrored in the same pass |
| SHOULD | **Noise before threshold (Q4):** a way to score one run file twice and print each metric's difference. ADR-008 states the regression rule's form, and leaves the number to be chosen from this measurement |
| SHOULD | **Baseline (Q5):** runs are written to `.claude/dev/reports/` (gitignored). A deliberate `make eval-baseline run=FILE` copies a chosen report to a committed path, `docs/eval-baselines/` |
| SHOULD | `ragas.yml` applies `sql/04` and `sql/05`, so the dispatched job can run once the key exists. It stays `workflow_dispatch` only |
| SHOULD | Stage 2 can resume: a report that already has scores for a record does not score it again |
| COULD | A `make eval-dry` that prints what stage 1 and stage 2 would send, with no key and no call, like `make fallback-eval-dry` |

## Success criteria (measurable)

All measured without a key, unless marked otherwise.

- [ ] Stage 1 on the 50-question golden set, with a stub client, writes **50**
      records and **1** provenance header. The header's golden-set SHA equals
      `git log -1 --format=%H -- docs/golden-set/evaluation_questions.yml`
- [ ] Stage 2 on a run file of 45 in-scope and 5 out-of-scope records, with a
      fake judge, writes **50** report rows: **45** with four metric fields and
      **5** with `fallback_correct` only
- [ ] A fake judge that fails on **1** metric of **1** question gives **1**
      missing value with a reason, **0** zeros, and a coverage count of 44 for
      that metric
- [ ] The contamination gate exiting 1 leaves **0** records written and **0**
      generator calls
- [ ] Two reports with different golden-set SHAs: the comparison exits non-zero,
      and prints both SHAs
- [ ] With a recording Langfuse fake: **4** scores per in-scope record and **1**
      per out-of-scope record, each on the record's trace id. With a Langfuse that
      raises on every call, the same report is written
- [ ] Every stage-1 row in `query_log` has `origin = 'eval'`. A row from the page
      has `origin = 'visitor'`. `sql/05` applied twice on a populated table: no
      error, rows intact
- [ ] No key: both stages exit non-zero with **0** calls
- [ ] `make lint` and `make test` green. **No test calls an API, needs a key, or
      needs network**
- [ ] *(With the key, later.)* One real `make eval-ci`, then a second scoring of
      the same run file. Each metric's difference between the two is recorded in
      ADR-008, and the regression threshold is chosen from it

## Acceptance tests

- [ ] `make eval` with the contamination gate failing: the gate's message, exit
      non-zero, no run file
- [ ] `make eval` with no key: one line naming `ANTHROPIC_API_KEY`, exit non-zero,
      no run file
- [ ] Stage 2 on a hand-written run file with a fake judge prints a table: one row
      per metric, its mean and its coverage (`n/45`), and `fallback_correct` as
      `n/5`
- [ ] The comparison of two reports with different golden-set SHAs prints "not
      comparable" and both SHAs
- [ ] `make eval-baseline run=FILE` copies the report to `docs/eval-baselines/` and
      refuses a file that is not a report
- [ ] *(With the key, later.)* `make eval-ci` writes a run file and a report. Every
      in-scope record's trace in Langfuse carries its four scores. The README
      badges are updated from that report only

## Non-goals

Explicitly out of scope:
- **A regression threshold number.** Its form is written in ADR-008. The number is
  chosen after the noise measurement, which needs the key
- **A push or PR trigger on `ragas.yml`.** It stays manual until a baseline exists
- **Numbers in the README badges.** They change only from a real `make eval-ci`
  report
- **ADR-020's 30 out-of-scope questions.** They are measured by `make
  fallback-eval` with ADR-020's own decision rule. Scoring them here too would
  give two numbers for one claim
- **Changing retrieval, the prompt or the model.** The runner measures them; it
  does not tune them
- **Other RAGAS metrics** (noise sensitivity, factual correctness and so on)

## Open questions

- [x] **Q1. Eval rows in `query_log`:** marked by an `origin` column (`sql/05`).
      Approved 2026-10-05
- [x] **Q2. The judge model.** The generator is `settings.llm_model`
      (`claude-sonnet-4-6`). **Recommendation: Claude Opus 5.5
      (`claude-opus-5-5`) as the judge**, in a new `settings.judge_model`. Two
      reasons:
      - A model judging its own output tends to score it more kindly, so the judge
        should not be the generator.
      - Every metric here is a judgment call (does this statement follow from
        this text?), and a weaker judge makes the scores noisier. Q4's noise
        measurement then has to absorb that noise.

      The trade-off is cost, which has not been measured. The first real run
      records the judge's tokens, so the cost becomes a number, not a guess.
      Haiku 4.5 is the cheap alternative. Sonnet would avoid a second model but
      keeps the self-judging problem. **Approved 2026-10-05: Opus 5.5.**
- [x] **Q3. Metrics per question:** four metrics on 45 in scope,
      `fallback_correct` only on 5 out of scope. Approved 2026-10-05
- [x] **Q4. Noise before threshold:** two scorings of one run file, before a
      number is chosen. Approved 2026-10-05
- [x] **Q5. Where runs live:** `.claude/dev/reports/` (gitignored). The baseline is
      copied to a committed path by a deliberate step. Approved 2026-10-05

## Clarity Score self-check

Rate each 1-5. Total must be ≥ 12/15 to proceed to Design.

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | Each stale piece is named, and each has a criterion that fails today |
| Users are named and their pain is real | 4 | The author's pain is real and current. The reviewer's is inferred from the `pending` badges, not reported by anyone |
| Success criteria include numbers | 4 | Every criterion without the key has a count. The one that matters most, the noise per metric, can only be a number after the key exists |
| **Total** | **13/15** | Ready for DESIGN |
