# Golden set for RAGAS evaluation

50 questions across three target intents (decision, architecture, comparison)
plus adversarial questions that MUST fire the out-of-scope fallback.

Format: YAML per question in `evaluation_questions.yml`.

## Schema

```yaml
- id: q001
  intent: decision | architecture | comparison | out-of-scope
  question: "What is the question?"
  expected_answer: "Ground truth answer"
  expected_source_paths:
    - docs/adr/ADR-XXX-name.md   # Must be in retrieval top-5
    - README.md
  should_fallback: false          # true only for out-of-scope questions
```

## Distribution target

| Intent | Count | Purpose |
|--------|-------|---------|
| decision | 22 | Cover the 21 ADRs across the two corpus projects |
| architecture | 18 | Cover Snowflake and Databricks READMEs, contracts, macros |
| comparison | 5 | Cross-project questions — how the two projects diverge on the same problem |
| out-of-scope | 5 | Force fallback — MUST return the LinkedIn redirect |
| **Total** | **50** | |

## Why this `intent` set is not `contracts.Intent`

The golden set's `intent` field labels the *question category being tested*.
It deliberately does not mirror `data_platform_rag.contracts.Intent` one for one:

- **`hybrid` is absent here.** It is a valid runtime value of `contracts.Intent`,
  but it is the classifier's semantic fallback when a query does not resolve to
  a target category — not a category questions are authored against. A
  golden-set question labelled `hybrid` would be exercising the fallback path by
  accident rather than by design. `scripts/validate_golden_set.py` rejects it.
- **`out-of-scope` is golden-set-only.** It labels expected *behaviour* (the
  fallback must fire), not a value the intent classifier can ever return.

Anything mapping these two enums onto each other should treat them as separate
vocabularies that happen to share two members.

## Curation rules

- Questions must sound natural — no "According to ADR-007..."
- Adversarial questions should be plausible ("What did Christian decide about
  Delta Live Tables?" — related but not in corpus)
- Update requires an ADR if count exceeds 100 or metric weighting changes
