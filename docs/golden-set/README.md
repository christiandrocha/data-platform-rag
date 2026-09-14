# Golden set for RAGAS evaluation

50 questions across two intents (decisions, architecture, hybrid) plus
adversarial questions that MUST fire the out-of-scope fallback.

Format: YAML per question in `evaluation_questions.yml`.

## Schema

```yaml
- id: q001
  intent: decision | architecture | hybrid | out-of-scope
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
| decisions | 22 | Cover the 21 ADRs across the two corpus projects |
| architecture | 18 | Cover Snowflake and Databricks READMEs, contracts, macros |
| hybrid | 5 | Cross-project questions requiring both collections |
| out-of-scope | 5 | Force fallback — MUST return the LinkedIn redirect |
| **Total** | **50** | |

## Curation rules

- Questions must sound natural — no "According to ADR-007..."
- Adversarial questions should be plausible ("What did Christian decide about
  Delta Live Tables?" — related but not in corpus)
- Update requires an ADR if count exceeds 100 or metric weighting changes
