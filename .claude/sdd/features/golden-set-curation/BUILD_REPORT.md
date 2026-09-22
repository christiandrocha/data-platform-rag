# BUILD REPORT: Golden set curation — the instrument's tooling

## Metadata

| Field | Value |
|-------|-------|
| Feature | golden-set-curation |
| DEFINE | [DEFINE.md](./DEFINE.md) |
| DESIGN | [DESIGN.md](./DESIGN.md) — Approved 2026-09-22 |
| ADR | [ADR-011](../../../../docs/adr/ADR-011-golden-set-curation.md) — Accepted 2026-09-14 |
| Themes | [INTERVIEWER_THEMES.md](./INTERVIEWER_THEMES.md) |
| Start date | 2026-09-14 (tooling slice 1), resumed 2026-09-22 |
| End date | 2026-09-22 (tooling); the 45 questions are not written |
| PR | pending |

## Outcome in one paragraph

**The tooling is finished; the instrument is not.** The five items the revised
DESIGN listed as TO BUILD are built: grounding checks, the comparison rule,
coverage that warns while the set is incomplete, the mechanical contamination
check, and the integration tests over the real files. Writing the questions
stays with the author, and the golden set still holds **5 of 50**. Building the
checks also produced the first real finding: reading the cited sources for the
four existing answers showed that **three of them claim something the source
does not support**, which is the "wrong ground truth" failure ADR-011 named and
which no metric would have surfaced.

## What was built

| File | Change | Slice |
|---|---|---|
| `scripts/validate_golden_set.py` | `check_grounding` (attestation, entry shape, claim is a span of the answer, quote comes from a cited source, digit-bearing words need a quote) and `high_risk_tokens` | 2026-09-22 |
| same | `check_comparison_sources`: a `comparison` question cites at least one source from each project (DEFINE MUST) | 2026-09-22 |
| `scripts/golden_set_coverage.py` | `report_exit`: uncovered ADRs warn below 50 questions, fail at 50; `TARGET_TOTAL` imported from the validator so 50 is defined once | 2026-09-22 |
| `scripts/check_contamination.py` | **New.** 8-word verbatim overlap between a question and its cited sources; grounding quotes verified against the files; cited paths verified to be in-corpus | 2026-09-22 |
| `Makefile` | `golden-set-check` also runs the contamination check, with `--skip-without-snapshot` | 2026-09-22 |
| `docs/golden-set/evaluation_questions.yml` | q003 carries a `grounding` entry for `ADR-0030` | 2026-09-22 |
| `tests/unit/test_validate_golden_set.py` | +15 tests (12 grounding, 3 comparison) | 2026-09-22 |
| `tests/unit/test_golden_set_coverage.py` | **New.** 3 tests on the exit rule | 2026-09-22 |
| `tests/unit/test_check_contamination.py` | **New.** 8 tests: tokenising, 8-word boundary, quote matching, the skip rule | 2026-09-22 |
| `tests/integration/test_golden_set_files.py` | **New.** 5 tests running the scripts as `make` runs them, over the real files | 2026-09-22 |
| `scripts/validate_golden_set.py`, `golden_set_coverage.py`, `verify_adversarials.py`, `audit_questions.py`, `corpus_inventory.yml` | Built earlier, on 2026-09-14 (`99ec2d7`, `51cf64c`, `b2f33e1`) and described by this DESIGN only after the 2026-09-22 revision | 2026-09-14 |

`make test`: 182 → **213**. `make golden-set-check` exits 0 while the set is
incomplete, and names what is missing.

## What deviated from design

- **Item 1 split in two, and half of it is not mine to do.** `grounding_verified`
  is the author's attestation that the answer was checked against the source.
  Writing `true` on four questions nobody had re-read would have fabricated the
  verification the field exists to record. The checks shipped; the attestation
  is the author's, and q003's `grounding` entry shipped without it.
- **The contamination script does not skip on a missing snapshot; the make
  target does.** DESIGN said the script skips loudly with exit 0. Every other
  corpus consumer raises instead, because an absent corpus passes every check
  vacuously (ADR-012, dev-log #16). The script therefore fails, and
  `--skip-without-snapshot` — used only by `make golden-set-check` — prints a
  `SKIPPED` line and exits 0. Same intent, without an exception to ADR-012.
- **Tokenising drops punctuation as well as case and whitespace.** DESIGN said
  lowercase and collapse whitespace. A comma should not hide a copied span.
- **The contamination pass also verifies grounding quotes and cited paths.** The
  validator cannot: it never reads the corpus. Both were open items — the quote
  check from item 1, the path check a DEFINE COULD — and the script already has
  the cited files open.
- **Only the question text is compared to the sources, not `expected_answer`.**
  An answer is supposed to restate its source; a question is not.
- **One span per source is reported, with a count.** Overlapping 8-grams would
  otherwise print dozens of near-identical lines.
- **`TARGET_TOTAL` is imported from `validate_golden_set`**, so the two scripts
  cannot disagree about 50. ruff then required the import to sit in the same
  block as `yaml`; applied with `ruff check --fix`.
- **The scripts only run through `make`** (or with `PYTHONPATH=.`), because that
  is where the package lands on the path. Found while running the new script by
  hand; it matches how the existing corpus scripts already work, so it was
  recorded rather than changed, and the integration test now runs them that way.

## Measurement

Against the real corpus snapshot `/tmp/dpr-corpus-20260922-180745`
(`sdd-kafka-databricks@f1295df9`, `sdd-kafka-snowflake-2@82a2e269`, 47 files):

| Check | Result |
|---|---|
| 8-word verbatim overlap, 4 in-scope questions × their cited sources | **none** |
| grounding quotes found in their source | 1 of 1 (q003) |
| cited paths that are in-corpus files | 6 of 6 |
| `validate_golden_set.py` | exit 0, with per-question warnings for the missing attestations |
| `golden_set_coverage.py` | exit 0, 3/21 ADRs covered, 18 uncovered |

### The finding: three of four expected answers are not supported by their source

Found by reading the cited documents while building the grounding check. No
metric would have reported it, and it is the third failure mode of ADR-011's
Context section.

- **q001** claims Streaming was chosen after *"confirming v4 connector managed
  pipes met the latency target"*. ADR-0029 states no latency target; managed
  pipes avoid *"needless ownership"*, and the recorded reasons are row-level
  commits (which make ADR-0019's gate possible), the measured cost
  (`0.0005 credits`), and leaving a deprecated generation.
- **q002** attributes the Unity Catalog lineage argument to ADR-007 and says it
  *"supersedes ADR-003"*. That argument belongs to ADR-006, which reversed
  ADR-003; ADR-007 supersedes **ADR-006's exclusions** and states the goal is
  *"no longer 'fix a lineage bug.' It's architectural consistency"*. The
  question is answered by both ADRs and cites only 007.
- **q003** is supported. Verified against ADR-0030.
- **q004** says Databricks enforces schema evolution through YAML contracts
  validated by `test_contracts.py`, implying a different mechanism from
  Snowflake's. The Databricks README's own stack table reads *"Confluent Schema
  Registry | Avro + BACKWARD compatibility"* — the same mechanism —
  `test_contracts.py` checks contract consistency rather than compatibility, and
  the README lists *"Schema Registry BACKWARD compatibility enforcement in CI"*
  as a next step. q004 has no digit-bearing word, so the mechanical floor would
  not have flagged it; this is the judgment layer's case.

**This is evidence for a hypothesis ADR-005 recorded and refused to act on.**
q002's declared path sat at RRF rank 7, and both rerankers dropped q004's
protected path. ADR-005 wrote that whether q004 is anchored to the wrong
documents was *"a hypothesis, not a measurement"*. It now has support. The
verdicts of ADR-015 and ADR-005 do not change: their rules were fixed before the
readings, and both were decided on paths, not on answers.

## RAGAS delta

**Not applicable, and no number is written.** RAGAS grades generated answers,
and no generation exists; `scripts/run_evaluation.py` is a stub. This feature
touches the instrument RAGAS will use, not the pipeline.

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | pending | pending | — |
| Context Precision | pending | pending | — |
| Answer Relevance | pending | pending | — |
| Context Recall | pending | pending | — |
| Fallback rate | pending | pending | — |

Source recall (ADR-014) is also unchanged and was not re-run: retrieval, the
index and the query are untouched, and `expected_source_paths` did not change.

## Known gaps at merge time

- **The 45 questions are not written.** That is the feature's long pole and it
  belongs to the author (ADR-011 Commitment 1). Angles per unit are in
  [INTERVIEWER_THEMES.md](./INTERVIEWER_THEMES.md).
- **q001, q002 and q004 need their `expected_answer` rewritten**, with the
  evidence above. q002 will likely need to cite `006_lakeflow_migration.md` as
  well — a change to a scored field, so recall artifacts from before and after
  are not comparable (ADR-011 Commitment 2). No RAGAS baseline exists yet, so
  nothing else is invalidated.
- **No question carries `grounding_verified` yet.** The validator warns on all
  four, and will error once the set reaches 50.
- **T4's 17 architecture units are not machine-readable.**
  `make golden-set-next-architecture` still walks all 61.
- **`verify_adversarials.py` is not wired into `make eval`**, as ADR-011
  requires. `run_evaluation.py` is a stub; the wiring belongs to ADR-008.
- **The contamination check is not in CI**, by decision: it guards authoring,
  which happens locally.
- **`yamllint` still reports four long lines** in `evaluation_questions.yml` and
  a missing final newline in `corpus_inventory.yml`. Both predate this slice;
  the count is unchanged (6 lines of output before and after).

## Verification

- [x] `make lint` — ruff and bandit clean; yamllint reports only the
      pre-existing errors listed above
- [x] `make test` — 213 passed (was 182)
- [x] `make golden-set-check` — exits 0, warns on what is incomplete
- [x] `scripts/check_contamination.py` against the real snapshot — clean
- [ ] `make eval` — not applicable, no generation exists
- [ ] `make verify-indexes` — not applicable, no SQL, no index and no query changed
