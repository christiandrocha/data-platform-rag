# BUILD REPORT: Retrieval — the executor, and a way to run a question

## Metadata

| Field | Value |
|-------|-------|
| Feature | retrieval |
| DEFINE | [DEFINE.md](DEFINE.md) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| ADR | [ADR-014](../../../../docs/adr/ADR-014-source-recall-before-ragas.md), plus [ADR-003 Amendment 1](../../../../docs/adr/ADR-003-hybrid-retrieval-rrf.md) |
| Start date | 2026-09-18 |
| End date | 2026-09-18 |
| PR | not raised |

## What was built

**New**

- `retrieval/pipeline.py` — `retrieve()`: question in, ranked `RetrievedChunk`s
  out. Validates, embeds, searches.
- `scripts/ask.py` + `make ask` — the curator's instrument. No LLM.
- `scripts/retrieval_recall.py` + `make retrieval-recall` — the ADR-014
  measurement, writing a timestamped JSON artifact.
- `docs/adr/ADR-014-source-recall-before-ragas.md`.

**Changed**

- `retrieval/hybrid_search.py` — rewritten. Placeholders, the `SELECT`, the
  limits, the RRF sentinel, plus `search()` and `row_to_chunk()`.
- `contracts.py` — `RetrievedChunk` gained `dense_rank` and `sparse_rank`. A
  deviation; see below.
- `tests/unit/test_hybrid_search_query.py` — corrected, not deleted.
- `docs/adr/ADR-003-hybrid-retrieval-rrf.md` — Amendment 1.
- `Makefile`, `AGENTS.md`, `docs/adr/index.md`.

**Tests**: 41 added (131 → **172**). `test_hybrid_search_query.py` rewritten to
24, `test_retrieval_pipeline.py` (13), `test_hybrid_search_postgres.py` (9).

## What deviated from design

1. **`RetrievedChunk` gained two fields, where DESIGN said "no contract
   changes".** `make ask` must distinguish "this side did not rank the chunk"
   from "this side scored it zero", and those are genuinely different: a chunk
   can carry a real sparse score and still fall outside the sparse top-k, so
   `sparse_score == 0` cannot stand in for the distinction. `dense_rank` and
   `sparse_rank` are optional with `None` defaults, so every existing
   construction still validates. They also make the fusion auditable, which is
   what the ADR-014 script records.

2. **Collection validation moved ahead of the embedding call.** As first
   written, `retrieve()` validated only inside `search()` — so an unknown
   collection name cost a model call and then surfaced from the database layer.
   DEFINE's acceptance test says it must raise *before touching the database*.
   Caught by the unit test, not by running the code. Validation now happens in
   `retrieve()` **and** stays in `search()`, which is the boundary that must not
   be bypassable.

3. **`ORDER BY rrf_score DESC, c.id ASC`** — the tiebreaker is not in DESIGN.
   Without it, ties order arbitrarily and the determinism criterion is luck. With
   the sparse side inert (below), ties are not hypothetical: many chunks share a
   fused score.

4. **ADR-003 Amendment 1 was written during BUILD, as DESIGN said it would be.**
   Not a deviation, recorded for completeness: the `COALESCE(rank, 999)` sentinel
   is gone, replaced by `COALESCE(1.0 / (60 + rank), 0)` per side.

## The two findings that matter more than the code

### 1. The sparse half of hybrid retrieval is inert for real questions

`plainto_tsquery` conjoins every term, so a natural-language question demands
that one chunk contain all of them:

```
plainto_tsquery('english', 'Why did the Snowflake project choose Snowpipe
Streaming over the classic file-based Snowpipe?')
  → 'snowflak' & 'project' & 'choos' & 'snowpip' & 'stream'
    & 'classic' & 'file-bas' & 'file' & 'base' & 'snowpip'
```

Measured across the golden set, counting chunks that match at all:

| question | `plainto` (current) | `websearch` | OR-joined |
|---|---|---|---|
| q001 | **0** | 0 | 161 |
| q002 | **0** | 0 | 179 |
| q003 | 2 | 2 | 158 |
| q004 | **0** | 0 | 201 |
| q005 | **0** | 0 | 211 |

`snowpipe` alone matches 19 chunks, so the corpus is not the problem. The query
plan says the same thing in its own words — `Subquery Scan on s … rows=0`, with
`Rows Removed by Filter: 304` on `sparse_score > 0`.

**This project's "hybrid" retrieval has been dense-only since the query was
written.** The fusion machinery is correct; the sparse half is simply never
populated.

**Deliberately not fixed here.** Switching the tsquery function is a
retrieval-strategy change, and AGENTS.md says any architectural change gets an
ADR before code. Fixing it silently inside a feature whose DEFINE was about
making the existing query executable would have been exactly the bypass that
boundary prohibits. Recorded in ADR-003 Amendment 1 §B as the next decision.

### 2. `fallback_threshold` cannot live on the RRF score

The top fused score, per question:

| q001 | q002 | q003 | q004 | **q005 (out of scope)** |
|---|---|---|---|---|
| 0.01639 | 0.01639 | 0.03279 | 0.01639 | **0.01639** |

The out-of-scope question scores **identically** to three of the four in-scope
ones. This is not a defect in the corpus or the embedding — it is what RRF is.
Rank 1 contributes `1/(60+1) = 0.016393` no matter how good or bad the match is,
because RRF ranks and then discards magnitude. Any non-empty result has the same
top score.

`settings.fallback_threshold` is **0.35**. Compared against an RRF score it would
fire on 100 % of queries, in scope or not.

The threshold therefore has to operate on the reranker score, which
`contracts.py` already anticipates (`query_log.reranker_top_score`). ADR-006 and
ADR-005 both need this on record before the fallback is implemented, and it is
the kind of thing that is discovered on the day the fallback silently swallows
every answer.

## RAGAS delta

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | — | — | n/a |
| Context Precision | — | — | n/a |
| Answer Relevance | — | — | n/a |
| Context Recall | — | — | n/a |
| Fallback rate | — | — | n/a |

**Not measured, and not measurable — the third consecutive feature to say so.**
RAGAS grades generated answers against retrieved contexts. This feature builds
retrieval and not generation, and the golden set is 5 of 50. `make eval` was not
run because there is nothing for it to evaluate. No number is entered, per the
AGENTS.md boundary.

**What exists instead, and is new to the project: a retrieval baseline.**
ADR-014 defines source recall at k; this is its first reading.

```
Source recall at k — 4 in-scope questions, 6 declared paths

  k=3    3/6   (50%)
  k=10   5/6   (83%)
  k=20   5/6   (83%)
```

Per declared path:

| question | declared path | result |
|---|---|---|
| q001 | `snowflake-2 …0029_snowpipe_streaming…md` | **rank 1** |
| q002 | `databricks …007_pipeline_unification.md` | rank 7 |
| q003 | `snowflake-2 …0030_avro_and_schema_registry…md` | rank 5 |
| q003 | `snowflake-2 README.md` | **rank 1** |
| q004 | `snowflake-2 …0030_avro_and_schema_registry…md` | **not retrieved in top 20** |
| q004 | `databricks README.md` | **rank 1** |

Two readings worth keeping:

- **q002's anchor now comes back at rank 7.** The slice-2 dense-only smoke check
  had it below `001_databricks_vs_snowflake.md` and out of the top 3. It is still
  out of the top 3, which is what `settings.rerank_top_k` will pass to
  generation — so on today's evidence q002 would be answered from the wrong
  documents. This is the case ADR-005 exists for, and now it has a number.
- **q004 misses one of its two declared paths entirely.** A comparison question
  needs both sides; it retrieved the Databricks README at rank 1 and never found
  the Snowflake ADR. Whether that is a retrieval failure or a badly anchored
  question is exactly the check the curator could not previously run.

**The denominator is six.** One path moving is 17 percentage points. These
numbers are directional and must never be quoted without the denominator, per
ADR-014's own Consequences.

## Known gaps at merge time

- **The sparse side is inert.** Finding 1. Needs an ADR, not a patch.
- **`fallback_threshold` is meaningless against RRF.** Finding 2. Needs to be
  settled before ADR-006 is implemented.
- **Source recall is measured manually.** `make retrieval-recall` is not in CI,
  deliberately (ADR-014 §4). Someone has to remember to run it.
- **No intent classifier.** `collections=None` searches both. `make ask
  --collections` exists so the question can be settled by experiment.
- **`ts_rank_cd` is computed over every candidate before either side is
  limited** — visible in the plan as the CTE scanning 304 rows. Irrelevant at
  this size; the first place to look if retrieval ever gets slow.
- **`retrieve()` opens a connection per call.** Fine for a CLI, wrong for a UI
  serving concurrent users. The `conn` parameter exists so a pool can be
  introduced without touching the signature.
- **`make ask` is a development instrument** and may not survive the UI.

## Verification

- [x] `make lint` — clean, exit 0 (ruff, yamllint, bandit)
- [x] `make test` — **172 passed** (131 before this feature)
- [x] `make ask` — returns ranked chunks with citations; q001 puts the correct
      ADR and the correct section at rank 1
- [x] `make retrieval-recall` — baseline recorded above, artifact written to
      `.claude/dev/reports/retrieval-recall-20260918-184909.json`
- [x] **Determinism** — two consecutive `make retrieval-recall` runs produced
      identical rankings and identical numbers
- [x] Collection filter — asserted in integration tests in both directions
- [x] **RRF arithmetic asserted by hand**, not eyeballed: a fixture with
      hand-chosen vectors gives dense A,C,B and sparse B, and the test asserts
      `B = 1/(60+3) + 1/(60+1)`, `A = 1/(60+1)`, `C = 1/(60+2)` exactly
- [x] **ADR-003 Amendment 1 asserted** — with `top_k=2`, the sparse-only chunk
      scores exactly `1/(60+1)`, not `1/(60+1) + 1/(60+999)`
- [x] Empty index returns `[]`; a question matching no text still returns dense
      results
- [ ] `make eval` — **not applicable**, no generation exists

### Query plan, first execution of the real fused query

```
Limit (actual time=3.185..3.189 rows=20 loops=1)
  CTE candidates
    ->  Seq Scan on chunks (actual time=0.256..2.664 rows=304 loops=1)
          Filter: (collection = ANY ('{decisions,architecture}'::text[]))
  ->  Sort  Sort Key: (COALESCE(1.0/(60 + d.dense_rank), 0)
                     + COALESCE(1.0/(60 + s.sparse_rank), 0)) DESC, c.id
        ->  Hash Left Join  Filter: (d.dense_rank IS NOT NULL OR s.sparse_rank IS NOT NULL)
              Rows Removed by Filter: 284
              ->  …  Subquery Scan on d  rows=20      <- dense side
              ->  …  Subquery Scan on s  rows=0       <- sparse side, empty
                        Filter: (sparse_score > '0'::double precision)
                        Rows Removed by Filter: 304
Planning Time: 2.055 ms
Execution Time: 4.373 ms
```

Sequential scan on 304 rows, as `sql/99_verify.sql` section 4 already records and
as ADR-014's DESIGN predicted. `rows=0` on the sparse side is finding 1, stated
by the planner.
