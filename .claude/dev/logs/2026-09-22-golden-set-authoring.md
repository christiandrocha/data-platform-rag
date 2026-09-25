# Golden-set authoring — open drafts and one deviation

Started 2026-09-22, with the tooling slice merged (PR #8). Questions live here,
not in `evaluation_questions.yml`, until they have an `expected_answer`: the
validator requires one on every in-scope question, and a half-written entry
would turn `make golden-set-check` red during curation.

## Deviation — the seeded walk order is not being followed for architecture

ADR-011 fixes a seeded walk (seed `20260914`) so the last units do not collect
the most fatigued questions, and so one project's voice does not drift into the
other's phrasing. On 2026-09-22 the author chose to write an `architecture`
question about `sdd-kafka-snowflake-2 README.md#Stack` while
`make golden-set-next-architecture` pointed at `sdd-kafka-databricks
README.md#Architecture`.

Decided deliberately and recorded here rather than left silent. The seed is
unchanged, and `--next-architecture` still reports the walk; the author skips
within it. If the order stops being followed at all, that is a decision to take
once, with its reason, not by drifting.

## Closed drafts

- D1 → q006, 2026-09-25. The answer's 8-word check ran against the local clone
  of `sdd-kafka-databricks`, not a snapshot (the `/tmp` snapshot was gone);
  `check_contamination.py` still has to confirm it after `make fetch-corpus`.

## Open drafts — question written, `expected_answer` pending

### D2 — architecture, `sdd-kafka-snowflake-2 README.md#Stack`

> What technology is used for data transformation in Snowflake?

Out of walk order (see the deviation above). Typo in the original draft
("tecchnology") corrected by the author's instruction on 2026-09-22.

An `expected_answer` of "dbt" alone was proposed and left for expansion: a
one-word ground truth gives RAGAS almost nothing to score against.
