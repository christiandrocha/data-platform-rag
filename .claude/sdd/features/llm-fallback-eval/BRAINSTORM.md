# BRAINSTORM: Measuring the LLM's out-of-scope fallback (rule 3)

> Free exploration. No commitments. No commits from this file alone.

## Date
2026-09-30

## Prompt

ADR-019 measured that no cosine threshold separates in-scope from out-of-scope
questions, and moved the fallback onto the LLM. Under system-prompt rule 3, the
LLM returns the fixed LinkedIn message when the retrieved context does not answer
the question. That is now the project's only out-of-scope gate, and it is
unmeasured. ADR-006 rejected relying on the LLM alone because "LLMs still
fabricate under 'context is weak' prompting". This feature puts a number on
whether that fear holds.

Constraints as they stand (checked 2026-09-30):

- **No API key and no `anthropic` package in the venv.** It is declared in
  `pyproject.toml` but not installed. The author chose (2026-09-30) to **prepare
  everything now and measure later**: the measurement is the one step that waits
  for a key.
- **Generation does not exist.** `generation/` holds only `prompt.py` (system
  prompt v1.1.0 and `FALLBACK_MESSAGE`). There is no client and no context
  assembly.
- **`settings.llm_model` is `claude-sonnet-4-6`.** Whether that id is current is
  checked in DESIGN, against the Claude API reference, not from memory.
- **The golden set has 5 out-of-scope questions** (q005, q047–q050). ADR-019 used
  them for a separability test. For a rate, 5 is too few: one miss moves the rate
  by 20 points.
- **`make eval` is a stub.** `RAGASReport.fallback_correct` and
  `RAGASAggregate.fallback_accuracy` exist as contracts with nothing behind them.

## What "the fallback works" means: two numbers, not one

- **Out-of-scope recall:** of the questions that should get the fallback, the
  share that does. A miss is the failure ADR-006 feared: the LLM answers from
  general knowledge.
- **In-scope false-fallback rate:** of the questions the corpus answers, the share
  that wrongly gets the fallback. Rule 3 also says "do NOT assemble a partial
  answer out of loosely related chunks", so an over-cautious LLM would turn
  answerable questions into dead ends.

A single `fallback_accuracy` mixes both, and with 45 in-scope against 5
out-of-scope it would be dominated by the in-scope side. Both are reported, and
each is judged separately.

## Options considered

### Option 1: A minimal generation step plus a dedicated fallback evaluation

Build the smallest real generation step and a script that runs it over labelled
questions:

- `generation/client.py`: retrieve, keep the top `settings.rerank_top_k` chunks,
  assemble the context, call Claude with `SYSTEM_PROMPT`, and return the text.
- **Fallback detection is an exact match** on `FALLBACK_MESSAGE`, after trimming
  whitespace. Rule 3 says "return the exact fallback string … VERBATIM", so a
  paraphrased refusal counts as *non-compliant*, recorded separately and not
  silently counted as a fallback.
- `make fallback-eval`: every golden question plus a **new out-of-scope
  evaluation set** (below). It writes an artifact with the model id, prompt
  version and snapshot, plus per-question outputs. Tests use a stub client, so
  nothing calls the API until the measurement.
- A decision rule fixed in DEFINE, before any call (as ADR-017, ADR-018 and
  ADR-019 did).

- **Pros**
  - It measures the one gate the project now has, and nothing else.
  - The code is the start of the real generation path, not throwaway.
  - Everything except the run can be built and tested without a key.
- **Cons**
  - Answer quality (faithfulness, relevance) stays unmeasured. That is RAGAS's
    job.
  - LLM output is not strictly deterministic even at temperature 0. The rule has
    to say how many runs make "the reading".

### Option 2: Build `make eval` with RAGAS first, and read `fallback_accuracy` from it

- **Pros**
  - It fills the contracts that already exist, and the README badges.
- **Cons**
  - Much bigger. RAGAS needs an LLM judge for every metric, so it costs more and
    is harder to make deterministic.
  - `fallback_accuracy` alone hides the two-numbers problem above.
  - It delays the one measurement ADR-019 left open.

### Option 3: Structured output for the gate (`{"answerable": bool, "answer": …}`)

The LLM returns JSON validated by pydantic, with the one-shot repair retry AGENTS.md
prescribes, and the code sends `FALLBACK_MESSAGE` itself.

- **Pros**
  - Detection is a boolean, not a string match, and the fallback text can never be
    paraphrased.
- **Cons**
  - It changes the system prompt's contract (rule 3 says "return the exact
    string"), which is a new prompt version and arguably its own ADR.
  - It measures a different gate from the one ADR-019 chose. Measure first, and
    change the mechanism if the measurement says so.

### Option 4: Keep the golden set's 5 out-of-scope questions only

- **Pros**
  - No new curation.
- **Cons**
  - One miss is 20 points. A rate on 5 questions cannot pass or fail anything
    honestly.

## The out-of-scope evaluation set (needed by Options 1 and 3)

A separate file, disjoint from the golden set, so the golden set keeps grading and
this set only measures rule 3.

- **Bands**, taken from ADR-016's out-of-scope design:
  - adjacent-but-absent: real data-engineering topics the corpus does not cover
    (Flink, Iceberg, Airflow-style questions), where ADR-019 showed similarity is
    highest
  - personal or career questions about the author
  - off-domain
  - adversarial or prompt-injection questions
- **Authorship:** LLM-written under ADR-016's retreat A3 terms (`provenance: llm`,
  author approval, Layer 1 grep probes via `verify-adversarials`). Layer 2 audit
  when a key exists.
- **Size:** fixed in DEFINE. A sketch: about 30, so one miss moves the rate by
  about 3 points instead of 20.

## Discarded early

- **Measuring with the retrieval-score gate on as a baseline.** ADR-019 removed it
  for cause, and there is nothing to compare against.
- **Asking the LLM to self-rate confidence.** It is another uncalibrated number,
  the same problem ADR-019 closed.
- **Running without retrieval** (asking the LLM directly). It is not the
  pipeline. Rule 3 is about "the retrieved context".

## Emerging preference

**Option 1, with the new out-of-scope evaluation set.** It is the smallest thing
that answers ADR-019's open question, it is buildable and testable without a key,
and the code it adds is the real generation path. Option 3 stays the candidate if
the measurement shows paraphrased or partial refusals.

**For DEFINE to fix before any call** (with the author):

- the two thresholds: out-of-scope recall ≥ ?, and in-scope false-fallback ≤ ?
- the out-of-scope set's size and bands
- the number of runs and the temperature (a sketch: temperature 0, 3 runs,
  reported per run, with the rule reading the worst run)
- what each outcome commits the project to (for example: pass → rule 3 is the
  gate and ADR-006's fear is answered; fail → structured output (Option 3) or a
  prompt revision, as a new ADR)
- how a paraphrased refusal counts

**What would change my mind:** if the author prefers to wait for RAGAS and
measure everything at once, Option 2. The cost is that the one open question stays
open longer.

## Next step

- [x] Author confirms Option 1 (2026-09-30)
- [ ] Write DEFINE: thresholds, set size, runs, outcomes, paraphrase handling
