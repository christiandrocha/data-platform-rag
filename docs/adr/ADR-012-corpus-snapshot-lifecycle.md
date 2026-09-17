# ADR-012 — Corpus snapshot as a shared, provenance-bearing artifact

**Status**: Accepted
**Date**: 2026-09-17

## Context

`AGENTS.md` describes the corpus clone twice, and the two descriptions cannot
both be true.

The Boundaries section says `make index-corpus` "clones to `/tmp`, extracts
relevant files, indexes, and **deletes**". The Commands section says scripts that
read the corpus "default to the newest `/tmp/dpr-corpus-*`, **created by**
`make index-corpus`", and explains why: "a GitHub Actions runner has no
`~/Documents`, so `/tmp` is the only path that works in both environments."

If the snapshot is deleted, the canonical path never exists when its consumers
run. Those consumers are not incidental: ADR-011 makes `verify_adversarials.py` a
**blocking precondition of every eval**, at `error` severity. The blocking gate
resolves to a path nothing creates, and has only ever run through a local
`CORPUS_DIR=` override that CI cannot use.

Two further gaps travel with the same decision.

**No provenance.** `corpus_inventory.yml` records `verified_against_clone:
2026-09-14` — a date, not a commit. The corpora are live repositories. An eval can
index commit X while the adversarial gate greps commit Y, and nothing compares
them. ADR-011 Commitment 2 closed this for the golden set by recording the YAML's
git SHA per run. The corpus is the other half of every score and has no
equivalent.

**Three definitions of the in-corpus file set.** `verify_adversarials.py` walks
`rglob("*")` under `docs/adr` and `contracts`; `corpus_inventory.yml` enumerates
paths by hand; the loader would imply a third. They already disagree on six
files. A gate whose scope is *wider* than the index **over-blocks**: a
contamination probe that matches Python source the system can never retrieve
rejects a valid adversarial question. This is the failure shape recorded in
dev-log #8 and #13 — a definition covering the wrong set does not raise, and the
gate reports green.

### What the boundary was protecting

Resolving the contradiction requires knowing what the rule limits. The evidence
says **scope**, not disk presence:

- The rule's own title is "Never index the target repos **as full clone**." The
  title states the rule; the sentence after it states one mechanism. The title is
  about what is *indexed*.
- The Commands passage was written deliberately to give CI a reproducible path.
  Under a disk-presence reading it is not merely imprecise, it must be deleted —
  and the CI problem it solved returns unsolved.
- There is no confidentiality to protect. Both corpora are public repositories,
  and `.env.example` carries their clone URLs as plain filled-in values
  (`CORPUS_REPO_SNOWFLAKE`, `CORPUS_REPO_DATABRICKS`), which is only acceptable
  because they are not secret. The separate "never store secrets in the repo"
  boundary is untouched by this ADR.

## Decision

**Acquisition is split from indexing**, and the extracted snapshot becomes a
shared artifact with recorded provenance.

1. **`make fetch-corpus`** shallow-clones each corpus repo, copies only
   in-corpus files into `/tmp/dpr-corpus-{timestamp}/{project}/`, writes a
   manifest, and deletes the full clone before exiting. No `.git` directory
   survives in the snapshot.

2. **The manifest** (`MANIFEST.json` at the snapshot root) records, per project:
   the repo URL, the 40-character commit SHA, and for every extracted file its
   relative path and sha256. It is a pydantic model in `contracts.py`, per
   ADR-010.

3. **One owner of the in-corpus file set**: a new `data_platform_rag/indexer/corpus.py`.
   `verify_adversarials.py` imports it; its `IN_CORPUS_SUBPATHS` constant is
   deleted. The gate and the index agree by construction, not by review.

4. **The v1 in-corpus set is enumerated explicitly**, per project:

   | Included | Excluded, and why |
   |---|---|
   | `docs/adr/*.md`, except the ADR index | `docs/adr/README.md` (snowflake only) — a table of links, not content. Indexing it produces a chunk dense in ADR titles that matches many queries and answers none |
   | `README.md` at the repo root | `contracts/*.py` (databricks, 5 files, 345 lines) — source code, already excluded by PRE_BUILD_VALIDATION Section 2. The rule they enforce is retrievable because databricks ADR 004 *discusses* `test_contracts.py`, and that ADR is indexed |
   | `dbt/macros/*.sql` (snowflake, 3 files) | `connectors/*.json` — runtime configuration, not decisions or architecture prose |
   | `contracts/*.yml` (databricks, 21 files) | `keys/`, `tests/`, `images/`, `pipelines/`, `scripts/`, `sql/`, `kafka_export/`, `observability/`, `demos/`, `presentation/`, `dagster/`, `dbt/` except `macros/` |

5. **The `schema` source type has no v1 producer, and this is recorded rather
   than left implicit.** No `.avsc` or registry-subject file exists in either
   corpus at `82a2e26`; the subjects live in a running Confluent Schema Registry,
   which `scripts/sync_metadata.py` reads over the network. `SourceType` keeps the
   value — removing it is a contract change with no benefit — but ADR-007's
   strategy row for `schema` applies to nothing in v1, and the AGENTS.md corpus
   description stops claiming "Schema Registry contracts".

6. **Retention**: `fetch-corpus` deletes older `/tmp/dpr-corpus-*` snapshots
   before writing a new one, so "newest wins" describes the only snapshot present.

7. **Both AGENTS.md passages are amended in the same commit as this ADR**, so
   they cannot drift apart again.

## Consequences

- The canonical path exists, is created by a make target, and works identically
  locally and in CI. `make verify-adversarials` runs with no override.
- Corpus provenance becomes a recorded fact. A later slice can assert *indexed
  corpus == verified corpus* by comparing SHAs, instead of trusting that two
  clones happened to match.
- The in-corpus set has one owner. The `IN_CORPUS_SUBPATHS` class of defect —
  a path that matches nothing, skipped in silence — cannot recur in the gate,
  because the gate no longer names paths.
- **Corpus bytes persist in `/tmp` between runs.** This is the change to the
  boundary. They are public files, they are removed on the next `fetch-corpus`,
  and nothing in the repo tree contains them.
- **The gate narrows by six files.** A contamination probe matching only
  `docs/adr/README.md` or `contracts/*.py` now passes where it previously failed.
  This is the intended correction, not a regression: the gate must not be wider
  than the index, or it rejects questions for matching text the system can never
  retrieve.
- The ADR index gains a numbering note. `ADR-012` was informally held by the
  `rerank_top_k` candidate in dev-log #9, which deliberately has no file. The
  number is taken here, because the register is chronological and a decision that
  exists outranks a candidate that may never be written.
- A manifest format decided now must still satisfy slice 2, which needs the SHA
  stored beside the indexed rows. Getting this wrong means a format change later.

## Alternatives considered

**Clone → index → delete, literally as specified.** Follows the Boundaries
wording exactly; no ADR and no boundary edit. Rejected: it makes the documented
default of `verify_adversarials.py` and `audit_questions.py` permanently dead
code, because the thing that creates the path also deletes it. It needs two
independent clone paths — index and eval gate — with nothing making them agree on
a commit, so the gate can pass against a corpus the index does not contain. And it
leaves the Commands section of AGENTS.md false.

**Pin-and-reclone.** `index-corpus` deletes as specified but records each SHA in
Postgres; consumers re-clone at the recorded SHA. Keeps the boundary literal and
closes provenance. Rejected: it puts a network round-trip and a clone in front of
every gate run and every audit — precisely the loop active during golden-set
curation — and it makes a gate that needs no database depend on one, just to learn
which SHA to fetch. It also fixes provenance without fixing the triple definition
of the in-corpus set.

**Git submodules pinned to corpus SHAs.** Pinned and reproducible, but the corpus
would live permanently inside this repo's working tree, under the repo root where
any tool that walks the repo meets it. Too close to the self-indexing boundary.

**Vendoring an extracted copy into `tests/data/`.** Same tree problem, and it goes
stale the moment a corpus repo gains an ADR. Tests use small hand-written
fixtures instead.

## Verification

- Two consecutive `make fetch-corpus` runs against unchanged remotes produce
  manifests with an identical per-file sha256 set.
- `find /tmp/dpr-corpus-*/ -name .git` returns nothing, and every file present is
  named in the manifest.
- `grep -c IN_CORPUS_SUBPATHS scripts/verify_adversarials.py` returns 0.
- `make verify-adversarials` with no `CORPUS_DIR=` reaches its probes.
- An ADR added to one corpus repo and not to `corpus_inventory.yml` fails the
  staleness check by name, in both directions of drift.
- An empty or missing snapshot raises in every consumer, extending the dev-log #16
  invariant to the extractor.
