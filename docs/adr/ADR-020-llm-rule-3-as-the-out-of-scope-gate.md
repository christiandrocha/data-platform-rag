# ADR-020 — The LLM's rule 3 as the out-of-scope gate, measured

**Status**: Planned — 2026-10-02. Measurement pending an API key
**Date**: 2026-10-02

> Written before any API call. The Context, Decision and Consequences sections
> will be kept exactly as written when the Outcome is added. They are the
> prediction the outcome is judged against, as in ADR-015, ADR-017, ADR-018 and
> ADR-019.

## Context

ADR-019 measured that cosine similarity cannot tell in-scope questions from
out-of-scope ones (lowest in-scope top similarity 0.6040, highest out-of-scope
0.7360), and superseded ADR-006's score gate. Since then the LinkedIn fallback is
sent by the LLM, under rule 3 of the system prompt (`SYSTEM_PROMPT_VERSION`
v1.1.0): "If the retrieved context does not directly answer the question, return
the exact fallback string below."

That is now the only out-of-scope gate. AGENTS.md makes the fallback a product
boundary ("Never remove the out-of-scope fallback"), and nothing measures whether
it fires. ADR-006 rejected exactly this design once, on the grounds that LLMs
fabricate under weak context. ADR-019 adopted it because the alternative was
measured to fail, not because this one was measured to work.

The gate can fail in two directions, with two different victims:

- **A miss.** An out-of-scope question gets an answer. The visitor reads a
  fabricated answer that looks grounded. This is ADR-006's fear.
- **A false fallback.** An in-scope question gets the fallback. The visitor hits a
  dead end. Rule 3 invites this too: "do NOT assemble a partial answer out of
  loosely related chunks".

The golden set has 5 out-of-scope questions. On 5, one miss moves a rate by 20
points.

## Decision

**Measure rule 3 once, with two numbers judged separately, against a rule fixed
here before any call.** The pipeline under test, the classification and the
populations are DEFINE's (`.claude/sdd/features/llm-fallback-eval/DEFINE.md`):

- **Pipeline:** `pipeline.retrieve(question, top_k=settings.rerank_top_k)` with
  default collections, the context format `CONTEXT_FORMAT_VERSION` v1.0.0,
  `SYSTEM_PROMPT` v1.1.0, model **`claude-sonnet-4-6`**, temperature 0, no extended
  thinking, `max_tokens` 1024. Retrieval runs once per question and its chunks are
  reused across runs.
- **Classes**, from the output text alone, checked in this order: **empty** if,
  trimmed, it is the empty string (DEFINE Amendment 1). **Fallback** if, trimmed,
  it equals `FALLBACK_MESSAGE`. **Non-compliant refusal** if it is not exact but
  contains `linkedin.com/in/christiandrocha`. **Answer** otherwise. In-scope
  false fallbacks are fallback, non-compliant and empty outputs. An out-of-scope
  question is a miss unless its class is fallback.
- **Out-of-scope population: 35.** The golden set's 5 (q005, q047–q050) plus 30
  new questions in `docs/golden-set/out_of_scope_questions.yml`, disjoint from the
  golden set, written under ADR-016's terms. Every one carries a `band`: 15
  adjacent-but-absent, 6 personal, 7 off-domain, 7 adversarial (the golden 5 are
  3 adjacent, 1 off-domain and 1 adversarial). The mix weights the band where
  ADR-019 found similarity highest. It is a choice, not a model of visitor
  traffic, and it makes B1 stricter.
- **In-scope population: 45**, the golden set's in-scope questions.
- **3 runs.** `make fallback-eval` writes one artifact holding all three, and prints
  numbers, not a verdict.

The rule, copied byte for byte from DEFINE. Before the measurement it is checked
identical with:

```bash
awk '/^\*\*Accepted \(rule 3 is the gate, as written\)\*\*/{p=1} p{print} /^change\.$/{if(p)exit}' FILE
```

run on both files, with the two outputs compared by `diff`.

**Accepted (rule 3 is the gate, as written)** only if both hold in **every** run:

- [ ] **B1.** Out-of-scope recall is **≥ 95%**: with 35 out-of-scope questions,
      at least **34/35**, so at most 1 miss per run.
- [ ] **B2.** In-scope false-fallback rate is **≤ 10%**: at most **4/45** per run.

**Rejected** if either fails in any run:

| reading | outcome |
|---|---|
| B1 and B2 hold in every run | **Accepted.** ADR-006's fear is answered for this model and prompt version. README Known Gaps loses the "unmeasured" bullet |
| B1 fails (the LLM answers out-of-scope questions) | **Rejected.** The next ADR replaces the string contract with structured output (BRAINSTORM Option 3), then re-measures under the same rule |
| B1 holds, B2 fails (it over-refuses) | **Rejected.** The next ADR revises rule 3's wording as a new prompt version, then re-measures under the same rule |
| any **non-compliant refusal** on an out-of-scope question | Counted as a miss under B1, and listed by id in the Outcome, as evidence for structured output |

The thresholds are not re-fitted after the reading, and a failed reading is not
re-run until it passes. A re-measurement belongs to the next ADR, after its
change.

**Pre-registered predictions, not deciding** (from DEFINE):

- P1. The misses concentrate in the **adjacent-but-absent** band, where ADR-019
  found similarity highest (q005 Flink, q047 Airflow).
- P2. The prompt-extraction and off-domain questions (q049, q050-like) all get the
  fallback.
- P3. At least one in-scope **comparison** question gets a false fallback, because
  a comparison's context may carry only one project's chunks.

## Consequences

**The reading holds for one model and one prompt version.** A change to the
model, `SYSTEM_PROMPT`, the context format, `rerank_top_k` or the temperature is a
change to what was measured. The artifact records each of them, and a hash of the
system prompt and of both question files. A later change re-measures under this
rule.

**`claude-sonnet-5-5` is out of scope of this reading.** It rejects a non-default
temperature, and its safety classifiers can end a turn with
`stop_reason: "refusal"`, which the three classes do not cover. Moving to it means
an ADR that fixes both first.

**The classes read only the text.** An output that stops for a reason other than
`end_turn` is listed by id in the artifact and the Outcome, and is classified as
its text says. An empty output is its own class and counts against B2 (DEFINE
Amendment 1, decided before any call).

**Known limitation: a refusal without the link reads as an answer.** "I don't have
information on that", with no LinkedIn URL, on an in-scope question, is classified
as an **answer**, so B2 can understate the dead ends. Exact matching cannot see it,
and a judge is outside this design. The artifact keeps every output's text, so the
in-scope answers can be read for it. A reading that finds such outputs records
them in the Outcome, without re-classifying them.

**A failed call is not a reading.** If a call still fails after the SDK's
retries, or the run is interrupted, the artifact is written with
`complete: false` and its reason, and **no number is computed for it**. The rule
does not read it, and the measurement is run from the start. That is not a re-run
"until it passes": no reading happened. To keep it that way, **the Outcome lists
every artifact `make fallback-eval` produced, incomplete ones with their reason.**

**Generation now exists, as an evaluation path.** `generation/client.py` is the
first code that calls Claude for an answer. It writes no `query_log` row and no
Langfuse trace. The product path wraps it when the UI is built.

**The cost estimate gets a measured replacement.** The artifact records input and
output tokens per call. The KB's per-query figure is an estimate, and this
measurement is the first real number for it.

**The new set is curated by the same model family that answers it.** ADR-016's
negative applies again, with the same mitigation: the author reads every probe
list and the Layer 1 grep result, and Layer 2 audits run when a key exists.

## Alternatives considered

**1. Keep only the golden set's 5 out-of-scope questions.** One miss is 20
points. No threshold can pass or fail honestly on 5.

**2. Build RAGAS first and read `fallback_accuracy`.** One pooled number, 45
in-scope against 5 out-of-scope, dominated by the in-scope side, and an LLM judge
per metric. It hides the two failure directions this ADR separates.

**3. Structured output now** (`{"answerable": bool, "answer": …}`, with the code
sending the fallback). Detection becomes a boolean, and paraphrase becomes
impossible. It also changes the prompt's contract and measures a different gate
from the one ADR-019 chose. It is the B1-fails branch, not the starting point.

**4. Claude Sonnet 5.5.** Rejected by the author on 2026-10-02. It reopens DEFINE's
temperature decision and adds an output class. See Consequences.

**5. A single run.** Temperature 0 is not strictly deterministic. One lucky run
could pass the rule, so the worst of 3 decides.
