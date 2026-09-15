# Phase 0 — findings deliberately not fixed

Recorded during the Phase 0 (Preparation) pass over `docs/PRE_BUILD_VALIDATION.md`
Section 6, applied 2026-09-14. Everything below was found while applying the ten
approved changes, falls outside Section 6's scope, and was left untouched on
purpose. Each entry names where it should be resolved.

---

## 1. `Chunk` dataclass diverges from `ChunkMetadata` — resolve in BUILD: corpus-indexing

**Owner**: feature `corpus-indexing`
**Raised by**: Change 4 (added `keywords` to `ChunkMetadata`)

`data_platform_rag/indexer/chunker.py::Chunk` is the dataclass that *produces*
chunk metadata, and it mirrors `contracts.py::ChunkMetadata` field by field —
by hand, with no enforced relationship. After Change 4 the two have diverged:
`ChunkMetadata` has `keywords: list[str] | None`, `Chunk` does not.

This is the second-order problem, and the more important one: a hand-mirrored
dataclass sitting next to the pydantic contract it duplicates will drift again
on the next field. ADR-010 says every inter-module boundary uses a model from
`contracts.py`; `Chunk` is exactly such a boundary (chunker -> writer).

Resolve during BUILD of `corpus-indexing`, choosing one:

- Delete `Chunk` and have the chunker emit `ChunkMetadata` + content directly.
- Keep `Chunk` as an internal working type and add a test asserting its field
  set is a superset of `ChunkMetadata`'s, so drift fails CI.

The first is more in the spirit of ADR-010. Either way, `keywords` gets added.

---

## 2. `loader.py` lists this repo as a corpus source — violates an AGENTS.md boundary

**Status**: RESOLVED 2026-09-14
**Resolution**: docstring corrected and an explicit "this repo is NOT a corpus
source" note added. `RawDocument.source_project` retyped from bare `str` to
`SourceProject` imported from `contracts.py`, so the two-project constraint is
now enforced by the type rather than described in prose. `contracts.py`
already held the correct two-value `Literal` and needed no change.

`data_platform_rag/indexer/loader.py:6` documents the corpus as:

```
- data-platform-rag (self) -> this project's docs/adr/
```

AGENTS.md states, as a hard boundary: "Never index the data-platform-rag repo
itself as a corpus source. [...] Self-indexing introduces recursion risk and was
explicitly rejected." `docs/PRE_BUILD_VALIDATION.md` Section 2 fixes the corpus
at two projects.

It is a docstring, not executable code — which is precisely why it is dangerous.
It is the specification someone implements `load_corpus` against.

---

## 3. `loader.py` annotates an undefined name

**Status**: RESOLVED 2026-09-14
**Resolution**: fixed as a side effect of #2 — `Collection`, `SourceProject`,
and `SourceType` are now imported from `contracts.py`, and the duplicated local
`SourceType` alias was deleted (ADR-010: `contracts.py` is the single source).
`Iterator` moved from `typing` to `collections.abc`. `ruff check` is now clean
across `data_platform_rag/` and `scripts/`.

`loader.py:29` declares `collection: Collection` on `RawDocument`, but
`Collection` is never imported — line 15 only carries a comment saying the alias
lives in `data_platform_rag.contracts`. `from __future__ import annotations`
defers evaluation, so the module imports fine and nothing fails today. It breaks
type checking, and it breaks at runtime for anything calling `get_type_hints()`.

---

## 4. `sql/01_schema.sql` header contradicts its own constraint

**Status**: RESOLVED 2026-09-14
**Resolution**: header corrected to "Two logical collections", aligning it with the
`CHECK` constraint, the table comment, and the title of ADR-002. The header was
the only place in the repo claiming three.

Line 2 says "Three logical collections, one physical table". The `CHECK`
constraint on line 15 allows two (`decisions`, `architecture`), ADR-002 is
titled "Two logical collections in one physical table", and the table comment on
line 49 says two. The header is the only place claiming three.

Left as found: Change 5's scope was the `keywords` column and the `pg_trgm`
comment, and silently rewriting an unrelated header comment in the same pass
would have buried it.

---

## 5. `sql/01_schema.sql` repeats the self-indexing violation

**Status**: RESOLVED 2026-09-14
**Resolution**: the `source_project` column comment now lists the two corpus
projects and states that this repo is not one of them.

The inline comment on the `source_project` column lists three values, including
`data-platform-rag`. Same boundary violation as #2, in a second file. Fixing one
without the other leaves the contradiction intact.

---

## 6. README cost claim is arithmetically wrong

**Status**: DECIDED 2026-09-14 — one cascade still open (see below)
**Decision**: top-k reduced pre-emptively to meet the Section 7 cost
non-negotiable — revisit during BUILD iteration with real RAGAS data. If the
reduction proves load-bearing for quality rather than just cost, it earns
ADR-011 rather than remaining a config default.

`config.py::rerank_top_k` 5 -> 3, mirrored in `.env.example`. Recomputed cost
is **$0.0083/query**, not the $0.0076 estimated when the decision was taken:
scaling the old total linearly by token count assumes input and output cost the
same, and they do not (output is 5x). The decision holds either way — both
figures clear the < $0.01 gate — but the KB carries the per-direction
arithmetic so the next reader can check it.

**Still open**: `README.md:64` continues to claim "cost per query <$0.005",
which no longer matches any computed figure.

`README.md:64` claims "cost per query <$0.005", and
`.claude/kb/langfuse/cost-tracking.md:29` claims the same. At the token shape
that file itself documents (500 system + 2000 context + 50 query in, 200 out)
and Claude Sonnet 4.6 pricing ($3/$15 per MTok), a query costs ~$0.0107 — which
also trips the ">$0.01/query, investigate" alarm in the same KB file, on every
normal query.

`docs/PRE_BUILD_VALIDATION.md` Section 7 makes "cost < $0.01 per non-fallback
query" a publication non-negotiable, so this is not cosmetic: the current model
choice fails that gate on paper before a single query runs.

Three ways out, all requiring a decision: correct the target, switch the model
(`claude-sonnet-5` is $2/$10 -> ~$0.0071, still above $0.005), or shrink the
context budget. AGENTS.md forbids publishing invented numbers, so the claim
cannot simply stand.

---

## 7. Langfuse KB and client are written against SDK v2; the pin resolves to v4

**Status**: RESOLVED 2026-09-14 (contained, not eliminated)
**Decision**: API divergence Langfuse v2 vs v4 to be resolved during Phase 4
BUILD of `langfuse-integration` — verify the current SDK API before implementing
decorators.

`pyproject.toml` now pins `langfuse>=2.50,<3.0`, so an install resolves to the
API the KB and `langfuse_client.py` actually describe. This stops the bleeding;
it does not modernise anything. The v4 line is two majors ahead.

`pyproject.toml` pins `langfuse>=2.50` with no upper bound; the current release
is 4.15.2. `.claude/kb/langfuse/python-sdk.md` documents
`from langfuse.decorators import observe`, and both that KB file and
`observability/langfuse_client.py` assume the v2 `trace()` / `span()` /
`generation()` surface, replaced in v3.

The failure mode is the bad one: `NoopLangfuse` implements the v2 shape and
keeps working, so with the default `LANGFUSE_ENABLED=false` nothing surfaces
until observability is switched on.

Decide whether to cap the pin at 2.x or rewrite for 4.x, then make the KB match.


---

## 8. `UNIQUE (source_path, chunk_index)` collides across the two corpus repos

**Status**: RESOLVED 2026-09-14
**Raised by**: the `golden-set-curation` brainstorm, while mapping
`expected_source_paths` onto `chunks`
**Class**: Phase 0 defect — shipped in commit `d0bf569`, found after

`sql/01_schema.sql` declared `UNIQUE (source_path, chunk_index)` with
`source_path` stored unqualified (`docs/adr/ADR-0019.md`, `README.md`). Both
corpus repos have a `README.md` and a `docs/adr/` tree. Under ADR-007 a README is
chunked by `##` section with an ordinal `chunk_index`, so
`sdd-kafka-snowflake-2/README.md` and `sdd-kafka-databricks/README.md` both
produce `(README.md, 0)`. The second insert violates the constraint, and
`make index-corpus` fails partway through the second repo.

The same flaw appeared in the golden set: `q004` cited files from both projects
and disambiguated them only with a YAML comment, which the parser discards.

**Resolution**: key qualified to `(source_project, source_path, chunk_index)`,
with the reason recorded inline in the DDL so it is not "simplified" later.
`expected_source_paths` changed from `list[str]` to a list of `{project, path}`
objects; `scripts/validate_golden_set.py` now rejects bare strings and entries
whose `project` is outside `SourceProject`. Prose references updated in ADR-007,
`scripts/index_corpus.py`, and `.claude/sdd/architecture/ARCHITECTURE.md`.

**Why it survived Phase 0**: every review pass read the constraint as a
single-repo statement. Nothing in the schema, the ADRs, or the tests exercised
two repos at once, and no integration test writes a chunk yet. The first test
that would have caught it is the one `corpus-indexing` has not written.


---

## 9. ADR-012 candidate — `rerank_top_k`

**Status**: CANDIDATE — no ADR written, deliberately
**Raised by**: Phase 0 pendência #6 (cost gate)

Current baseline: `rerank_top_k=3` (chosen pre-emptively during Phase 0 to meet
the Section 7 cost non-negotiable, see the Phase 0 dev log entry #6). ADR-012
will supersede this baseline only if RAGAS-measured Context Recall justifies a
different value.

No ADR is written now. It becomes one during Phase 5 calibration, if and only if
measurement produces a number that justifies changing the value. Writing it
earlier would document a guess as a decision.

---

## 10. Adversarial grep verification — record for 2026-09-14

**Status**: RECORDED
**Rule**: ADR-011, "Adversarial questions are verified absent, never assumed"

Verified against the in-corpus files of both repos (`docs/adr/`, `README.md`,
`contracts/`, `macros/`) on 2026-09-14:

**Existing adversarial**
- `q005` — Apache Flink vs Kafka Streams: **0 in-corpus matches. Valid.**

**Verified-absent candidates for future adversarials** (12): Apache Iceberg,
Hudi, Flink, Airflow, Great Expectations, Trino, Presto, ClickHouse, Monte
Carlo, Atlan, Collibra, DuckDB.

**Verified PRESENT — rejected as adversarials**
- `Delta Live Tables` / `DLT` — present in `sdd-kafka-databricks`
  `docs/adr/001_databricks_vs_snowflake.md:36` and
  `docs/adr/003_parametrized_notebooks.md:40`, both as a rejected alternative.
  This was the repo's own suggested example adversarial. It is a legitimate
  `decision` question and would have failed `fallback_accuracy` on every run.
- `dagster` — 9 in-corpus files. Correctly so; it is the snowflake orchestrator.

**Illustrative examples in ADR-011 Commitment 3**
- `1024` — 0 matches, clean.
- `ADR-9999` — 0 matches; substituted for `ADR-0029`, which matched 2 files.
- `Debezium` (10 files) and `Unity Catalog` (5 files) — annotated as illustrative
  matches rather than substituted, per the curation rule in ADR-011.

All greps are point-in-time. `scripts/reverify_adversarials.py` (ADR-011) makes
this durable by re-running as a blocking precondition of every eval.


---

## 11. Audit cost arithmetic corrected — $0.07 → ~$2.10

**Status**: CORRECTED 2026-09-14
**Same pattern as finding #6** ($0.0076 → $0.0083): a supplied figure was
recomputed rather than copied, and the discrepancy recorded rather than erased.

The BUILD plan estimated ~$0.07 total for five Layer 2 audits at questions 10,
20, 30, 40 and 50. Those five passes audit 10 + 20 + 30 + 40 + 50 = **150
question-audits**, not 50. At the ADR-011 estimate of ~$0.014 per question that
is **~$2.10**, roughly 30x the figure given.

The decision is unaffected — $2.10 is still negligible — but the number in the
plan was wrong by an order of magnitude and would have propagated into
BUILD_REPORT.

**Measured, not estimated**: `scripts/audit_questions.py --dry-run` against the
current 5-question set reports ~$0.0075 per in-scope question and ~$0.0085 for
the adversarial — both *below* the ADR-011 estimate, because the starter
questions cite short sources and adversarial mode scans ADR titles rather than
full text. Expect the per-question figure to rise as questions cite fuller ADRs.
Real usage is recorded per run in the audit report footer.

**Corrected by #20** (2026-09-15): the per-question figure above is an estimate, not a measurement.

---

## 12. Retreat A3 invoked — LLM proposes architecture questions

**Status**: DECIDED 2026-09-14
**Trigger**: 11-19h of curation time not available this week.

ADR-011's pre-approved pragmatic retreat is invoked. Human authors the 27
`decision`, `comparison` and `out-of-scope` questions; an LLM proposes the 18
`architecture` questions. Four preconditions, all landed before any question is
written:

1. `provenance: human | llm` is a required field; the 5 starter questions are
   marked `human`.
2. Human questions are written and committed **before** the LLM proposes any.
3. Layer 2 audits are stratified by provenance, every 10 questions within each
   batch. If the first LLM batch shows systematically worse contamination than
   the human batch, frequency increases before continuing.
4. Final RAGAS is reported per stratum. A large human/LLM delta earns a new known
   gap in ADR-011, or its own ADR on correction methodology.

The purpose of the retreat is a **measurable** bias, not a hidden one. Without
the four preconditions above, A3 silently becomes the thing Commitment 1 exists
to prevent.


---

## 13. Layer 1 was not grepping macros at all

**Status**: RESOLVED 2026-09-14
**Raised by**: sizing the architecture inventory for golden-set-curation

`verify_adversarials.py` declared `IN_CORPUS_SUBPATHS = (..., "macros")`. Neither
corpus repo has a top-level `macros/` directory — the snowflake macros live at
`dbt/macros/`. A non-existent subpath is skipped silently, so the constant
covered **zero** macro files while reporting success.

Same shape as the `UNIQUE (source_path, chunk_index)` defect: a wrong path does
not raise, it just covers nothing, and the gate reports green.

Corrected to `dbt/macros`, which also excludes `dbt/dbt_packages/` — vendored
third-party macros that are not corpus. Snowflake in-corpus file count went from
14 to 17.

---

## 14. `--corpus-dir` canonical location — pending implementation

**Status**: DECIDED 2026-09-14, implementation pending `make index-corpus`

Canonical: the newest `/tmp/dpr-corpus-*`, created by `make index-corpus`.
Override: an explicit `--corpus-dir` (or `CORPUS_DIR=` for make), accepted for
local dev only.

Rationale: CI runs on a GitHub Actions runner with no `~/Documents`, so `/tmp` is
the only location that works in both environments. A local override buys
iteration speed at the cost of reproducibility — acceptable for dev, not for CI.

`verify_adversarials.py` and `audit_questions.py` already implement the default
and the override. **What does not exist yet is the thing that creates the
directory**: `make index-corpus` is still a stub, so the canonical path currently
resolves to nothing and every local run must pass an override. Resolve when
`corpus-indexing` is built (Feature 2), which is also where the glob-vs-fixed-name
question gets settled — `dpr-corpus-*` with a timestamp means the newest wins,
and stale clones are never cleaned up by these scripts.

---

## 15. Human/LLM batch split corrected — 28/17, not 27/18

**Status**: CORRECTED 2026-09-14
**Cause**: q003 was counted as `decision`; it is `architecture`.
**Pattern**: third arithmetic correction of this session, after $0.005 -> $0.0083
(finding #6) and $0.07 -> $2.10 (finding #11). All three followed the same shape:
a supplied figure was recomputed rather than copied, and the discrepancy was
recorded rather than silently replaced.

The BUILD plan put the split at 27 human / 18 LLM. The existing starter question
`q003` is `intent: architecture` and human-authored, so only **17** architecture
questions remain for the LLM batch and **28** for the human batch:

| intent | have | target | remaining | batch |
|--------|------|--------|-----------|-------|
| decision | 2 | 22 | 20 | human |
| architecture | 1 | 18 | 17 | LLM |
| comparison | 1 | 5 | 4 | human |
| out-of-scope | 1 | 5 | 4 | human |
| **total** | **5** | **50** | **45** | **28 human / 17 LLM** |

Matters for BUILD_REPORT and for the stratified RAGAS comparison, where the
denominator of each stratum has to be right.


---

## 16. Corpus directory must fail loudly when empty or missing

**Status**: RESOLVED 2026-09-14

`resolve_corpus_dir()` in `verify_adversarials.py` and `audit_questions.py` now
raises on a missing or empty corpus directory rather than proceeding.

An empty corpus directory produces a **false green**: every contamination probe
finds nothing, Layer 1 reports success, and the contamination the gate exists to
catch passes through untouched. Same failure class as finding #13
(`IN_CORPUS_SUBPATHS = "macros"`), where a path matching nothing was skipped in
silence and the gate still reported green.

The general shape, worth naming because it has now appeared three times in this
repo: **a wrong path does not raise, it covers nothing, and a check over nothing
passes.** Any gate that reads files needs an explicit assertion that it actually
read some.

---

## 17. q006 rejected at grounding audit — first curation rejection

**Status**: RECORDED 2026-09-14
**Question**: "Why did the Databricks pipeline choose Liquid Clustering over
traditional partitioning for the Silver layer?"

Passed format, passed coherence checks in the validator, passed the contamination
threshold (longest verbatim span 4 words, below the 8-word rule). **Failed the
grounding audit**, which no script performs — it requires reading the cited ADR.

Three defects, verified mechanically against
`sdd-kafka-databricks/docs/adr/004_liquid_clustering.md`:

1. The question's framing presupposes a comparison the ADR never makes. Its
   Alternatives Considered are **ZORDER BY** and **no clustering**. The string
   "partitioning" appears in **no databricks ADR at all**.
2. `expected_answer` claims "MERGE INTO operations dominate Silver-layer writes"
   — "dominate" appears 0 times; the ADR never ranks Silver write types.
3. `expected_answer` claims Liquid Clustering "avoids the shuffle penalty of
   traditional partitioning" — "shuffle" appears 0 times. This is a named
   mechanism claim, exactly the class ADR-011 Commitment 3 requires a grounding
   quote for, and no quote exists because the mechanism is not in the source.

Supported portions: "aligned with the MERGE key" (the ADR's title and Decision)
and "preserving pruning" ("file pruning during MERGE").

**Why this matters beyond one question**: had q006 entered the set, Context
Recall for it would have been permanently unachievable, because the corpus cannot
supply claims it does not contain. It would have presented as a retrieval bug and
cost a day of debugging the wrong component. This is precisely the failure mode
Commitment 2 describes, caught at authoring time where it is cheap.


---

## 18. q006 first attempt — process corrective, and an inventory bug that was not there

**Status**: RECORDED 2026-09-14
**Relates to**: finding #17 (the rejection itself)

**Pattern.** The human wrote q006 with two material grounding defects on the
first attempt: a framing that presupposed a comparison the ADR never makes
("Liquid Clustering over traditional partitioning" — the real alternatives are
ZORDER BY and no clustering, and the string "partitioning" appears in no
databricks ADR), and two claims absent from the source ("dominate", "shuffle
penalty", 0 occurrences each). Both were detected by the Layer 2 style audit
against the cited file. ADR-011 Commitment 1 assumes the human reads the source
before writing; that step was skipped.

**Process corrective.** The human fetches and reads the source ADR text before
formulating a question. `--next` output is an **index reference, not a source
substitute** — it names which unit is due, not what the unit says.

**Not a finding: the suspected inventory bug does not exist.** The incident
review hypothesised that `corpus_inventory.yml` held presumed filename patterns
rather than real paths, and that `--next` had therefore reported a file that does
not exist. The inventory was audited against the filesystem:

```
ADRs in inventory: 21   present on disk: 21   divergent: 0
Files on disk absent from the inventory: none
```

`004_liquid_clustering.md` is the real filename, is what `--next` reported, and
is what the inventory holds. The hypothesised
`ADR-004-liquid-clustering-aligned-with-merge-key.md` does not exist in the repo.
The inventory was generated from `ls` in the first place, not from a pattern.

No regeneration and no re-seed were performed. Recording this explicitly so a
later reader does not go looking for an inventory defect that was never there —
and so the immutable-seed invariant is not disturbed to fix a non-problem.

**Two corrections to the incident account**, for the same reason:

- "preserving pruning" was **not** a hallucination. It is supported by the ADR's
  own wording, "file pruning during MERGE", and the audit reported it as
  supported.
- There was no Silver-versus-Gold layer error. The ADR's alignment table covers
  four `silver.*` tables alongside three `gold.*` ones, so a question about the
  Silver layer is in scope.

Two real defects, not three, and not the three first proposed. Over-attributing
errors corrupts the record in the same way under-attributing does.

---

## 19. Starter questions cited ADR paths that do not exist — coverage was 0/21

**Status**: RESOLVED 2026-09-15
**Relates to**: #16 (a check over nothing passes)

**What the sources show.** q001–q004 cited three ADR paths that exist neither in
`corpus_inventory.yml` nor in either corpus clone:

| Cited | Real file (inventory and clone) |
|-------|---------------------------------|
| `docs/adr/ADR-0029.md` (q001) | `docs/adr/0029_snowpipe_streaming_as_the_ingestion_path.md` |
| `docs/adr/ADR-007.md` (q002) | `docs/adr/007_pipeline_unification.md` |
| `docs/adr/ADR-0030.md` (q003, q004) | `docs/adr/0030_avro_and_schema_registry_as_the_contract.md` |

Two effects, both silent:

- `golden_set_coverage.py` reported `0/21 inventory ADRs covered`. `--next`
  printed `[1/21]`, where the number is covered-count + 1, not a walk position.
- `audit_questions.py::source_excerpts` substituted `— NOT FOUND —` for each
  missing file. For q001 and q002 the entire cited-source block was that one
  line (62 and 60 chars), and for q003 and q004 only the README text reached the
  prompt.

**Why nothing failed.** `validate_golden_set.py::check_sources` checks the
*shape* of each entry (`project` and `path` present, project in
`SourceProject`), never that the path exists. #18 audited the inventory against
the filesystem (21/21), not the YAML against the inventory. Same class as #13
and #16: a path that matches nothing does not raise.

**Resolution.** Paths replaced with the inventory entries. No `question` or
`expected_answer` text changed. No re-baseline is needed under ADR-011
Commitment 2, because no baseline exists yet.

**Not established by this fix.** Nothing on disk shows an audit that read these
three ADRs: `.claude/dev/reports/` does not exist. The grounding of q001–q004
against their ADRs is therefore unverified, and this entry makes no claim either
way about their content.

---

## 20. Audit cost in #11 was an estimate, and the audit truncates long sources

**Status**: RECORDED 2026-09-15
**Relates to**: #11 (the figure), #19 (the paths that shaped it)
**Pattern**: fourth correction of a recorded figure, after #6, #11 and #15.

**The figure was an estimate labelled as a measurement.** #11 records ~$0.0075
per in-scope question as "measured, not estimated", from `--dry-run`.
`audit_questions.py` computes the dry-run figure as `len(prompt) // 4` input
tokens plus a flat 150 output tokens per question. Nothing is measured.

**It was also computed over missing sources.** Re-running `--dry-run` before the
#19 fix reproduces $0.0301 / 4 = $0.0075 exactly: q001 and q002 carried a
`NOT FOUND` line instead of source text. After the fix the same formula gives
$0.0502 / 4 ≈ $0.0126. That is still an estimate and is not recorded as the cost.

**Real per-question cost: not yet measured.** No non-dry audit has run, and
`.claude/dev/reports/` does not exist. The first real Layer 2 run records actual
token usage in its report footer, and that figure replaces this gap. The #11
decision (audit cost is negligible) is not affected.

**The auditor truncates each cited source at 4,000 characters.**
`source_excerpts(..., max_chars=4000)`. `sdd-kafka-databricks/docs/adr/007_pipeline_unification.md`,
cited by q002, is 4,131 words, so the auditor reads only its opening. A claim
grounded later in a long ADR can be reported as unsupported: a false negative
that sends the author to fix a question that was correct. Not fixed here — the
limit and its replacement are a code change for a separate decision.

---

## 21. Guideline — acknowledge defects from the source, not from memory

**Status**: DECIDED 2026-09-15
**Relates to**: #18 (an incident account corrected against the source), ADR-011 Commitment 1

> When acknowledging a defect, list only what the source shows is wrong; do not
> reconstruct what "should have been" from memory. If verification is needed to
> describe the defect correctly, request the source before proposing the
> correction.

**Applies to every contributor, human or model.** It was first proposed as a
personal rule. It is recorded here at project level because a project rule is
auditable: a correction that does not cite the source it was checked against
can be flagged in review.

**Why it belongs next to ADR-011.** Commitment 1 requires verifying against the
source before *writing*. This guideline extends the same discipline to
*correcting*: a defect description is itself a claim, and it needs grounding just
as much.

**On record.** #18 documents an incident account of q006 that named more defects
than the source supports:

- a suspected inventory bug, disproved by auditing the inventory against the
  filesystem;
- "preserving pruning" as unsupported, contradicted by the ADR's own wording;
- a Silver-versus-Gold error, contradicted by the ADR's alignment table.

Each was corrected by checking the source, not by recalling it.
