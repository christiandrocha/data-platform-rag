# Golden set for RAGAS evaluation

50 questions across three target intents (decision, architecture, comparison)
plus adversarial questions that MUST fire the out-of-scope fallback.

Format: YAML per question in `evaluation_questions.yml`.

## Schema

```yaml
- id: q001
  provenance: human               # human | llm — see below
  voice: technical                # recruiter | technical — see below
  intent: decision | architecture | comparison | out-of-scope
  question: "What is the question?"
  expected_answer: "Ground truth answer"
  expected_source_paths:          # {project, path} objects — project is mandatory
    - project: sdd-kafka-snowflake-2
      path: docs/adr/ADR-XXXX.md  # Must be in the retrieval top-k
    - project: sdd-kafka-databricks
      path: README.md
```

There is no `should_fallback` field. Whether a question must fire the fallback
is **derived** from `intent == "out-of-scope"`. Two fields encoding one fact
drift apart; a derived one cannot. Consumers call
`scripts/validate_golden_set.py::should_fallback(q)`.

`project` must be one of the two corpus repos, mirroring
`data_platform_rag.contracts.SourceProject`. It is mandatory rather than
inferred: both repos carry a `README.md` and a `docs/adr/` tree, so a bare path
does not identify a document. `scripts/validate_golden_set.py` rejects entries
without it, and also enforces the distribution below once the set reaches 50.

## Provenance

Every question declares `provenance: human | llm`.

ADR-011 Commitment 1 reserves question authorship to a human. The field exists
because that ADR also pre-approves **retreat A3**, under which an LLM may propose
`architecture` questions while a human writes all `decision`, `comparison`, and
`out-of-scope` ones. When A3 is invoked:

- Human questions are written and committed **before** the LLM proposes any.
  Reading LLM phrasings first contaminates the human author's own phrasing.
- Layer 2 audits run separately per stratum, so contamination rates stay
  comparable rather than pooled.
- RAGAS results are reported per stratum. The human/LLM delta becomes a measured
  number rather than an assumed bias.

The point of the field is to make the bias **measurable**, not to hide it.

## Voice

Every question declares `voice: recruiter | technical`.

The target audience asks in two different ways (dev log #23):

- **recruiter** — no technical background; a short question built around a
  keyword from the job posting, expecting confirmation and where it was used.
- **technical** — a hiring manager or interviewer asking why a decision was
  taken and what was traded off.

Both voices are written within the same intents and the same distribution.
RAGAS results are reported per voice, so a system that serves one audience and
fails the other shows up as a gap instead of an average.

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
- Adversarial questions must be plausible **and verified absent**. Grep every
  candidate against the in-corpus files of both repos (`docs/adr/`, `README.md`,
  `contracts/`, `macros/`) before it enters the set. The plausible-looking ones
  are often present: "Delta Live Tables" was the original example here, and it
  turns out to be discussed in two databricks ADRs as a rejected alternative —
  it is a legitimate `decision` question, and would have failed
  `fallback_accuracy` on every run.
- Topics verified absent from both corpora on 2026-09-14: Apache Iceberg, Hudi,
  Flink, Airflow, Great Expectations, Trino, Presto, ClickHouse, Monte Carlo,
  Atlan, Collibra, DuckDB. Re-verify before use — the corpora change.
- Update requires an ADR if count exceeds 100 or metric weighting changes
