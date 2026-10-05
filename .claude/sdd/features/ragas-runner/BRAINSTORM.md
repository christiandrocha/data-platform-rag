# BRAINSTORM: The RAGAS runner (ADR-008)

> Free exploration. No commitments. No commits from this file alone.

## Date
2026-10-05

## Prompt

The author chose to build the RAGAS runner while the API key is not available,
the same way `streamlit-ui` was built: everything testable on stubs, the real run
waiting for the key.

`make eval` and `make eval-ci` call `scripts/run_evaluation.py`, which is a stub
that prints "not yet implemented". `ragas.yml` runs only on `workflow_dispatch`
for that reason. ADR-008 exists only as a `Planned` row in `docs/adr/index.md`:
there is no file. This brainstorm is therefore also the start of ADR-008.

## What already binds ADR-008

Other ADRs made decisions that this one has to honour. They are not open.

| From | Binding |
|---|---|
| ADR-011, commitment 2 | Every run records the git SHA of `evaluation_questions.yml`. Two runs with different SHAs are not comparable, and the comparison tooling must **say so**, not subtract. |
| ADR-011, contamination gate | `make eval` and `make eval-ci` run `verify_adversarials.py` first, and a non-zero exit is a failed run. |
| ADR-014 | Source recall is a different metric and is never shown as a RAGAS score. Badges stay `pending` until `make eval-ci` has run. |
| AGENTS.md | RAGAS scores push to Langfuse **attached to the trace that produced the query**: one score system for eval and production. Never invent a score. |
| ADR-018, ADR-020, ADR-021 | Retrieval is dense-only; the out-of-scope gate is the LLM's rule 3; `answer()` is the product path. |

## What is stale and will be rewritten whatever the option

Found while reading. None of it is wrong today, only written before the decisions
above.

1. **`scripts/run_evaluation.py`** says "regressed > 0.05 from previous run". So
   does `.claude/kb/evaluation/ragas-metrics.md`. A previous run does not exist,
   so no threshold can fire yet, and 0.05 has no measurement behind it.
2. **`RAGASReport`** (`contracts.py`) requires all four metrics for every
   question. The 5 out-of-scope questions in `evaluation_questions.yml` have no
   `expected_answer` and no paths, so context recall and context precision
   (both need a reference) are undefined for them. The contract cannot hold a
   real run.
3. **`pyproject.toml`'s `eval` extra** pins `ragas>=0.2` and `datasets>=3.0`.
   The current release is **ragas 0.4.3**, which requires `datasets>=4.0`. The
   0.2 API and the 0.4 API differ (0.4 has `ragas.metrics.collections` and
   `llm_factory(provider=...)`).
4. **`ragas.yml`** applies `sql/00`–`03`, not `04`. It would fail on the first
   `answer()` insert.

## Facts about RAGAS 0.4.3, read from the wheel

- **The judge can be Claude.** `llm_factory(model, provider="anthropic",
  client=anthropic.Anthropic(...))`, through the `instructor` adapter. No OpenAI
  key is needed, although the package still installs `openai`, `langchain`,
  `langchain-openai` and `langchain-community` as hard dependencies.
- **Embeddings can be local.** There is a Hugging Face / sentence-transformers
  provider, so answer relevancy can use the same `bge-small-en-v1.5` the index
  uses. No second embedding vendor.
- **What each metric needs:**

  | Metric | Needs | Calls the judge | Out-of-scope questions |
  |---|---|---|---|
  | Faithfulness | question, answer, contexts | yes | defined, but meaningless on the fallback message |
  | Answer relevancy | question, answer, **embeddings** | yes (`strictness` questions per answer, default 3) | meaningless on the fallback |
  | Context precision (with reference) | question, **reference**, contexts | yes, once per context | undefined: no reference |
  | Context recall | question, **reference**, contexts | yes | undefined: raises on an empty reference |

- **RAGAS sends usage telemetry by default.** `ragas/_analytics.py` tracks runs
  unless `RAGAS_DO_NOT_TRACK=true`. That has to be set, in one place, whichever
  option wins.

No cost figure is given here. The number of judge calls per question depends on
the answer's length (faithfulness splits it into statements) and is not known
before a run. The first real run measures it.

## Options considered

### Option 1: RAGAS library, one script, one pass

What the stub describes. `run_evaluation.py` loops over the golden set, calls
`answer()` for each question, gives the answers to RAGAS, prints and writes the
report.

- **Pros:** the smallest amount of code. It is what the Makefile and `ragas.yml`
  already expect.
- **Cons:**
  - **Generation and judging are paid together.** Rescoring the same answers
    (a judge bug, a metric setting, another judge model) means generating all 45
    again, at a cost and with answers that may differ.
  - **One failure late in the run loses the whole run**, unless resume logic is
    added, which is most of Option 2 anyway.
  - The answers are never stored outside RAGAS's own result, so a score cannot be
    traced back to the exact text it judged.

### Option 2: RAGAS library, two stages with a stored run (recommended)

- **Stage 1, `generate`:** for each golden-set question, call `answer()` and
  write one record to a run file: question id, the shown answer, the contexts in
  rank order, the `AnswerResult` fields, and the trace id. The file header holds
  the provenance ADR-011 asks for: golden-set SHA, corpus commits, embedding
  model, prompt and context versions, generation model.
- **Stage 2, `score`:** read the run file, score the in-scope questions with
  RAGAS, push each score to Langfuse on the record's trace id, and write the
  report next to the run file. Out-of-scope questions get `fallback_correct`
  only.
- **`make eval`** runs the contamination gate, then both stages. Each stage can
  also run alone.

- **Pros:**
  - **Answers are generated once and can be judged many times.** The judge's
    configuration can change without new answers.
  - **Every score points to the text it judged**, in a file, plus the trace.
  - Stage 1 is the product path, so it is already tested. Stage 2 can be tested
    on a hand-written run file and a fake judge: no key, no database.
  - Resuming after a failure is natural: stage 2 can skip records that already
    have scores.
- **Cons:**
  - More code than Option 1: a run-file contract, two entry points.
  - **`answer()` writes a `query_log` row and a trace for every eval question.**
    The 45 eval queries would mix with visitor queries in the analytics table.
    This needs a decision (see the DEFINE questions). The trace is wanted:
    AGENTS.md needs it for the scores.

### Option 3: own LLM-as-judge metrics, no RAGAS library

Write four small judge prompts for Claude and compute the scores ourselves.

- **Pros:** no `langchain`, `openai` or `instructor` dependency. Every prompt is
  ours and visible. Easy to stub.
- **Cons:**
  - **It is not RAGAS.** The stack, the README badges and ADR-011 all say
    "RAGAS". Scores named after RAGAS metrics but computed differently would
    claim a comparison nobody can make. It would need its own ADR, superseding
    the stack choice.
  - The metric definitions would have to be written, defended and maintained
    here. Our versions would have their own bugs.

### Option 4: build only stage 1 now, choose the judge later

Option 2's stage 1 alone, plus the run file. Stage 2 waits.

- **Pros:** the smallest step that keeps the answers the key will produce.
- **Cons:** `make eval` still does not score anything, so the badges stay
  pending after the key arrives. And stage 2 is the part that can be built
  without a key, which is the reason for doing this now.

## Discarded early

- **OpenAI as the judge** (RAGAS's default). It would add a second vendor and a
  second key for no reason: 0.4.3 supports Anthropic directly.
- **ragas 0.2.x**, to match the old pin. The 0.2 API is the one being replaced.
  Starting a new runner on it means migrating it later.
- **A push trigger on `ragas.yml` and a regression threshold now.** There is no
  baseline, so any threshold would be invented. The first `make eval-ci` run *is*
  the baseline. The gate's rule can be written down now and switched on after.
- **Scoring the 30 out-of-scope questions of ADR-020 here.** That is ADR-020's
  measurement (`make fallback-eval`), with its own decision rule. Scoring them
  twice in two places would produce two numbers for one claim.

## Emerging preference

**Option 2.** It is the only option that keeps every score traceable to the
answer it judged, and that lets the judge be fixed without paying for new
answers. Stage 2 can be built and tested completely without a key, which is the
point of doing this now.

What would change this: if the author does not want eval traffic in `query_log`
at all **and** does not want to add a column to mark it, then stage 1 cannot use
`answer()` as it is. It would call retrieval and generation directly, the way
`fallback_eval.py` does. That would lose the product path's trace and with it
AGENTS.md's "same score system for eval and production".

## Questions for DEFINE

1. **Eval rows in `query_log`:** (a) keep them, marked by a new `origin` column
   (`sql/05`, `'visitor'` or `'eval'`); (b) do not write them, behind a flag on
   `answer()`; or (c) keep them unmarked. (a) is the recommendation: the
   analytics table stays honest and the eval run stays the real product path.
2. **The judge model.** Claude Sonnet is also the model that generates. A model
   judging its own output tends to score it more kindly. A different model (Opus,
   or Haiku for cost) avoids that. This is the author's call. Whichever is chosen
   is recorded in the report.
3. **Which metrics, on which questions.** The proposal: the four metrics on the
   45 in-scope questions, and `fallback_correct` only on the 5 out-of-scope ones.
4. **The regression rule, written now and switched on after the baseline.** For
   example "a metric falls more than X from the baseline". X cannot be chosen
   before one run shows how much the scores move between two runs on the same
   answers. Should the first real step be **two scoring runs on one generated
   run**, to measure that noise before choosing X?
5. **Where run files live.** `eval-ci` writes to `.claude/dev/reports/` today, and
   `.gitignore` ignores `*.json` there ("ephemeral"). That suits ordinary runs.
   The **baseline** is different: README badges and every later comparison
   point at it, so it should be committed. The proposal: runs stay in
   `.claude/dev/reports/`, and the run chosen as baseline is copied to a committed
   path by a deliberate step.

## Next step
- [x] Author picks an option and answers the DEFINE questions: **Option 2**, and
      the recommendations on Q1, Q3, Q4 and Q5 (2026-10-05). Q2 had no
      recommendation here, so DEFINE proposes one and leaves it open
- [x] DEFINE.md written
