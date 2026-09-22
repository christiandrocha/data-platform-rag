# DESIGN: Golden set curation

> Implements [DEFINE.md](./DEFINE.md) (Clarity Score 14/15). Direction set by
> [BRAINSTORM.md](./BRAINSTORM.md): A4 + B4 + C3 + D2→D4.

> **Revision 2026-09-22.** This DESIGN was written on 2026-09-14, before the
> recall, sparse and reranker features. Part of it was built since, some of it
> beyond what is written here, and some of it not at all. The sections below
> now describe the repo as it is, mark what is still to build, and record two
> decisions taken on the revision: the mechanical contamination check **will
> be built**, and incomplete coverage **warns** below 50 questions.

## Metadata

| Field | Value |
|-------|-------|
| Feature | golden-set-curation |
| Depends on | [DEFINE.md](./DEFINE.md) |
| Status | Approved 2026-09-22 — revised against the repo as built (see *Revision 2026-09-22*) |
| ADR needed | **Yes** — [ADR-011](../../../../docs/adr/ADR-011-golden-set-curation.md), Accepted 2026-09-14 |

## Architecture overview

No application code changes. This feature builds an *instrument*, and the
instrument is data plus the tooling that keeps it honest.

```
docs/golden-set/
├── evaluation_questions.yml     ← 50 questions (the instrument); 5 today
├── corpus_inventory.yml         ← built: seed + 21 ADRs + 61 architecture units
└── README.md                    ← schema + distribution + curation rules

scripts/
├── validate_golden_set.py       ← built; TO BUILD: grounding + comparison checks
├── golden_set_coverage.py       ← built (matrix, --next, --next-architecture,
│                                   --next-comparison-pair); TO BUILD: warn below 50
├── check_contamination.py       ← TO BUILD: 8-word verbatim overlap detector
├── verify_adversarials.py       ← built: Layer 1, literal probes (ADR-011)
└── audit_questions.py           ← built: Layer 2, Opus auditor (T1)

Makefile
├── golden-set-check             ← validate + coverage; TO BUILD: + contamination
├── golden-set-next[-architecture|-comparison-pair]   ← built
├── verify-adversarials          ← built
└── audit-adversarials           ← built
```

Every script that reads the corpus resolves it through
`data_platform_rag.indexer.corpus` (`resolve_snapshot`, `in_corpus_files`): the
newest `/tmp/dpr-corpus-*` by default, `--corpus-dir` to override (ADR-012).
None declares its own file set.

Three properties the tooling must have, because the failure modes are all silent:

1. **Coverage is computed, never asserted.** A checked-in matrix would become a
   second source of truth and drift from the YAML.
2. **Contamination is mechanical.** "Write naturally" is advice; an 8-word
   verbatim overlap test is a gate.
3. **Incompleteness warns, wrongness fails.** Curation takes days. The validator
   must stay usable at question 11 of 50 without turning CI red, then become
   strict the moment the set is full. The existing warning/error split already
   does this; the new checks follow the same rule.

## Data contracts

### `evaluation_questions.yml` — fields built, and the two still to build

```yaml
- id: q001
  provenance: human                 # built — human | llm (ADR-011 retreat A3)
  voice: technical                  # built — recruiter | technical (DESIGN T4)
  intent: decision                  # decision | architecture | comparison | out-of-scope
  question: "..."
  expected_answer: "..."            # null iff intent is out-of-scope
  expected_source_paths:
    - project: sdd-kafka-snowflake-2
      path: docs/adr/0029_snowpipe_streaming_as_the_ingestion_path.md
  grounding_verified: true          # TO BUILD — required for in-scope questions
  grounding:                        # TO BUILD — required only for high-risk claims
    - claim: "<the claim span from expected_answer>"
      project: sdd-kafka-snowflake-2
      path: docs/adr/0029_snowpipe_streaming_as_the_ingestion_path.md
      quote: "<verbatim text from that file>"

- id: q005
  intent: out-of-scope
  contamination_probes: ["Apache Flink", "Kafka Streams"]  # built — out-of-scope only
  grep_verified: 2026-09-14                                # built — out-of-scope only
```

The `claim` and `quote` above are placeholders on purpose: an example quote
invented here would be exactly the unsupported claim this field exists to catch.

**`grounding` is deliberately partial, and that is a weakening of D2.** Full
clause-by-clause evidence for 45 questions is roughly 135 quote entries —
disproportionate to the risk, and the kind of ceremony that gets abandoned at
question 20 and then lied about. Instead the quote requirement binds only where
being wrong actually costs: **any claim containing a number, a version, a
latency/cost figure, or a named product or mechanism**. Prose claims are covered
by `grounding_verified` alone. The COULD-level D4 auditor later mechanises the
rest.

### `corpus_inventory.yml` — new file

```yaml
seed: 20260914                       # ADR-011: immutable for this generation
verified_against_clone: 2026-09-14
sdd-kafka-snowflake-2:
  adrs: [docs/adr/0018_dedicated_postgres_for_dagster_storage.md, ...]  # 12
  architecture: [README.md#TL;DR, ..., dbt/macros/resolve_cdc.sql]      # 25
sdd-kafka-databricks:
  adrs: [docs/adr/001_databricks_vs_snowflake.md, ...]                  #  9
  architecture: [README.md#TL;DR, ..., contracts/users_mssql.yml]       # 36
```

The `architecture` list is the coverage universe for `architecture` questions.
Which 17 of its 61 units get a question is decided in T4, not by this file.

Coverage cannot be derived from `expected_source_paths` alone: that tells you
which ADRs *are* cited, never which exist and are missing — the exact gap the
check must catch. An inventory is the minimum external fact required.

**Known drift risk, accepted:** this file is hand-maintained and goes stale if
the corpus repos gain an ADR. Mitigation is a one-line note in the file and a
check during `corpus-indexing` BUILD, when a clone is present, comparing the
inventory against the clone. Recorded rather than solved.

## Interfaces

| Interface | Change |
|-----------|--------|
| `scripts/validate_golden_set.py` | **Built:** required fields, `provenance`, `voice`, `intent`, `{project, path}` sources, answer/source coherence against `intent`, adversarial fields (`contamination_probes` ≥ 1, `grep_verified`) on out-of-scope only, 22/18/5/5 distribution (warn below 50, error at 50). **To build:** `grounding_verified is True` on in-scope questions and a `grounding` quote for any claim span with a digit, a version or an `ADR-\d+` (warn below 50, error at 50); every `comparison` question cites at least one source from each project (DEFINE MUST) |
| `scripts/golden_set_coverage.py` | **Built:** ADR × intent matrix; `--next`, `--next-architecture`, `--next-comparison-pair` in seeded walk order. **To build:** while the set has fewer than 50 questions, uncovered ADRs are a warning and the exit is 0; at 50, any uncovered ADR exits 1. Today it exits 1 whenever an ADR is uncovered, which contradicts property 3 above |
| `scripts/check_contamination.py` | **To build.** Reports any question whose text shares an 8-word verbatim span with one of its cited sources, after lowercasing and collapsing whitespace; exits 1 on any hit. Reads cited files only through `corpus.in_corpus_files`, from the snapshot `resolve_snapshot` returns (`--corpus-dir` overrides). With no snapshot on disk it prints an explicit skip and exits 0 — never a silent pass |
| `scripts/verify_adversarials.py` | **Built.** Layer 1: case-sensitive literal probes against the in-corpus files of both repos; non-zero exit on any match. **Not yet wired** as a precondition of `make eval` / `make eval-ci`: `run_evaluation.py` is a stub, so the wiring belongs to the RAGAS feature (ADR-008), which inherits it from ADR-011 |
| `scripts/audit_questions.py` | **Built.** Layer 2, `claude-opus-5`, advisory only (T1); `--adversarial` for paraphrase contamination |
| `make golden-set-check` | **Built:** validate + coverage. **To build:** + `check_contamination.py`, which skips loudly when no snapshot exists |
| Config | None. No new env vars, no `settings.*` additions |
| `contracts.py` | None. The golden set is a file format, not an inter-module boundary — it crosses into Python only via `evaluation/golden_set_loader.py`, which does not exist yet and belongs to the RAGAS feature |

## Retrieval and RAG-specific concerns

- [x] **Does this affect chunking?** No. No source material is chunked or
      re-chunked. ADR-007 is untouched.
- [x] **Does this touch the HNSW index?** No. No reindex, no DDL, no vector
      written.
- [x] **Does this change the query pattern?** No. `sql/99_verify.sql` baseline is
      unaffected.
- [x] **Does this change RAGAS metrics?** **This feature *is* the RAGAS
      instrument.** Regression risk today is **nil** — no eval has ever run, so
      there is no baseline to regress against.

      The consequence runs the other way and is the part worth designing for:
      **once 50 questions exist and ADR-008 records a baseline, editing any
      question silently invalidates every comparison across that edit.** A metric
      that moves because the ruler changed is indistinguishable from one that
      moved because the system changed. This feature therefore has to leave
      behind a change policy for the set, not just the set. That policy is the
      main reason an ADR is warranted — see below.

## Alternatives considered

- **Checked-in coverage matrix instead of a generator.** Rejected: a second
  source of truth that drifts from the YAML, and drift here is invisible — a
  stale matrix reports full coverage for an ADR nobody asked about.
- **Full clause-by-clause `grounding` for every claim (strict D2).** Rejected as
  disproportionate: ~135 quote entries, most of them proving prose that carries
  no factual risk. The partial rule targets the subset where a wrong ground truth
  produces a permanently unachievable Context Recall.
- **No `grounding` field; trust the author (D1).** Rejected: the failure is
  silent and expensive. A wrong expected answer looks exactly like a retrieval
  bug, and someone spends a day debugging the pipeline.
- **Contamination check in CI.** Rejected for now, on a revised reason. The
  2026-09-14 reason was that CI has no corpus clone; ADR-012 has since given CI
  one (`make fetch-corpus`, used by `ragas.yml`). The check stays out of `ci.yml`
  because it guards authoring, which happens locally, and fetching the corpus on
  every push for it is disproportionate. Deferred to ADR-008, which owns CI
  evaluation and already fetches the corpus.
- **Derive coverage from `expected_source_paths` alone, no inventory.**
  Rejected: structurally cannot detect an uncited ADR, which is the only thing
  the check exists to find.

## Test plan

### Unit tests — `tests/unit/test_validate_golden_set.py` (built: 25 tests)

Built and passing: `should_fallback`, `check_sources`, `check_coherence`,
adversarial fields, `check_distribution`, `check_voice`. Still to add, as pure
functions over parsed YAML: `check_grounding` and the comparison-sources rule.
The original list, kept for the record:

- `check_sources`: rejects bare strings, missing `project`, missing `path`,
  unknown keys, a project outside `SourceProject`, a non-string path
- `check_distribution`: warns below 50 without erroring; errors at exactly 50
  with a wrong split; errors above 50; passes at exactly 22/18/5/5
- `check_coherence`: rejects an out-of-scope question carrying an answer or
  sources; rejects an in-scope question missing either; accepts both aligned
- `should_fallback`: returns True only for `out-of-scope`
- `check_grounding`: below 50, missing `grounding_verified` warns; at 50 it
  errors; fallback questions are exempt; a claim containing a digit without a
  `grounding` quote errors
- Duplicate-id and missing-field detection (existing behaviour, currently untested)
- `check_comparison_sources` (to build): rejects a `comparison` question whose
  sources all come from one project; accepts one source from each

### Unit tests — `tests/unit/test_check_contamination.py` (to build)

- An 8-word span shared with the cited text is a hit; a 7-word span is not
- Case and whitespace differences do not hide a hit
- Only the question's own cited sources are compared, not the whole corpus
- No snapshot on disk: explicit skip message, exit 0

### Unit tests — coverage warning (to build)

- Below 50 questions with uncovered ADRs: warning, exit 0
- At 50 with an uncovered ADR: exit 1

### Integration tests — `tests/integration/test_golden_set_files.py` (to build)

- The real `evaluation_questions.yml` parses and validates clean (exit 0)
- `golden_set_coverage.py` against the real inventory warns and exits 0 while
  the set is incomplete, and names the uncovered ADRs *(revised 2026-09-22: was
  "exits 1")*
- Every `project` value in the real file is a member of `contracts.SourceProject`
  — catches divergence between the YAML vocabulary and the pydantic Literal,
  which are maintained in two places
- Every `path` in the real file is a plausible relative path (no leading `/`, no
  `..`)

### Manual verification

- Read the 5 adversarials end to end and name the difficulty band of each;
  confirm exactly one is the prompt-extraction case
- Spot-check 3 questions: trace every numeric or named-mechanism claim in
  `expected_answer` to its `grounding` quote, and confirm the quote is real by
  opening the cited file in a corpus clone
- Read 5 randomly chosen questions and judge, honestly, whether someone who had
  *not* read the ADR would phrase them that way — the check `check_contamination`
  cannot make

## Rollout plan

No schema migration, no database, no user-visible surface. Order matters only
because the validator tightens:

1. Add `grounding_verified` to the 4 existing non-fallback questions. q005 is
   exempt (`expected_answer: null`). **To build.**
2. Land the validator changes with the new checks at **warning** severity below
   50 questions, so curation can proceed without a red build. **Partly built**:
   grounding and comparison checks remain.
3. Add `corpus_inventory.yml` and `golden_set_coverage.py`. **Built**; the
   warning below 50 remains.
4. Add `check_contamination.py` and wire it into `make golden-set-check`.
   **To build** (decided 2026-09-22).
5. Author the 45 questions (the long pole — days, not hours), from the angles in
   [INTERVIEWER_THEMES.md](./INTERVIEWER_THEMES.md) (T4).
6. At 50, all checks flip to error automatically via the existing threshold
   logic. No code change at the flip.

**Rollback:** revert the YAML and the scripts. Nothing else depends on them yet;
`evaluation/golden_set_loader.py` does not exist. The blast radius is one
directory and three scripts, and no data is destroyed. This is the cheapest
feature in the project to undo — which is precisely why the expensive part
(question quality) must be got right the first time, since *that* is not
recoverable by a revert.

## Open questions

All five open questions from DEFINE are resolved below. One new question is
raised and needs a decision before the ADR is written.

| # | DEFINE question | Resolution |
|---|-----------------|------------|
| 1 | Does `should_fallback: true` imply `intent: out-of-scope`? | **Resolved by removing the field** (commit `c2a45a2`). Enforcing a pairing between two fields that encode one fact is weaker than not having the second field. `should_fallback(q)` is now a derived helper in the validator |
| 2 | Where does the coverage matrix live? | **Resolved — generated, not checked in**, by `golden_set_coverage.py`, against a small hand-maintained `corpus_inventory.yml`. Reviewable via one command; cannot drift from the YAML |
| 3 | Contamination check: script or review step? | **Resolved — script**, `check_contamination.py`, requiring `--corpus-dir`. Runs during curation where a clone already exists; skips loudly otherwise. CI integration deferred to ADR-008 |
| 4 | What counts as one of "the 21 ADRs"? | **Resolved — one ADR file is one coverage unit**, superseded or not. A question about a reversal covers both only if it cites both. Reversals are high-value questions (the system prompt mandates preserving them), so counting them separately is deliberate |
| 5 | How is grounding recorded? | **Resolved — `grounding_verified` on every non-fallback question, plus `grounding` quotes only for claims carrying numbers or named mechanisms.** A deliberate, documented weakening of strict D2; rationale in Data contracts |

- [x] ~~ADR number.~~ **RESOLVED.** Golden-set methodology is ADR-011 (Accepted
      2026-09-14). *(Revised 2026-09-22: this line used to reserve ADR-012 for a
      `rerank_top_k` decision. ADR-012 became the corpus snapshot lifecycle, and
      ADR-005 rejected the reranker on 2026-09-21, so no such ADR is pending.)*
- [ ] **Real interview questions (DEFINE SHOULD).** Questions Christian was
      actually asked about these projects are the strongest provenance the set
      can have, and they fit the technical-interviewer focus of T4. Open: whether
      any exist and can be recorded before authoring starts.
- [ ] **T4's 17 architecture units are not machine-readable.** `make
      golden-set-next-architecture` walks all 61 and will propose units outside
      the list. BUILD decides whether the list moves into `corpus_inventory.yml`
      or the author skips by hand.

## Resolved tension points

Three items raised for DESIGN to settle rather than DEFINE to re-open.

### T1 — The LLM auditor has no interface. Now it does.

`scripts/audit_questions.py`, run manually during curation, never in CI.

| Aspect | Decision |
|--------|----------|
| Model | `claude-opus-5` |
| Input per question | The question, its `expected_answer`, and the cited source excerpts pulled from a local corpus clone (`--corpus-dir`) |
| Asks | (a) Would someone who had **not** read this source phrase the question this way? (b) Is every claim in `expected_answer` supported by the quoted text? (c) Which cited source, if any, is not actually needed? |
| Output | Per-question verdict plus rationale, written to `.claude/dev/reports/audit-{timestamp}.md`. Advisory — it never edits the YAML |
| Cost | ~2,050 input + ~150 output tokens per question. At Opus 5 pricing ($5/$25 per MTok): **~$0.014 per question, ~$0.70 per full 50-question pass.** Five passes across curation is roughly $3.50 |

Opus rather than Haiku deliberately: this is the judgment task the mechanical
checks cannot do, and a missed contamination is silent and permanent. Saving
$0.55 a pass is not a reason to use a weaker judge on the instrument that
validates everything else. The auditor is **advisory and non-authoring** — it
emits a report, a human edits the YAML. That boundary is the whole point of A4
and is what the ADR exists to protect.

### T2 — Corpus sampling sequence: deterministic, seeded, interleaved

Authoring 45 questions in inventory order produces two systematic biases: the
last ADRs get the tired questions, and writing all of one project before the
other lets a per-project "voice" drift into the phrasing.

- Walk order is a **seeded shuffle** of `corpus_inventory.yml`, interleaving the
  two projects, with **seed `20260914`** recorded in the inventory file itself.
- `scripts/golden_set_coverage.py --next` prints the next uncovered ADR in that
  order, so authoring is driven by the sequence rather than by appetite.
- The seed makes the order reproducible, so a reviewer can verify coverage was
  systematic rather than opportunistic.

### T3 — The "Delta Live Tables" adversarial is contaminated. Verified, not assumed.

`docs/golden-set/README.md` suggested it as the model adversarial. It is not one.
Grepped against the in-corpus files of `sdd-kafka-databricks`:

```
docs/adr/001_databricks_vs_snowflake.md:36
  "Databricks Lakeflow (DLT) — evaluated but Structured Streaming is more explicit"
docs/adr/003_parametrized_notebooks.md:40
  "Lakeflow DLT — different abstraction; less explicit control over MERGE logic"
```

Both are in-scope ADR files. "What did Christian decide about Delta Live Tables?"
has a real, citable answer — it is a legitimate `decision` question. As an
adversarial it would have failed `fallback_accuracy` on every run, and that
metric must be 100% per Section 7.

Root cause worth naming: DLT is the former name of Lakeflow Declarative
Pipelines. An adversarial chosen by intuition about a *rebrand* is exactly the
kind that looks absent and is not.

**Resolution**: the curation rule now requires every adversarial candidate to be
grepped against both corpora before it enters the set, and the README records
twelve verified-absent topics as of 2026-09-14 (Iceberg, Hudi, Flink, Airflow,
Great Expectations, Trino, Presto, ClickHouse, Monte Carlo, Atlan, Collibra,
DuckDB) with an instruction to re-verify, since the corpora change. The existing
q005 (Flink vs Kafka Streams) was checked and **is** valid.

**Point-in-time verification decays, so the gate is blocking.** If a corpus repo
later gains an ADR mentioning Flink, q005 turns silently invalid. ADR-011 settles
this as a **fail-fast gate scoped to adversarials**, not a warning, on the
severity criterion the corpus itself established in `sdd-kafka-snowflake-2`
ADR-0027: an error is a violation that, propagated, makes a metric *objectively
wrong* rather than degraded. A contaminated adversarial makes `fallback_accuracy`
wrong while leaving it looking healthy. The scope stays narrow — a new corpus
mention only changes semantic status for an out-of-scope question; for an
in-scope one it is simply more material to retrieve.

### T4 — Voice and architecture units: decided 2026-09-22

Angles per unit live in [INTERVIEWER_THEMES.md](./INTERVIEWER_THEMES.md): research
input, not questions. Commitment 1 of ADR-011 is unchanged.

- **All 45 remaining questions are `voice: technical`.** The audience this
  generation measures is the technical interviewer. The `recruiter` voice stays
  in the schema but has no questions, so recruiter-style performance is
  **unmeasured**, and that is recorded as a known gap in
  `docs/golden-set/README.md`.
- **The 17 architecture units are chosen by interviewer relevance**, not by
  taking the first 17 of `make golden-set-next-architecture`'s 61-unit walk,
  which would include units like `#License` and `#Author`. The seeded walk
  still sets the *order* of authoring: skip units not on the list. This is a
  selection decision, not a re-shuffle, so the seed stays `20260914`.
- **Both `#Interview Cheat Sheet` sections are excluded** as expected sources.
  They answer interview questions nearly verbatim; a match there would measure
  phrasing, not retrieval.
- **The 4 new adversarials complete decision C3's gradient**: two
  adjacent-but-absent, one trivially out-of-domain, one prompt-extraction.
  q005 already holds the subjective band.

## Why an ADR is warranted

Three commitments here outlive this feature and would otherwise be violated by a
future contributor with no way to know they were decisions:

1. **Questions are human-authored; LLMs audit but never write.** Without a
   recorded rationale this reads as an inefficiency to be optimised away, and the
   optimisation is invisible — the metrics improve.
2. **The golden set is a measuring instrument, and editing it invalidates
   baselines across the edit.** This needs a stated change policy, or ADR-008's
   regression gate silently compares incomparable runs.
3. **`grounding` is partial by design.** Written down, it is a proportionality
   judgment; undocumented, it looks like an unfinished D2.
