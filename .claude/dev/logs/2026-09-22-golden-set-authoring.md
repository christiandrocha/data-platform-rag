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
  `check_contamination.py` confirmed it the same day against snapshot
  `dpr-corpus-20260925-173826` (`sdd-kafka-databricks` at `f1295df9`).
- ADR-0025 → q007, 2026-09-25. An AI-written draft was offered first and
  rejected under ADR-011 Commitment 1 (a light edit of it still shared 51% of its
  words in 8-word runs). The author then wrote q007 fresh, having read that draft:
  against it, the answer shares no 8-word or 5-word run. Recorded so the Layer 2
  audit can weigh it.
- ADR-002 → q008, 2026-09-25. Two audit rounds: one sentence made the
  unidirectional topology the cause of simpler code (ADR-002 keeps them as
  separate points), and "JSON" contradicted the Avro envelope (line 40). Both
  were fixed by the author.
- ADR-0026 → q009, 2026-09-25. Two audit findings, both fixed by the author:
  "we haven't incrementalized anything yet" contradicted the two models already
  incremental (lines 22–23), and a partial refresh was said to break every global
  ratio, against the low-cardinality exception (line 23). The ADR itself has two
  gaps that no answer should lean on: line 51 counts two `table` candidates where
  its table shows three, and line 14 names two corrections but describes one.
- ADR-009 → q010, 2026-09-25. Three audit findings, all fixed by the author:
  "broke the data flow" overstated a design reason (lines 13–15), "first" added
  an ordering the ADR does not state (lines 22–24), and the question's "column
  prefixes" named something the ADR does not do (it prefixes tables). The ADR
  has three stale passages no answer should lean on: line 84 says the
  `order_identifier` rename proceeds (reverted, lines 10–11), line 153 asks for
  a manual drop that lines 136–140 advise against, and D2's body (lines 46–53)
  reads as applied although it was reverted.
- ADR-0019 → q011, 2026-09-25. No audit findings. "Tier-1" is grounded by a
  verbatim quote from line 22. First question of the q011–q015 batch.
- ADR-001 → q012, 2026-09-25. No audit findings. The answer keeps to the parts of
  ADR-001 that still hold: its Lakeflow rejection (line 36) was overtaken by
  ADR-006/007, and its Snowflake latency and cost rows (lines 24, 28) describe
  classic Snowpipe and a per-query billing model the Snowflake project's own ADRs
  contradict.
- ADR-0018 → q013, 2026-09-25. One minor finding, kept by the author: "too
  fragile for concurrent runs" folds line 9's two problems (concurrent writes,
  crash fragility) into one. Lines 56–57 cite an off-corpus design doc that
  "supersedes this ADR's original text"; no answer should depend on it.
- ADR-005 → q014, 2026-09-25. Two minor findings, kept by the author: "random"
  where the ADR says "arbitrary" (line 51), and "the Silver contracts" where
  `user_id` was enforced by hand, not by contract (lines 30–31). The ADR's "users
  has no YAML contract" (lines 31, 96) was overtaken by ADR-009 D3; its notebook
  names predate ADR-006/007.
- ADR-0020 → q015, 2026-09-25. Two audit findings, both fixed by the author: "a
  limit" dropped the two conflicting monitors (lines 8–14), and "never trust
  documentation … cloud billing" overstated line 70's narrower lesson. Lines
  59–60 (sensors consulting Prometheus) may be in tension with ADR-0019's
  description of the old sensor; no answer should lean on either. Closes the
  q011–q015 batch.
- ADR-003 → q016, 2026-09-25. One audit finding, fixed by the author: "eventually
  … with conditional logic" misdescribed the special cases, which were known at
  decision time and included a separate notebook for `users` (lines 32–35). The
  question is framed historically because ADR-006/007 superseded ADR-003 although
  its status still reads Accepted. ADR-003's "60 notebooks" does not follow from
  its own 20 + 12 domains, and ADR-006 counts 11 Silver runs, not 12. First
  question of the q016–q020 batch.
- ADR-0024 → q017, 2026-09-25. One audit finding, fixed by the author: the first
  draft said the new cursor had skipped rows, where the ADR says review caught it
  before it did (line 17) and only the original sensor had the bug (lines 18, 55).
  "Code review" is slightly more specific than line 17's "independent second
  opinion"; kept.
- ADR-006 → q018, 2026-09-25. One minor finding, kept by the author:
  "guarantees" is stronger than the ADR, which says the per-domain registration
  loop and the uniqueness join were not verified live (lines 92–95). The angle
  (quarantine without a native action) was chosen to avoid duplicating q002.
  ADR-006's "not migrated" list was overtaken by ADR-007; its counts disagree
  (20 + 10 migrated at line 24, "31" at lines 84–85); "ADR-06" at line 91 is
  unexplained.
- ADR-0028 → q019, 2026-09-25. No audit findings. The answer keeps the offset
  tiebreaker to one partition (line 41). The ADR does not discuss whether
  `CreateTime` is ordered across partitions, which ADR-0024's watermark lesson
  would make a fair interviewer probe; no answer should claim either way.
- ADR-008 → q020, 2026-09-25. Two audit findings, both fixed by the author: the
  first draft said the manual test corrupted a Silver row, where the test only
  inspected the Kafka message and the corruption was never observed (lines 8–9,
  23); "drop the record" became deleting the matching row (lines 38, 67–68).
  Lines 110–111 ("Gold tables (full recompute …)") may conflict with ADR-004/005,
  which describe Gold MERGE; no answer should lean on it. Closes the q016–q020
  batch.
- ADR-0021 → q021, 2026-09-25. Three audit findings, all fixed by the author:
  "decimal" for the ADR's `FLOAT64` (a word the auditor's own summary had
  introduced), "permanently locked" (not in the ADR), and "randomly observed"
  (line 33 says observed, not random). The angle (client-side validation) avoids
  q001 and q019. Line 55's "Two … configuration keys" lists four. First question
  of the q021–q025 batch.
- ADR-0027 → q022, 2026-09-25. No audit findings. The answer stays close to the
  ADR's wording (a 7-word run from line 28); `check_contamination.py` checks
  questions only, and the question shares no 8-word run. Lines 85–88 say the
  Resource Monitor trigger actions cannot be verified with the repo's
  credentials, which may conflict with ADR-0020's same-day creation of the
  monitor; no answer should lean on either.
- ADR-0022 → q023, 2026-09-25. No audit findings. The answer scopes the saving to
  "that specific bill", avoiding line 28's "Cost is charged on ingestion volume,
  not on transformation", which read literally contradicts the warehouse-compute
  billing ADR-0019 and ADR-0020 rest on. Last ADR in the walk: all 21 now have a
  question.
- ADR-0030 → q024, 2026-09-25. First decision question on ADR-0030, which until
  now had only q003 (architecture) and q004 (comparison). One audit finding,
  fixed by the author: "entirely data-driven" ignored the three hardcoded domain
  lists the ADR calls "the unclosed half" (lines 69–76). On a coverage note the
  author also added `BACKWARD` compatibility (lines 50–53) to the safeguards.
  The angle (the `doc` field as processing contract) avoids q003, q004 and q021.

## Open drafts — question written, `expected_answer` pending

### D2 — architecture, `sdd-kafka-snowflake-2 README.md#Stack`

> What technology is used for data transformation in Snowflake?

Out of walk order (see the deviation above). Typo in the original draft
("tecchnology") corrected by the author's instruction on 2026-09-22.

An `expected_answer` of "dbt" alone was proposed and left for expansion: a
one-word ground truth gives RAGAS almost nothing to score against.
