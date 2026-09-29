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
- ADR-008 → q025 draft, dropped 2026-09-28. Angle: why `REPLICA IDENTITY FULL`
  on all 20 tables and `apply_as_deletes`, over the rejected alternatives. Five
  audit rounds fixed claims (the path was never observed, lines 23–25; the
  users path filtered deletes before dedup, lines 18–20), but the question
  failed ADR-011 auditor check (a): it names mechanisms only a reader of the ADR
  knows, and its angle overlaps q020. The auditor missed (a) in all five rounds;
  the author raised it. The draft followed lines 55–57 (delete-rewrite rows are
  quarantined before the merge) over lines 14–17 (the row is NULLed by an
  `UPDATE`): ADR-008 contradicts itself here, and no answer should lean on
  either reading alone. On the same day the author chose smaller questions and
  12 `voice: recruiter` questions among the remaining 25 (DESIGN T4, revised
  2026-09-28). q025 will be a new decision question phrased by someone who has
  not read the project.
- ADR-001 → q025, 2026-09-28. Second question on ADR-001, after q012 (why
  Databricks, and what features drove the choice). This one asks only what was
  given up, which line 42 answers. Auditor check (a) passes: a reader who has not
  seen the project would ask this. Two audit findings, fixed by the author:
  "primary drawback" ranked two items line 42 lists as equals, and
  "Consequently" made the second a result of the first, which line 42 does not
  say. Line 36 disparages Lakeflow, which ADR-006 later adopted; no answer should
  lean on it. Longest word run shared with the ADR: 2 in the question, 0 in the
  answer. Closes the q021–q025 batch.
- Liquid Clustering draft, dropped 2026-09-28. After D2 was assigned the
  recruiter voice, the author sent a different architecture question on Liquid
  Clustering versus partitioning. The question was judged fine; the answer's
  claims (partition explosion, storage efficiency, organisation by query
  patterns) are general Databricks knowledge absent from both corpora, and two
  contradict ADR-004 (line 60: cluster_by must be kept in sync by hand; line 14:
  cluster_by is set per contract, not by query patterns). The author declined to
  rewrite it and invoked retreat A3.
- Retreat A3 invoked, 2026-09-28 (ADR-011 amendment). From q026 on,
  `architecture` questions and their `expected_answer` are LLM-written,
  `provenance: llm`, and approved by the author per batch. q026–q030 are the
  first five, all `voice: recruiter`, grounded in the two READMEs: Kafka (q026),
  dbt (q027), Databricks and Unity Catalog (q028), orchestration (q029), data
  contracts (q030). No answer has a digit-bearing token. Longest word run shared
  with the sources: 2 in a question, 6 in an answer. The Databricks README's
  stale passages (parametrized notebooks, Structured Streaming), superseded by
  ADR-006/007, were deliberately avoided.
- q031–q035, 2026-09-28, retreat A3 (`provenance: llm`). Three recruiter
  questions complete the 8 recruiter `architecture` slots: Prometheus and
  Grafana (q031), CI/CD in both projects (q032), Snowflake (q033). Two technical
  ones follow INTERVIEWER_THEMES angles: the dbt layers (q034, SF
  README#Layered modeling) and one user from two sources (q035, the three
  `users` contracts). Self-audit before showing the author: q033 first said an
  idle *warehouse* costs nothing, but the source says the *gate* does, so it was
  corrected; q032 was reworded to cut a 7-word run from the README's CI/CD
  section. Longest word run shared with the sources: 2 in a question, 6 in an
  answer (q033). No digit-bearing token. Left 7 technical `architecture`
  questions.
- q036–q040, 2026-09-28, retreat A3 (`provenance: llm`, all technical). Angles
  from INTERVIEWER_THEMES: SF The Problem (q036), SF Known gaps (q037), SF What
  Evolved (q038), DB Data Contracts (q039), DB TL;DR dataset framing (q040).
  Numbers (60 seconds, nine runs, 129k) left out so no grounding quote is
  needed. Deliberately not used: DB README *Next Steps*, stale (it still lists
  the DLT migration ADR-006 already made), and the README's "scales
  horizontally", which nothing in the corpus demonstrates. q039 says only that
  the stack *lists* loader, Spark schema and pydantic as contract consumers,
  because line 98 gives no mechanism. Longest word run shared with the sources:
  3 in a question, 6 in an answer (q036). Left 2 technical `architecture`
  questions.
- q041–q042, 2026-09-28, retreat A3 (`provenance: llm`, technical). Both from
  SF README#Cost governance: where the trigger design stops saving (q041,
  line 362) and what drives the bill (q042, lines 364, 378–386, 399). Deviation
  approved by the author: DB README#Stack, planned as one of the 17 units, got
  no question. Its `availableNow` / Structured Streaming rows are stale since
  ADR-006/007 moved to Lakeflow, KRaft has one line of support ("No Zookeeper"),
  and Asset Bundles are in q029. Figures (60 seconds, under 2%, 1.1188 credits)
  were put in words, so no grounding quote is needed. Longest word run shared
  with the source: 2 in a question, 4 in an answer. All 18 `architecture`
  questions are now written.
- q043–q047, 2026-09-29, ADR-016 (`provenance: llm`). The four `comparison`
  pairs come from the seeded walk, in order. q043 (technical): how each project
  guards a table-layout rule, DB ADR-004 enforced by CI against SF ADR-0025,
  a convention only. q044 (recruiter): a design call each project revisited,
  DB ADR-002 and SF ADR-0026. The topics do not meet, so the thread is the
  revision itself. q045 (technical): what DB ADR-009 and SF ADR-0019 each
  deliberately did not do. The Kafka-boundary angle was dropped because q010
  and q011 already answer it. q046 (recruiter): how showcasing the work shaped
  choices, DB ADR-001 and SF ADR-0018. The orchestration angle was dropped
  because q012, q013 and q029 cover it. q046 cites DB ADR-006 as a third
  source, because ADR-001's "Structured Streaming over Lakeflow" was later
  reversed. **Corpus inconsistency:** ADR-001 still reads "Accepted" with no
  pointer to that reversal. The fix belongs in sdd-kafka-databricks.
  q047 (technical, `out-of-scope`): why not Airflow. Probes `Airflow`,
  `airflow`, `Apache Airflow`: 0 in-corpus matches, and `astronomer` and
  `MWAA` also 0. `DAG` appears 7 times, all Dagster or Lakeflow graphs, so it
  is not a probe. The author read the probes and the grep (ADR-016 rule 3).
  **Layer 2 deferred** with the author's approval: `make audit-adversarials`
  had crashed since 2026-09-17 (fixed in the batch, with a dry-run test), and
  the local venv has no `anthropic` package and no API key. It must run on
  q047 before the batch PR merges. Longest word run shared with the sources:
  2 in a question, 8 in an answer (q044, "reading the actual SQL corrected two
  of those"; information only, since the contamination check reads questions).
  `comparison` is complete (5/5). Left: 3 `out-of-scope` (Iceberg, trivially
  off-domain, prompt-extraction; 2 of them recruiter).
- q048–q050, 2026-09-29, ADR-016 (`provenance: llm`), the last three
  `out-of-scope`. q048 (recruiter): "Have you worked with Apache Iceberg?". The
  corpus is silent on Iceberg, which does not show the author never used it, so
  the fallback is the right answer and not an inference from Delta Lake.
  Probes `Iceberg`, `iceberg`; `UniForm`, "table format" and `Hudi` are also 0.
  q049 (recruiter): React frontends, the trivially off-domain band. It was
  chosen over mobile because the Databricks dataset simulates a food-delivery
  app. Probes `React`, `frontend`, `Frontend`, `front-end`. Lowercase `react`
  was left out, because the gate matches substrings ("reaction"). q050
  (technical): prompt extraction. The probes are phrases, "system prompt" and
  "previous instructions", because `prompt`, `ignore` and `instruction` already
  occur with other meanings. The question avoids "Claude", which both READMEs
  use for the build methodology, the residual risk the author accepted. For
  every one, the author read the probes and the grep (ADR-016 rule 3). Layer 2
  is deferred with q047, and all four must run before merge.
  **At 50 the validator went strict**, as designed, and failed on the seeds
  q001–q004. q003 got its attestation. q001, q002 and q004 got LLM-rewritten
  answers under the ADR-016 amendment and are now hybrids, a human question
  with an LLM answer, to be reported apart. The set is complete: 50/50, 25
  human and 25 llm, 38 technical and 12 recruiter, 21/21 ADRs covered.

## Open drafts — question written, `expected_answer` pending

None. D2 (*What technology is used for data transformation in Snowflake?*)
was dropped on 2026-09-28: q027 covers dbt in the Snowflake project, and D2's
answer was never written.
