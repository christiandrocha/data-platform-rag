# ADR-004 — Embedding model selection and HNSW parameter tuning

**Status**: Planned — decision during BUILD via benchmark
**Date**: — (decision pending; this ADR defines the protocol that produces it)

## Context

Two retrieval-quality knobs were left at baseline values during the DESIGN
phase, both on the assumption that they would be tuned against real data
rather than guessed:

1. **Embedding model.** `bge-small-en-v1.5` (384 dims) is the current default
   in `config.py` and is hardcoded as `VECTOR(384)` in `sql/01_schema.sql`.
   It was chosen for footprint, not for measured quality on this corpus.
2. **HNSW index parameters.** `sql/02_indexes.sql` builds with `m = 16`,
   `ef_construction = 64`, and the retrieval code is expected to set
   `hnsw.ef_search = 40` per session. All three are pgvector defaults.

These two knobs are coupled and must be decided together: embedding dimension
changes the index size, the build time, and the recall ceiling that HNSW
tuning is trying to reach. Tuning HNSW against a model that later gets
replaced wastes the tuning.

The AGENTS.md boundary "Never skip HNSW index tuning" and the Section 7
non-negotiable "the three planned ADRs (004, 005, 008) all Accepted with real
numbers" both block v1 publication on this ADR reaching Accepted.

## Decision

**Deferred to BUILD.** This ADR does not choose values — it fixes the
benchmark protocol that will, so the eventual numbers are reproducible and
the reasoning is auditable.

### Part A — Embedding model benchmark

Three candidates from the same family (same training objective, same
normalization, so the comparison isolates capacity):

| Model | Dims | Params | Approx. fp32 size |
|-------|------|--------|-------------------|
| `BAAI/bge-small-en-v1.5` | 384 | 33M | ~130 MB |
| `BAAI/bge-base-en-v1.5` | 768 | 109M | ~440 MB |
| `BAAI/bge-large-en-v1.5` | 1024 | 335M | ~1.3 GB |

Sizes above are fp32 weights only. Runtime working set is substantially
larger — see the benchmark environment note below for the measured figure.

Each candidate is measured on the full 50-question golden set, with the
reranker and all retrieval parameters held constant:

| Metric | Source | Why it matters |
|--------|--------|----------------|
| RAGAS Context Recall | `make eval-ci` | Primary quality signal — did we retrieve what was needed |
| RAGAS Context Precision | `make eval-ci` | Guards against recall bought with noise |
| Query latency (embed + retrieve, p50) | benchmark script | User-facing cost of a bigger model |
| Index build time | `make reindex` | Operational cost of a reindex |
| Resident memory at steady state | benchmark script | Deployment gate — see below |

**Measurement is unconstrained; deployment is gated.** These are two separate
steps, deliberately.

*Step 1 — measure everything locally.* All three candidates are benchmarked on
the local development machine (8 GB RAM). No candidate is dropped for
footprint at this stage; the point is to learn the quality ceiling of this
corpus, including the part of it we may not be able to ship.

`bge-large` is the tight one: measured working set ~3.4 GB for the model plus
the reranker, on top of baseline system usage. Running it requires closing
Cursor, browser tabs, and other memory-heavy applications beforehand. That is
a documented precondition of the run, not an improvisation at execution time.

**If the run OOMs, it is aborted and the candidate is recorded as "not
measurable in the current environment."** It is never backfilled with an
estimate, an extrapolation from `bge-base`, or a figure from a model card.
A stated gap in the record is worth more than a plausible invention, and per
AGENTS.md an unmeasured number has no place in an ADR.

*Step 2 — apply the deployment gate.* Streamlit Community Cloud's free tier
has a documented resident-memory ceiling (~1 GB; confirm against current
Streamlit docs at benchmark time, not from this table), shared by the
embedding model, the reranker (`bge-reranker-base`, ~1.1 GB fp32), and the
Streamlit process. A candidate that cannot coexist with the reranker inside
that ceiling is **not deployable in v1** — but its measured scores stay in
the record.

`bge-large` is the expected case. If it wins on quality, this ADR records the
outcome in exactly that form — *"bge-large wins Context Recall by X over the
shipped model, but exceeds the v1 memory ceiling by Y MB and is therefore not
deployable in v1"* — with both numbers measured, not estimated. That sentence
is a deliverable, not a footnote: it converts an unknown into a quantified,
deliberate deferral, and it becomes the trigger condition for the v2 hosting
decision (paid tier, or self-hosted runtime).

**Three possible outcomes per candidate.** They are not interchangeable, and
the record must say which one applies:

| Outcome | Meaning | Enters the decision rule? |
|---------|---------|---------------------------|
| Measured, deployable | Scores recorded; fits the v1 memory ceiling | Yes |
| Measured, not deployable | Scores recorded; exceeds the ceiling | No — recorded as measured headroom |
| Not measurable | Run aborted (OOM); no scores exist | No — recorded as a gap, with the abort reason |

**Decision rule.** Ship the *smallest deployable* candidate whose Context
Recall is within 0.02 of the best *deployable* candidate's. Ties broken by
latency, then by footprint. A larger model wins only by clearing that 0.02
margin — a measurable lift, not a rounding difference. Non-deployable
candidates never enter this rule; they are recorded as measured headroom.

### Part B — HNSW tuning, run against the winning model only

Tuning runs after Part A concludes, on the winner's embeddings:

1. Baseline: build with `m = 16`, `ef_construction = 64`; sweep
   `hnsw.ef_search` over {20, 40, 80, 160} at query time; record Context
   Recall and p50 latency at each point.
2. If Context Recall plateaus below 0.90, rebuild with `m` ∈ {24, 32} and
   repeat the `ef_search` sweep.
3. If build time exceeds 60s at the chosen `m`, cap `m` and buy recall with
   `ef_search` instead — build time is paid on every `make reindex`.

`ef_search` stays a per-session parameter (`SET LOCAL`), never a global.
It is a per-query latency/accuracy trade-off and belongs in the query path.

## Consequences

**Positive**:
- The embedding choice becomes a measured decision on this corpus, not an
  inherited default. That is the claim the README makes about the project.
- Tuning HNSW after the model is fixed avoids discarding the tuning work.
- The decision rule is written before the numbers exist, so it cannot be
  retrofitted to justify whichever model happens to win.

**Negative / accepted trade-offs**:
- The benchmark costs three full indexing passes plus three golden-set eval
  runs. At 50 questions with a Claude call each, that is real API spend
  (see `.claude/kb/langfuse/cost-tracking.md` for per-query cost).
- The `bge-large` run requires preparing the benchmark machine (closing
  Cursor, browser, other memory-heavy apps) and is the one candidate that
  may not complete at all on 8 GB. That risk is accepted deliberately: the
  alternative — substituting an estimate — would put an unmeasured number
  into an ADR, which AGENTS.md forbids.
- Footprint measured locally is indicative only. The Step 2 gate must be
  confirmed against the Streamlit Cloud environment itself, since that is
  where the ceiling actually binds.

**Schema migration — an explicit consequence, not a side effect**:

The embedding dimension is not configuration. `config.py` holds
`embedding_model` as a string, but the dimension that matters lives in the
DDL: `sql/01_schema.sql` declares `embedding VECTOR(384)`. Changing the env
var alone migrates nothing — pgvector enforces the declared dimension, so a
768-dim vector written against a `VECTOR(384)` column fails at insert time
during `make index-corpus`. That failure is loud, which is good. What it is
not, is automatic.

If the benchmark winner is anything other than `bge-small-en-v1.5`, all of
the following are required, in order, and belong in the BUILD estimate:

1. `sql/01_schema.sql` — change `VECTOR(384)` to the winner's dimension.
2. `sql/02_indexes.sql` — drop and rebuild `idx_chunks_embedding_hnsw`. Both
   index size and build time scale with dimension.
3. `make reindex` — full destructive rebuild of every stored embedding. There
   is no in-place migration path; the old vectors are not convertible.
4. `sql/99_verify.sql` — regenerate the EXPLAIN ANALYZE baseline, which is
   dimension-sensitive and otherwise becomes a false regression signal.
5. Any RAGAS baseline or README badge recorded before the switch is void.
   Per AGENTS.md, badges show "pending" until a post-migration `make eval-ci`
   run replaces them. They are not carried over.

This is the main reason Part B runs only after Part A concludes: HNSW
parameters tuned against 384-dim vectors do not transfer to 768 or 1024 dims.
Tuning before the model is fixed throws the tuning away.

## Alternatives considered

- **Keep `bge-small` undocumented and skip the benchmark.** Rejected: it
  leaves the central retrieval-quality knob unjustified, and AGENTS.md
  forbids shipping untuned HNSW parameters.
- **Hosted embedding APIs (OpenAI `text-embedding-3`, Cohere Embed,
  Voyage).** Rejected for v1: adds a second paid external dependency, a
  per-indexation cost, and a network hop in the query path. The stack's
  local-embedding decision is deliberate (see `docs/PRE_BUILD_VALIDATION.md`
  Section 3 exclusions). Revisit only if all three local candidates plateau
  below the 0.80 Context Recall non-negotiable.
- **Cross-family comparison (`e5`, `gte`, `nomic-embed`).** Rejected as
  scope: a three-family × three-size matrix is nine benchmark runs for a
  50-question golden set that cannot resolve differences that fine. The BGE
  family is a defensible single-family choice; a cross-family sweep is a v2
  exercise if the winner disappoints.
- **Matryoshka / dimension truncation on a larger model.** Interesting
  (large-model quality at small-model storage), but `bge-*-en-v1.5` is not
  Matryoshka-trained, so truncation degrades unpredictably. Out of scope.
- **IVFFlat instead of HNSW.** Already settled in `sql/02_indexes.sql`: no
  training step, better recall at this scale, supports incremental inserts.
  Not reopened here.

## Verification

This ADR is promoted from Planned to Accepted when all of the following are
recorded in its Consequences section, with timestamps:

- [ ] The benchmark table, filled in with measured values for all three
      candidates (or a documented disqualification for any not run).
- [ ] Each candidate resolved to exactly one of the three outcomes above,
      with its reason recorded. A candidate marked "not measurable" carries
      the abort reason, never a substituted estimate.
- [ ] The winning model, named, with the decision rule shown to select it.
- [ ] For any candidate measured but not shipped: the "wins by X, not
      deployable by Y" sentence, with both numbers measured.
- [ ] Final `m`, `ef_construction`, and `ef_search`, with the sweep data
      that justifies them.
- [ ] If the winner is not `bge-small-en-v1.5`: the five migration steps in
      Consequences executed and checked off.
- [ ] `sql/02_indexes.sql` parameters matching the values above.
- [ ] `sql/99_verify.sql` EXPLAIN ANALYZE baseline regenerated against the
      final index.

Benchmark artifacts land in `.claude/dev/reports/`. Per AGENTS.md, no number
in this ADR may be written by hand — every value comes from a `make eval-ci`
run or the benchmark script.
