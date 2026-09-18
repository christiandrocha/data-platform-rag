# DESIGN: Retrieval — the executor, and a way to run a question

> Implements [DEFINE.md](DEFINE.md), Clarity 13/15. Direction from
> [BRAINSTORM.md](BRAINSTORM.md), Option 3.
> Decision of record: [ADR-014](../../../../docs/adr/ADR-014-source-recall-before-ragas.md).
> Implements the strategy already decided in ADR-003.

## Metadata

| Field | Value |
|-------|-------|
| Feature | retrieval |
| Depends on | [DEFINE.md](DEFINE.md), Clarity Score 13/15 |
| Status | Draft |
| ADR needed | Yes — [ADR-014](../../../../docs/adr/ADR-014-source-recall-before-ragas.md), the retrieval metric. ADR-003 gains an amendment; see *Deviations from ADR-003* |

## Architecture overview

Three layers, deliberately separated by what they need in order to be tested:
SQL that needs a database, orchestration that needs a model, and a CLI that
needs a person.

```
make ask q="..."                     make retrieval-recall
      │                                     │
      ▼                                     ▼
scripts/ask.py                       scripts/retrieval_recall.py
      │                                     │  reads expected_source_paths
      └──────────────┬──────────────────────┘  from the golden set
                     ▼
         retrieval/pipeline.py :: retrieve()
                     │  question text + collections
                     ├─► embedder.embed_query()        (model)
                     └─► hybrid_search.search()        (database)
                              │
                              ▼
                   HYBRID_QUERY, one round trip
                   dense rank ⊕ sparse rank, RRF k=60
                              │
                              ▼
                   list[RetrievedChunk]   (ADR-010)
```

**New**

- `data_platform_rag/retrieval/pipeline.py` — `retrieve()`, the one function
  DEFINE asks for. Named per the repo map, which already reserves
  `retrieval/pipeline.py`; it grows to orchestrate intent and reranking later.
- `scripts/ask.py` — the development instrument.
- `scripts/retrieval_recall.py` — the ADR-014 measurement.
- `docs/adr/ADR-014-source-recall-before-ragas.md`.

**Changed**

- `retrieval/hybrid_search.py` — placeholders, the `SELECT`, the limits, the
  sentinel, and a real `search()` function.
- `tests/unit/test_hybrid_search_query.py` — it currently pins the `$1` form, so
  it changes with the query. Corrected, not deleted: the assertions move to the
  psycopg form and gain the fields the contract needs.
- `Makefile` — `ask`, `retrieval-recall`.
- `AGENTS.md` — the two new commands, and the repo-map target count, which still
  read 14 after slice 2 raised it to 25.
- `docs/adr/index.md` — the ADR-014 row.
- `docs/adr/ADR-003-hybrid-retrieval-rrf.md` — Amendment 1, below.

**Unchanged**: `contracts.py`, `config.py` fields, every `sql/` file, the whole
`indexer/` package. This feature reads; it writes nothing to Postgres.

## Deviations from ADR-003 found while designing

**The sentinel does not contribute zero.** ADR-003 states that a chunk appearing
in only one ranked list has its missing side count "as rank infinity →
contributes zero". The SQL uses `COALESCE(dense_rank, 999)`, and
`1/(60 + 999) = 0.000944` — not zero, and **5.8 % of a rank-1 contribution**
(`1/61 = 0.016393`).

The effect is small but systematic: every one-sided match receives the same
constant bonus, so one-sided matches are inflated relative to what ADR-003
specifies. It does not reorder one-sided matches among themselves; it shifts them
as a group against two-sided ones.

**Decision: fix the SQL to match the ADR**, with `COALESCE(1.0/(60 + rank), 0)`
per side rather than a sentinel rank. ADR-003 is the decision; the SQL is an
implementation of it that drifted, and 999 is a magic number that reads like a
limit and behaves like a bias. Recorded as **ADR-003 Amendment 1** at BUILD,
following the ADR-007 Amendment 1 precedent rather than superseding.

This is stated here, before implementation, because the recall baseline ADR-014
records must be measured against the corrected formula. A baseline captured
under the drifted one would have to be thrown away.

## Data contracts

**No contract changes.** `RetrievedChunk` and `ChunkMetadata` are used exactly as
they stand. What changes is that the `SELECT` finally returns enough columns to
construct them:

| `ChunkMetadata` field | Required | In the current `SELECT` |
|---|---|---|
| `source_project` | yes | yes |
| `source_type` | yes | **no** |
| `source_path` | yes | yes |
| `chunk_index` | yes | **no** |
| `token_count` | yes | **no** |
| `source_anchor`, `adr_id`, `topic`, `status`, `keywords` | no | `adr_id` only |

The widened `SELECT` returns all ten, plus `id`, `content`, `collection`,
`dense_dist`, `sparse_score` and `rrf_score`. Every optional field is carried
rather than dropped, because `source_anchor` is what makes a citation point at a
section rather than a whole ADR, and the curator's question is about sections.

### On provenance in the result — resolved, no field added

DEFINE asked whether `RetrievedChunk` should carry `snapshot_id`, given ADR-013
made provenance first-class. **It should not**, and the reasoning belongs here
rather than in an ADR because it declines a change rather than making one.

The commit a chunk came from is a property of the **indexing run**, not of the
chunk. The schema enforces one live snapshot per project, so every chunk of a
project shares one commit by construction; per-chunk provenance would repeat two
values across 304 rows and could never disagree. When an answer needs to name its
corpus commit, it reads `corpus_snapshot` once — and `make index-corpus-verify`
already asserts that what is indexed is what the manifest verified. Adding a
field to `RetrievedChunk` would put a join in every retrieval to carry a constant.

Revisit only if the one-snapshot-per-project invariant is ever relaxed.

## Interfaces

### `retrieval/pipeline.py`

```python
def retrieve(
    question: str,
    collections: list[Collection] | None = None,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Embed a question and return fused, ranked chunks. Opens its own connection."""
```

`collections=None` means both, which is the DEFINE non-goal about intent
classification made explicit in a default rather than hidden in a branch. An
empty list still raises — "no collections" is a caller error, not a request for
everything. `top_k=None` reads `settings.hybrid_top_k`.

### `retrieval/hybrid_search.py`

```python
def search(
    conn: psycopg.Connection,
    *,
    query_text: str,
    query_vector: Sequence[float],
    collections: list[Collection],
    top_k: int,
) -> list[RetrievedChunk]:
    """Run the fused query. Takes an embedding; does not create one."""
```

The split is deliberate and mirrors `indexer/writer.py`: the layer that touches
the database takes an open connection and no model, so integration tests can
drive it with a fixed vector and assert on ranking without loading
`sentence-transformers`. `build_hybrid_query` keeps its name and finally uses its
argument.

### Commands

| Command | Behaviour |
|---|---|
| `make ask q="..."` | Retrieve and print. `COLLECTIONS=decisions` and `TOP_K=` optional |
| `make retrieval-recall` | ADR-014 measurement over the golden set; writes `.claude/dev/reports/retrieval-recall-{timestamp}.json` |

**What `make ask` prints** — a DEFINE open question, resolved as two views:

```
 #  rrf     dense  sparse  source
 1  0.0328  0.154  0.0912  sdd-kafka-snowflake-2/docs/adr/0029_….md [Alternatives considered]
 2  0.0161  0.201  —       sdd-kafka-databricks/docs/adr/001_….md   [—]
```

Default is one line per chunk: rank, the three scores, and the citation with its
anchor. A `—` in a score column means that chunk was not in that side's ranked
list, which is information the reader needs and a `0.0` would disguise. `--full`
prints chunk text as well. The default serves the curator's actual question —
"did my anchor come back, and where" — and `--full` serves "why did this rank".

### Config

No new fields. `settings.hybrid_top_k` (20) stops being a literal in SQL, and the
RRF constant `k = 60` becomes a module constant named after ADR-003 rather than
an inline 60 appearing three times. It is **not** promoted to settings: ADR-003
fixes it at 60 from the Cormack paper, and tuning it is ADR-008's business under
RAGAS, not a runtime knob to be turned by accident.

## Retrieval and RAG-specific concerns

- [x] **Does this affect chunking?** No. `indexer/` is untouched.
- [x] **Does this touch the HNSW index? Reindex needed?** No index changes and no
  reindex. The dense side finally *uses* the HNSW index — and at 304 rows the
  planner will keep choosing a sequential scan, exactly as `sql/99_verify.sql`
  section 4 already records. That is correct and this feature does not fight it.
- [x] **Does this change the query pattern?** It introduces the first real one.
  `sql/99_verify.sql` sections 4 and 5 are synthetic approximations of it; BUILD
  captures an `EXPLAIN ANALYZE` of the actual fused query as the new baseline.
  One thing to watch: `ts_rank_cd` over `content_tsv` is computed for every
  candidate row in the `candidates` CTE before either side is limited, so the
  sparse cost is paid on the whole collection. At 304 rows that is nothing; it is
  the first thing to look at if this ever gets slow.
- [x] **Does this change RAGAS metrics? Regression test needed?** No RAGAS metric
  exists. ADR-014 defines what stands in its place, and BUILD records the first
  reading as the baseline ADR-004 and ADR-005 will be measured against.

## Alternatives considered

The scope alternatives (executor alone, executor + intent classifier, full
vertical slice) are argued in BRAINSTORM. The metric alternatives (MRR, nDCG,
waiting for RAGAS) are argued in ADR-014. Not repeated.

Two are local to this DESIGN:

- **Two queries fused in Python instead of one SQL round trip.** Easier to unit
  test — RRF becomes a pure function over two lists — and it would let the two
  sides be limited independently. Rejected: ADR-003 puts fusion in the query, the
  round trip doubles, and a pure-function RRF can be tested anyway by asserting
  on rankings from fixed vectors. Revisit if the one query proves untunable under
  ADR-008.
- **`make ask` calling the same code path as a future UI.** Tempting, and
  premature: no pipeline exists to share yet, and designing `retrieve()` around a
  UI that has not been designed would be guessing at its needs. `retrieve()` is
  shaped by the contract, not by either caller.

## Test plan

**Unit** (no database, no model, no network)

- `test_hybrid_search_query.py`, corrected: the query contains no `$1`/`$2`/`$3`;
  it contains `%s`; it selects every field `ChunkMetadata` requires; `LIMIT`
  appears with a placeholder, not a literal 20; the RRF expression contributes
  zero rather than a sentinel rank for a missing side.
- `build_hybrid_query` rejects an empty list *and* an unknown collection name,
  and actually varies with its argument.
- Row-to-contract mapping: a fixed fake row tuple becomes a valid
  `RetrievedChunk`, and a row missing a required field raises rather than
  substituting a default.

**Integration** (Postgres, fixed vectors, no model — same posture as slice 2)

- Seeded chunks with hand-chosen vectors: the ranking is the one RRF predicts,
  computed by hand in the test.
- A chunk matching only the sparse side is returned, and its `rrf_score` equals
  the sparse contribution alone — the ADR-003 amendment, asserted rather than
  assumed.
- `collections=["decisions"]` returns nothing from `architecture`, and vice versa.
- An empty `chunks` table returns `[]` rather than raising.
- A question matching nothing textually still returns dense results.
- `top_k` is honoured, and the result is ordered by `rrf_score` descending.
- Determinism: the same call twice returns identical ids in identical order.

**Manual verification** (real model, real 304 rows, recorded in BUILD_REPORT)

- `make ask` on each of the five golden-set questions, output pasted.
- `make retrieval-recall` — the ADR-014 baseline: three recall numbers over six
  declared paths, plus five top scores including q005's.
- Specifically: whether q002 now retrieves `007_pipeline_unification.md`, which
  dense-only did not. Either answer is a result; neither is a pass condition.
- `EXPLAIN ANALYZE` of the fused query against the real index.

## Rollout plan

**Migration order.** None. No schema change, no reindex, nothing written. The
feature is additive and reads a database that already exists.

**Feature flag.** None. Nothing user-visible ships: the Streamlit app is still a
placeholder and `make ask` is a development instrument.

**Rollback.** Reverting the commit restores a `hybrid_search.py` whose query
cannot execute and two commands that do not exist. Nothing persists, so there is
no state to unwind — which is the whole of the rollback plan for a read-only
feature.

**CI.** `ci.yml` needs no change. The unit tests stay offline; the integration
tests use the existing `_test` database fixture and fixed vectors, so no model is
downloaded. `make retrieval-recall` is deliberately not wired into CI (ADR-014
§4).

## Open questions

From DEFINE, all resolved or explicitly deferred:

- [x] **Does `make ask` use `embed_query`, and is the cache correct here?** Yes,
  and yes. A CLI process embeds one question and exits, so the `lru_cache` never
  hits and costs one entry; it is correct for the UI that will share the code
  later, which is what the cache was written for.
- [x] **What does `make ask` print?** Two views, compact by default, `--full` for
  chunk text. See *Interfaces*.
- [x] **Where does the recall measurement live?** A script, `make
  retrieval-recall`, writing a timestamped JSON artifact. Not a CI test — ADR-014
  §4 argues why.
- [x] **Is `dense_distance` right for a sparse-only match?** Keep it. The
  `candidates` CTE computes the distance for every row, so the value is real and
  not a placeholder; it simply is not what ranked that chunk. The `—` in the
  `make ask` output marks which side actually ranked it, which is where the
  confusion would otherwise arise.
- [x] **Should the result carry `snapshot_id`?** No. Reasoning in *Data
  contracts*.
- [ ] **Deferred: the intent classifier.** `collections=None` defaults to both.
  Whether choosing them needs an LLM is its own brainstorm, per BRAINSTORM
  Option 2. `make ask --collections` exists precisely so that question can be
  answered by experiment rather than argument.
- [ ] **Deferred: `ts_rank_cd` over the full collection before limiting.** Noted
  above as the first place to look if retrieval gets slow. Not addressed at 304
  rows, where addressing it would be optimisation without a measurement.

## Deferred exit criterion

`make eval` is deferred for the third consecutive feature, with the cause DEFINE
records: RAGAS needs generation, which this feature does not build, and a golden
set larger than 5 of 50.

ADR-014 exists so that this deferral stops meaning "no evidence". Source recall
at k is not a substitute for RAGAS and is not reported as one — but it is a
retrieval-quality number where previously there was none, and BUILD produces the
first one.
