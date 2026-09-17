# BRAINSTORM: corpus-indexing

> Free exploration. No commitments. No commits from this file alone.

## Date
2026-09-15

## Prompt

Feature 2. The job is unchanged from the archived v0 draft
(`.claude/sdd/archive/corpus-indexing-brainstorm-v0.md`): clone the two corpus
repos, load the in-corpus files, chunk them per ADR-007, embed, and write to
`chunks`.

**Carried forward, not re-litigated.** The archive note records Option 1 of v0 as
the approved preference: a model-agnostic pipeline, where the ADR-004 benchmark is
a *consumer* of the pipeline and not a blocker on it. This brainstorm starts from
that point.

**Why start now, while the golden set is at 5 of 50.** The archive's corrected
order puts the ADR-004 benchmark before this feature, but it also says the
"preliminary parameterised pipeline *is* Option 1, run early". The benchmark can't
run without that pipeline, and the 45 remaining questions are a human long pole
measured in days. Building the pipeline now, in parallel with curation, doesn't
reorder anything. It removes the wait. The consequence is that ADR-004 can't be
concluded inside this feature, so DEFINE can't have RAGAS-based success criteria
(see Open question 12).

**What v0 did not see.** Two things came out of reading the repo and a shallow
clone of both corpora (to the session scratchpad on 2026-09-15:
`sdd-kafka-snowflake-2@82a2e26`, `sdd-kafka-databricks@f1295df`). They make
*corpus lifecycle* the open architectural decision, ahead of anything in the
pipeline itself.

1. **AGENTS.md contradicts itself about the clone.** The Boundaries section says
   `make index-corpus` "clones to `/tmp`, extracts relevant files, indexes, and
   **deletes**." The Commands section says scripts "default to the newest
   `/tmp/dpr-corpus-*`, **created by** `make index-corpus`." Both can't be true.
   If the clone is deleted, the canonical path that `verify_adversarials.py` and
   `audit_questions.py` resolve to never exists when they run. ADR-011 makes the
   first of those a *blocking* precondition of every eval. Dev-log #14 already
   deferred exactly this ("what does not exist yet is the thing that creates the
   directory") to this feature.
2. **Nothing records which corpus commit anything was measured against.**
   `corpus_inventory.yml` says `verified_against_clone: 2026-09-14`, which is a
   date, not a SHA. The index won't record one either, and neither will the
   adversarial gate. The corpora are live repos, so an eval can index commit X
   while the gate greps commit Y, and no check compares the two. ADR-011
   Commitment 2 closed this hole for the golden set (the YAML's git SHA is
   recorded per run), but not for the corpus, which is the other half of every
   score.

## Options considered — corpus lifecycle and provenance

### Option 1: Clone → index → delete, literally as specified

`scripts/index_corpus.py` does what its stub docstring says: clone to
`/tmp/dpr-corpus-{ts}/`, index, `rm -rf`. The adversarial gate and the auditor
keep their `--corpus-dir` override. CI's eval job clones separately.

- **Pros**
  - Follows the AGENTS.md Boundaries wording exactly. No ADR, no boundary edit.
  - Smallest surface: one script, no new artifact.
- **Cons**
  - The documented default for `verify_adversarials.py` and `audit_questions.py`
    becomes permanently dead code, because the thing that creates it also deletes
    it. Every run needs an override, which dev-log #14 accepted for local dev
    only.
  - It needs two independent clone code paths (index and eval gate), and nothing
    makes them agree on a commit. The gate can pass against a corpus the index
    doesn't contain. The shape matches dev-log #8 and #13: nothing raises, and the
    gate reports green.
  - Leaves the Commands section of AGENTS.md false.

### Option 2: Extracted snapshot as the shared artifact

Split acquisition from indexing. A new `make fetch-corpus` clones each repo,
copies **only the in-corpus files** into `/tmp/dpr-corpus-{ts}/{project}/`,
writes a `MANIFEST` (repo URL, commit SHA, relative path + sha256 per file), and
deletes the full clone immediately. `index-corpus`, `verify-adversarials`,
`audit-adversarials`, and the inventory staleness check all consume that
snapshot. The index writes the manifest's SHAs to the database, so eval can
assert *indexed corpus == verified corpus* before scoring.

- **Pros**
  - Resolves dev-log #14 as written: the canonical `/tmp/dpr-corpus-*` path
    exists, is created by a make target, and works the same locally and in CI.
  - Corpus provenance becomes a recorded fact, the same way ADR-011 records the
    golden set's. A corpus-SHA mismatch fails loudly instead of silently changing
    what is being measured.
  - Forces **one** definition of the in-corpus file set, owned by the extractor.
    Today it is written independently in `verify_adversarials.py`
    (`IN_CORPUS_SUBPATHS`), in `corpus_inventory.yml`, and implicitly in the
    loader to be written. They already disagree (Open question 3), and a
    disagreement of this shape is exactly how dev-log #13 happened.
  - The ADR-011 inventory staleness check turns into a set difference between
    the manifest and the inventory.
- **Cons**
  - Corpus bytes persist on disk after indexing. That is a change to an AGENTS.md
    boundary, so by the repo's own rule it needs **an ADR before code**, plus
    edits to both AGENTS.md passages.
  - New surface: a make target, a manifest format (a pydantic model, per ADR-010),
    and somewhere in Postgres to store corpus SHAs. That is a schema change.
  - Snapshots accumulate in `/tmp`. "Newest wins" plus no cleanup (dev-log #14)
    needs an explicit retention rule.

### Option 3: Pin-and-reclone

`index-corpus` deletes as specified, but first records each repo's commit SHA in
Postgres. Consumers that need corpus text later (gate, auditor) re-clone **at the
recorded SHA** through a shared `corpus` module.

- **Pros**
  - Keeps the "deletes" boundary literally while still closing the provenance
    gap.
  - Consumers can't drift from the index, because they fetch the exact commit it
    was built from.
- **Cons**
  - Network plus a clone on every gate run and every audit. Local iteration on
    curation (many `make audit-adversarials q=…` calls) gets slow, and that is
    precisely the loop that is active right now.
  - Makes the gate depend on a database, which it doesn't need today. Running
    `verify-adversarials` would require an indexed Postgres just to learn which
    SHA to clone.
  - The in-corpus file-set definition still has to be shared between loader and
    gate. Option 3 fixes provenance but not the triple definition.

## Discarded early

- **Revisiting v0 Option 2 (hardcode 384) or Option 3 (benchmark spike)**:
  settled by the archive note.
- **Git submodules pinned to corpus SHAs**: pinned and reproducible, but the full
  corpus would live permanently inside this repo's working tree. That violates
  the full-clone boundary, and it puts corpus files under the repo root, where
  any tooling that walks the repo (ruff, the gate's `rglob`, a future indexer
  bug) meets them. It is too close to the self-indexing boundary.
- **Vendoring an extracted corpus copy into `tests/data/`**: same problem, plus
  it goes stale the moment a corpus repo gains an ADR. Tests use small
  hand-written fixtures instead.
- **LLM-derived `topic` or `keywords` at index time**: it puts a paid,
  non-deterministic call inside indexing, which breaks the rule that re-running
  on unchanged sources yields identical rows (ADR-007 needs determinism for
  `chunk_index`, and the same logic applies to metadata).
- **Keeping the full clone around**, **webhook ingestion**, **parallel
  embedding**, **dedicated vector DB**, **committing embedding JSON**: all
  discarded in v0 for reasons that still hold.

## Emerging preference

**Option 2**, pending one decision that is Christian's to make: whether the
AGENTS.md "deletes" boundary exists to limit *scope* (never index `.claude/`
internals, vendored `dbt_packages/`, or the full tree) or to limit *disk
presence* (no corpus bytes survive the run).

- If it is about scope, Option 2 keeps its intent: only in-corpus files survive,
  and the full clone is still deleted. What changes is the wording and an ADR.
- If it is about disk presence, **Option 3** is the answer. The slower curation
  loop is its accepted cost.

Option 1 is ruled out either way, because it leaves the blocking eval gate
without a defined corpus, and ADR-011 says that gate is `error` severity.

**Internal build sequence, measure before writing.** The first slice should be
extraction plus chunking with a `--dry-run` token report: no database and no
embedding writes, counted with the model tokenizer as ADR-007 Verification
requires. The evidence says ADR-007's fail-loud rule may fire on the very first
real run.

- 10 of 21 ADR files exceed 480 *whitespace-separated words*:
  - Snowflake: 0019, 0020, 0027, 0029, 0030.
  - Databricks: 005, 006, 008, 009, 007. Databricks 007 is 4,131 words.
- The largest contiguous fenced block or table in `sdd-kafka-snowflake-2/README.md`
  is 429 words, which is close to the 480 budget.

**These are word counts, not token counts. No token count has been measured.**
Whether any atomic block exceeds 480 tokens is unknown until the dry run runs. If
one does, the next step is a human decision under ADR-007 rule 4 (reformat the
source, or record an exception), not code. It is far cheaper to learn that before
the writer and DDL exist.

**What would change our mind.**
- Christian reads the boundary as disk presence: choose Option 3.
- The dry run shows ADR-007 needs amending before the corpus can be indexed at
  all: the feature pauses for an ADR-007 revision, and lifecycle waits.

## Open questions for DEFINE

1. **Lifecycle ADR and boundary edits.** Option 2 or 3 needs a new ADR plus edits
   to both AGENTS.md passages, applied in the same pass so they can't disagree
   again. The ADR number is unresolved: ADR-012 is informally held by the
   `rerank_top_k` candidate (dev-log #9), which deliberately has no file.
2. **Collection mapping: v0 was wrong that no rule exists.** ADR-002 Context
   already defines it by source kind: `decisions` are "the ADRs from both", and
   `architecture` is "READMEs, macros, YAML data contracts, and other technical
   documentation". Proposed rule: `adr → decisions`, everything else →
   `architecture`, derived from `source_type` and citing ADR-002, with no new
   ADR. The correction should be recorded rather than silently absorbed.
3. **The in-corpus file set is defined three ways, and they disagree.**
   `verify_adversarials.py` greps `rglob("*")` under `docs/adr` and `contracts`,
   so it covers files that `corpus_inventory.yml` excludes:
   - `sdd-kafka-snowflake-2/docs/adr/README.md` (an ADR index, 579 words)
   - five Python files in `sdd-kafka-databricks/contracts/` (`__init__.py`,
     `dlt_adapter.py`, `loader.py`, `pydantic_models.py`, `spark_schema.py`)

   A gate whose scope is wider than the index **over-blocks**: a probe that
   matches Python code the system can never retrieve rejects a valid
   adversarial. We need one owner and one decision per file: index it (as what
   `source_type`?) or exclude it from the gate too.
4. **`schema` source type has no producer.** At `sdd-kafka-snowflake-2@82a2e26`,
   no `.avsc` or registry subject files exist. Only ADR-0030 *discusses* the
   Schema Registry. That leaves `SourceType` with a value nothing emits, ADR-007
   with a strategy row with nothing to apply to, and AGENTS.md claiming "Schema
   Registry contracts" as corpus. Decide: find where the subjects actually live,
   or scope `schema` out of v1 and correct AGENTS.md. Either way the claim must
   stop being unbacked.
5. **ADR status can't be derived from the file alone.** `Status` lines are free
   prose ("Resolved on 2026-08-11 — the premise was false"; 009: "Accepted **with
   partial reversion 2026-07-02**"). Worse, supersession lives in the
   *superseding* ADR's title: databricks 007 "(Supersedes ADR-006's
   Exclusions)", 006 "(Overrides ADR-03 Scope)". Meanwhile 006's own status just
   says `Accepted`. A first-word mapping to `ADRStatus` would mark 006 fully
   accepted, which is the "superseded decision cited as current" failure ADR-007
   put status in the preamble to prevent. Options:
   - normalized `status` column plus the verbatim status line in the preamble
   - a hand-maintained supersession map next to the inventory
   - both
6. **`adr_id` format.** There are three spellings in the corpus: filenames `0019_…`
   / `006_…`, H1 `# ADR 0019 —` / `# ADR 001 —`, and cross-references `ADR-006`
   / `ADR-03`. Repo comments assume `ADR-0019`. Pick one canonical form, and
   decide whether it is project-qualified: the column is indexed without
   `source_project`, and `ADR 006` is meaningful only within its repo.
7. **`Chunk` vs `ChunkMetadata`** (dev-log #1, owned by this feature). The lean
   carried from the dev log is to delete `Chunk`, the option closer to ADR-010.
8. **`topic` and `keywords` have no source.** No corpus ADR has frontmatter. Lean
   for v1: write `NULL` for both. The schema already defines `keywords IS NULL`
   as "extraction did not run", which is honest. `topic` would need a
   hand-maintained map, and nothing in v1 retrieval reads it.
9. **Rebuild semantics.** `make reindex` runs `TRUNCATE` *outside* any transaction
   and then indexes. If ADR-007's fail-loud assertion trips mid-run, the result is
   an empty index. Lean: chunk and assert the *whole* corpus before the first
   write, then replace rows in one transaction. At this corpus size, upsert buys
   nothing that truncate-in-a-transaction doesn't, and it still orphans rows when
   `chunk_index` shifts (ADR-007 Consequences).
10. **Benchmark tables at non-384 dimensions** (v0 question 5): still the
    mechanism the carried-forward Option 1 depends on.
11. **Inventory staleness check** (ADR-011 Consequences assigns it to this
    feature's BUILD). It is a set difference under Option 2 and a separate clone
    under Option 3.
12. **Unsatisfiable exit criterion.** `WORKFLOW_CONTRACTS.yaml` build exit
    requires "make eval shows no regression on golden set". No retrieval or
    generation exists, and the set is at 5 of 50. DEFINE must mark this
    explicitly deferred, with the reason, and list structural acceptance tests in
    its place: the 512-token assertion, deterministic keys across two runs, row
    count per file matching the manifest, and corpus SHAs recorded.
13. **Snapshot retention and "newest wins"** (dev-log #14). Under Option 2 this
    needs a rule, for example: `fetch-corpus` deletes older snapshots, or
    consumers select by the SHA the index recorded instead of by mtime.

## Next step
- [ ] Write DEFINE if a clear direction emerged
- [ ] Or park with `status: Parked` and revisit

Direction: Option 2, conditional on the boundary-intent question above. DEFINE
pending user confirmation.
