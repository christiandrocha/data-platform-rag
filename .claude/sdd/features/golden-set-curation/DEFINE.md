# DEFINE: Golden set curation

> Build the 50-question evaluation set that every downstream quality decision in this project will be measured against.

## Metadata

| Field | Value |
|-------|-------|
| Feature | golden-set-curation |
| Date | 2026-09-14 |
| Author | christiandrocha |
| Status | Ready for Design |
| Clarity Score | 14/15 |

## Problem statement

`docs/golden-set/evaluation_questions.yml` holds 5 of its 50 questions, and
nothing in this project can be measured until it holds all 50. ADR-004's
embedding decision rule, ADR-005's reranker A/B, ADR-008's CI regression
threshold, and all four Section 7 publication gates are all scored against this
one file.

The acute risk is not slowness — it is that a **biased golden set yields
confidently wrong numbers**. If the questions are written in the vocabulary of
the corpus, retrieval scores inflate and every downstream metric looks healthy
while measuring nothing. No later phase can detect this, because the golden set
is the thing all later phases trust.

## Users

| User | Role | Pain point |
|------|------|-----------|
| Christian (author) | Writes the questions and their ground-truth answers | Has no instrument to tell whether a retrieval change helped or hurt; currently choosing parameters by intuition |
| Christian (operator) | Runs `make eval`, reads RAGAS output | Cannot promote ADR-004/005/008 from Planned to Accepted without real numbers, which blocks v1 publication |
| The RAG's end users | Ask questions of the deployed system | Represented only by proxy. Whatever bias the golden set carries becomes an unexamined assumption about what they will ask |
| CI (ADR-008) | Fails the build on metric regression | With too few questions, a 0.05 metric drop is noise, not signal — the regression gate cannot be calibrated |

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | 50 questions at the 22/18/5/5 distribution, validator-enforced |
| MUST | Every question authored by a human; no LLM-generated question text (decision A4) |
| MUST | Every `expected_answer` grounded clause-by-clause in a cited source (decision D2) |
| MUST | Coverage: all 21 corpus ADRs (12 snowflake + 9 databricks) cited by at least one question |
| MUST | The 5 adversarials span a difficulty gradient, including exactly one prompt-extraction attempt (decision C3, Section 7 non-negotiable) |
| MUST | Each `comparison` question cites at least one source from each project |
| SHOULD | An LLM audit pass for coverage gaps and phrasing contamination — auditor role only, never author |
| SHOULD | Seed the set from real provenance (questions Christian was actually asked) where such questions exist |
| SHOULD | A coverage matrix artefact (ADR x intent) checked into the repo, not held in someone's head |
| COULD | Mechanised grounding audit (decision D4) replacing the manual D2 pass |
| COULD | `expected_source_paths` verified against a live corpus clone |
| COULD | A `provenance` field, required only if the A3 retreat is taken |

## Success criteria (measurable)

- [ ] Exactly **50** questions; `python scripts/validate_golden_set.py` exits 0 with **zero warnings**
- [ ] Distribution is exactly **22 / 18 / 5 / 5** (decision / architecture / comparison / out-of-scope)
- [ ] **100%** of in-scope questions (`intent != "out-of-scope"`) carry at least one `expected_source_paths` entry and a non-empty `expected_answer`
- [ ] **21 of 21** corpus ADRs are cited by at least one question
- [ ] **0** questions contain a verbatim span of **8 or more consecutive words** copied from any of their cited sources (contamination check)
- [ ] The 5 adversarials cover at least **3** distinct difficulty bands, and exactly **1** is a prompt-extraction attempt
- [ ] **5 of 5** `comparison` questions cite at least one source from **each** of the two projects
- [ ] **100%** of `expected_answer` clauses have a recorded grounding reference in a cited source

## Acceptance tests

- [ ] `python scripts/validate_golden_set.py` exits 0 and prints no `!` warning lines
- [ ] A coverage report (`make golden-set-check` or a new target) lists all 21 ADRs, each with a question count of at least 1, and fails if any is 0
- [ ] A contamination check reports 0 questions with an 8-word verbatim overlap against their cited sources
- [ ] Given the adversarial subset, a reviewer can name which difficulty band each of the 5 occupies, and exactly one is the prompt-extraction case
- [ ] Given any in-scope question, its `expected_answer` can be traced clause-by-clause to text in a file named in its `expected_source_paths`
- [ ] Given a question whose `expected_source_paths` names a project outside `SourceProject`, the validator exits 1

## Non-goals

Explicitly out of scope for this feature:

- **Running RAGAS.** Scoring needs `corpus-indexing` and the retrieval pipeline, neither of which exists. This feature produces the instrument, not a reading from it.
- **Choosing the embedding model.** ADR-004's benchmark consumes this set; it is a separate piece of work that starts when this one finishes.
- **Tuning `fallback_threshold`.** The adversarial gradient is designed so this becomes tunable later. Tuning it now would be fitting a parameter to five questions.
- **Verifying `expected_source_paths` against a live clone.** Listed as COULD; it depends on a corpus-clone workflow that conflicts with the AGENTS.md transient-clone rule and needs its own design.
- **Expanding beyond 50 questions.** Section 5E fixes the count. The golden-set README already requires an ADR to exceed 100.
- **Writing the questions themselves.** This DEFINE specifies what makes a question acceptable; authoring happens in BUILD.

## Open questions

- [x] ~~Does `should_fallback: true` imply `intent: out-of-scope`?~~ **RESOLVED 2026-09-14 by removing the field.** The boolean is derived from `intent == "out-of-scope"` rather than stored and cross-checked. Reconsider only if a real case appears for an in-scope question that must still fall back.
- [ ] **Where does the coverage matrix live?** A checked-in file (`docs/golden-set/coverage.md`), or generated on demand by the check target? Generated is harder to review; checked-in drifts.
- [ ] **Is the contamination check a script or a review step?** An 8-word overlap test is mechanical and cheap, but it needs the corpus available locally — the same clone-workflow problem as the COULD above.
- [ ] **What counts as one of "the 21 ADRs"?** The databricks project has a superseded ADR-003 (reversed by ADR-007). Does a question about the reversal satisfy coverage for both, or does each need its own?
- [ ] **How is grounding recorded?** D2 requires a traceable clause-to-source mapping, but the YAML schema has no field for it. A side file, a comment convention, or a new optional field?

## Clarity Score self-check

Rate each 1-5. Total must be >= 12/15 to proceed to Design.

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | The deliverable is a countable artefact with a fixed target, and the failure mode (contamination bias) is named and given a mechanical test rather than left as a worry |
| Users are named and their pain is real | 4 | Christian's two roles are concrete and the pain is present-tense. Deliberately not a 5: the end users exist only by proxy, and two of the four rows (CI, the benchmark) are consumers rather than people — the dimension is being stretched to cover them |
| Success criteria include numbers | 5 | All eight criteria are numeric and independently checkable; six are automatable today |
| **Total** | **14/15** | Above the 12/15 gate |
