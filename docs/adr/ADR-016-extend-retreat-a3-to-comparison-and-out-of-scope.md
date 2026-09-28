# ADR-016 — Extend retreat A3 to comparison and out-of-scope questions

**Status**: Accepted — 2026-09-28, by the author
**Date**: 2026-09-28
**Amends**: ADR-011 (retreat A3, and Commitment 1 for the remaining eight questions)

## Context

ADR-011 Commitment 1 reserves question authorship to a human. Its pre-approved
retreat A3 lets an LLM write `architecture` questions only. A3 was invoked on
2026-09-28 (ADR-011 amendment), and q026–q042 are LLM-written.

The set stands at 42/50: `decision` 22/22 and `architecture` 18/18 are
complete. Eight remain, 4 `comparison` and 4 `out-of-scope`, two of each in the
recruiter voice (DESIGN T4). ADR-011 kept both intents human for different
reasons. For comparison, a cross-project claim is easy to get subtly wrong.
For out-of-scope, the Layer 2 auditor is the same model family that would be
writing the question, so a paraphrase it misses as a writer it can also miss
as an auditor.

The author has declined to write more questions. The options are to stop at 42,
to extend A3, or to leave eight slots open indefinitely.

## Decision

Extend A3 to the eight remaining questions. They are LLM-written, carry
`provenance: llm`, and are approved by the author per batch, exactly as under
the A3 amendment. Every check that already binds these intents still applies,
and none is relaxed:

1. **Comparison:** each question cites at least one source from each project,
   which `validate_golden_set.py` already enforces. Every claim about either
   project is checked against its own cited file, not against the other.
2. **Out-of-scope:** `expected_answer` is null and the fallback must fire.
   Every question carries `contamination_probes` and `grep_verified`, and must
   pass `make verify-adversarials` (Layer 1, literal) before it is committed.
3. **Out-of-scope, Layer 2:** the Opus audit (`make audit-adversarials`) still
   runs on each one, but because the writer and the auditor share a model
   family, **the author reads each probe list and the grep result**, not only
   the audit verdict. That human read is the check that is independent of the model.
4. The topics already reserved in INTERVIEWER_THEMES are used as they are:
   Airflow and Iceberg (adjacent but absent), one trivially off-domain question,
   and one prompt-extraction attempt. The comparison pairs come from
   `make golden-set-next-comparison-pair`, the seeded walk.

## Consequences

**Positive:** the set reaches 50, which is the size ADR-008's regression gate
and the Section 7 publication gates are defined against. Coverage warnings stop.

**Negative:**

- **The human/LLM comparison becomes confounded with intent.** At 50 questions
  the split is 25 human and 25 LLM, but the human stratum is almost entirely
  `decision` (22 of 25) and the LLM stratum is `architecture`, `comparison` and
  `out-of-scope`. A Context Recall gap between the two strata cannot be put
  down to authorship alone, because the intents differ too. A3's promise that
  "the delta becomes a measured number" survives only within an intent, and
  only `architecture` (1 human and 17 LLM) and `comparison` (1 and 4) have both
  strata, too few to be conclusive. This is recorded as a known gap in
  `docs/golden-set/README.md`.
- **Out-of-scope loses an independent author.** Rule 3 narrows the gap but does
  not close it. If an LLM-written adversarial turns out to be discussed in the
  corpus in different words, `fallback_accuracy` fails on every run. That is at
  least visible, not silent.
- Every metric reported on this set should be read per provenance and per
  intent, never pooled.

## Alternatives considered

- **Stop at 42.** Rejected. The distribution targets and the gates are defined at
  50. Changing them would be a second ADR, and it would leave `comparison` and
  `out-of-scope` with one question each, too few to score.
- **Extend A3 to comparison only, and keep out-of-scope human.** This is the
  cleanest option on independence, and it is the one to fall back on if the
  author is willing to write four one-line questions, since out-of-scope answers
  are the fixed fallback. Rejected only because the author has declined to
  write more.
- **Rebalance, writing fewer comparison and out-of-scope and more of the
  complete intents.** Rejected. It moves the ruler mid-curation (ADR-011, "a
  moving ruler") to save eight questions.
