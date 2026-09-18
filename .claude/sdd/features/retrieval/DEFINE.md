# DEFINE: Retrieval — the executor, and a way to run a question

> Make the 304 indexed chunks answerable: one function that takes a question and
> returns ranked `RetrievedChunk`s, and one command that lets a person run it.

## Metadata

| Field | Value |
|-------|-------|
| Feature | retrieval |
| Date | 2026-09-18 |
| Author | christiandrocha |
| Status | Ready for Design |
| Clarity Score | 13/15 |
| Brainstorm | [BRAINSTORM.md](BRAINSTORM.md), Option 3 |

## Problem statement

The corpus is indexed and unreachable. 304 chunks sit in Postgres behind an HNSW
index and a GIN index, and no code path reads them. `make index-corpus` is the
last command in the project that does anything.

The retrieval SQL is not missing — it is written, in
`retrieval/hybrid_search.py`, and it has never run. Reading it against the rest
of the codebase turns up three reasons it cannot:

**It uses the wrong placeholder syntax.** `$1`, `$2`, `$3` is asyncpg. This
project declares and uses `psycopg` (`pyproject.toml`; `indexer/writer.py`
throughout), which uses `%s`. The query has never been executed against a
database, and `tests/unit/test_hybrid_search_query.py` asserts the `$1` form —
so the only test covering it pins the shape that cannot work.

**Its `SELECT` cannot build the contract it is supposed to produce.**
`RetrievedChunk` nests `ChunkMetadata`, which requires five fields:
`source_project`, `source_type`, `source_path`, `chunk_index`, `token_count`.
The final `SELECT` returns two of them. ADR-010 makes the contract the source of
truth, so the `SELECT` is what is wrong.

**`build_hybrid_query(collections)` ignores its argument.** It rejects an empty
list and then returns the constant unchanged; the collections were meant to
arrive as `$3`.

Behind all three sits the pain that makes this feature next rather than later.
The golden set stands at 5 of 50, and the curator writes the remaining 45
questions blind: there is no way to ask whether a question actually retrieves
the ADR it was anchored to. Every question written today is a guess that can
only be checked after generation and RAGAS exist — which is the slowest possible
feedback loop for the cheapest possible question.

## Users

| User | Role | Pain point |
|------|------|-----------|
| Christian (curator) | Writes the remaining 45 golden-set questions | Anchors each question to a source path by hand and cannot check the anchor. `expected_source_paths` is a claim nothing verifies |
| Christian (operator) | Wants to know whether the index is any good | Has 304 rows, an HNSW index and a GIN index, and no evidence that retrieval over them returns anything sensible |
| ADR-004 (model + HNSW tuning) | Needs a retrieval metric to tune against | Still Planned. Cannot compare two models or two HNSW settings without a repeatable retrieval measurement |
| ADR-005 (reranking) | Needs a pre-rerank baseline | Still Planned. "Reranking improves things" is unmeasurable without the number it improves on |

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | One function: question text + collections in, `list[RetrievedChunk]` out, every element a valid pydantic instance |
| MUST | The query executes against psycopg — placeholders corrected, and the existing test corrected with it rather than deleted |
| MUST | The `SELECT` returns every field `ChunkMetadata` requires, so the contract is constructible without invention |
| MUST | `collections` is actually applied as a filter, and an empty list is still rejected |
| MUST | `make ask q="..."` — embed the question, retrieve, print ranked chunks with their RRF, dense and sparse scores, and a citation per chunk |
| MUST | **Source recall measured and reported** against the golden set: for the 4 in-scope questions and their 6 declared `expected_source_paths`, how many are retrieved at k = 3, 10 and 20 |
| SHOULD | `hybrid_top_k` and the RRF constant read from `settings`, not literals, so the ADR-004/ADR-008 tuning that AGENTS.md requires becomes possible without touching SQL |
| SHOULD | The out-of-scope question (q005) reported alongside the others, so its top RRF score can be compared against the in-scope ones |
| SHOULD | A recorded baseline artifact the reranking and tuning ADRs can be measured against |
| COULD | `make ask` accepts `--collections` to force one collection, making the "do we need an intent classifier" question answerable by experiment |
| COULD | Latency per stage printed, as an early read on whether retrieval is anywhere near a UI budget |

## Success criteria (measurable)

- [ ] `make ask q="..."` exits 0 and prints **≥ 1** chunk for a question about the corpus
- [ ] Every returned object validates as a `RetrievedChunk`; **0** constructed with placeholder or invented metadata
- [ ] The query runs through psycopg with **0** occurrences of `$1`/`$2`/`$3` remaining in `hybrid_search.py`
- [ ] `grep -c "LIMIT 20" hybrid_search.py` returns **0** — the limit comes from `settings.hybrid_top_k`
- [ ] Retrieval over both collections returns at most `settings.hybrid_top_k` (**20**) chunks, and filtering to one collection returns **0** chunks from the other
- [ ] **Source recall reported for all 4 in-scope questions across 6 declared source paths**, at k = 3, 10, 20 — three numbers out of 6, recorded in the BUILD_REPORT
- [ ] The q005 (out-of-scope) top RRF score is recorded next to the four in-scope top scores — **5** numbers, for ADR-005 and ADR-006 to use later
- [ ] Two identical `make ask` invocations return identical rankings — retrieval is deterministic
- [ ] An empty `collections` list raises, and an unknown collection name raises, rather than silently returning everything

**On the absence of a pass threshold.** The recall criterion says *measure and
report*, not *must exceed N*. No baseline exists, and a threshold invented today
would be the fabricated number AGENTS.md prohibits. There is already a reason to
expect it will not be perfect: a dense-only smoke check during slice 2 returned
`001_databricks_vs_snowflake.md` above `007_pipeline_unification.md` for q002,
whose declared anchor is the latter. Whether hybrid fixes that is unknown, and
finding out is the point.

## Acceptance tests

- [ ] Given a populated index and a corpus question, `make ask` prints ranked
      chunks with scores and citations, and exits 0
- [ ] Given the same question twice, the two rankings are identical
- [ ] Given `collections=["decisions"]`, no returned chunk has
      `collection = "architecture"`, and vice versa
- [ ] Given an empty or unknown collections list, the call raises before touching
      the database
- [ ] Given each of the 4 in-scope golden-set questions, the run reports whether
      each declared `expected_source_paths` entry appears at k = 3, 10, 20
- [ ] Given q005, the run reports its top RRF score without special-casing it —
      out-of-scope handling is generation's job, not retrieval's
- [ ] Given an empty `chunks` table, retrieval returns an empty list and
      `make ask` says so plainly, rather than raising or printing nothing
- [ ] Given a question in a collection that exists but matches nothing textually,
      dense-only results still return — the sparse side contributing zero must not
      empty the result

## Non-goals

Explicitly out of scope for this feature:

- **Intent classification.** The caller passes `collections`; the default is
  both. Whether choosing them needs an LLM at all is a real open question and
  deserves its own brainstorm, per BRAINSTORM Option 2. Deciding it inside a
  retrieval feature would decide it by accident.
- **Reranking.** ADR-005 is Planned. A cross-encoder is a different performance
  and testing problem, and reranking is meaningless before there is a measured
  baseline to improve on — which this feature produces.
- **Generation, and the out-of-scope fallback.** No Anthropic call. The fallback
  is ADR-006's and fires on a reranker score that does not exist yet.
- **Tuning RRF weights, `k`, or HNSW parameters.** AGENTS.md requires RAGAS
  tuning; RAGAS requires generation and a populated golden set. This feature
  makes the numbers configurable and records a baseline. It does not move them.
- **The Streamlit UI.** `make ask` is a development instrument. Whether any of
  it survives into the UI is a later question.
- **`query_log` writes and Langfuse traces.** Both are specified for *user
  queries* (ADR-009, AGENTS.md). A developer running `make ask` is not a user
  query, and writing rows for it would pollute the analytics source of truth
  before the product exists.
- **Growing the golden set.** That is `golden-set-curation`, already designed and
  mid-BUILD. This feature exists to make that one cheaper, not to do it.

## Open questions

- [ ] **Does `make ask` embed the question with `embed_query`, and is that cache
      correct here?** `embed_query` is `lru_cache`d for repeated user queries
      within a session. A CLI process is one query and exits, so the cache never
      hits and costs nothing — but a future UI would share it. Worth confirming
      rather than assuming it is free.
- [ ] **What does `make ask` print, exactly?** Full chunk text is unreadable at
      20 results; a truncated preview risks hiding the reason a chunk ranked. The
      curator's need is "did my anchor come back and at what rank", which may
      want a different default view from "why did this rank".
- [ ] **Where does the recall measurement live?** A flag on `make ask`, a
      separate script, or a test. As a test it runs in CI and needs a database
      and a model; as a script it is honest but manual. This interacts with what
      `ragas.yml` will eventually do.
- [ ] **Is `RetrievedChunk.dense_distance` the right field for a chunk that only
      matched sparsely?** The contract requires it and the SQL computes it for
      every candidate, so a value always exists — but for a sparse-only match it
      is a distance nothing ranked on, and a reader may take it for a reason the
      chunk was returned.
- [ ] **Should the fused result carry the chunk's `snapshot_id`?** Provenance is
      now a first-class column (ADR-013). A citation that cannot name the corpus
      commit it came from weakens what ADR-012 and ADR-013 were built for, but
      `RetrievedChunk` has no field for it and adding one is a contract change.

## Deferred exit criterion

`WORKFLOW_CONTRACTS.yaml` requires, for BUILD, that "make eval shows no
regression on golden set". **Deferred again, with the same cause recorded in
`corpus-indexing-writer`:** RAGAS scores generated answers against retrieved
contexts, and this feature builds retrieval but not generation. The golden set
also remains at 5 of 50.

This is the third consecutive feature to defer it, which is itself worth saying
out loud: the criterion is written for a mature pipeline and every feature so far
has been upstream of it. It returns when generation exists and the golden set is
populated — a condition, not a feature name.

Standing in its place: the source-recall measurement above, which is the first
retrieval-quality number the project will have, and the determinism and
collection-filter assertions, all observable without RAGAS.

## Clarity Score self-check

Rate each 1-5. Total must be ≥ 12/15 to proceed to Design.

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | Three defects each located at a named symbol and each with a mechanical test, plus a fourth problem — the curator's blind anchoring — that is present-tense and blocking. Nothing here is speculative: the query's placeholders, the missing metadata fields and the ignored argument were all read out of the file |
| Users are named and their pain is real | 4 | The curator's pain is concrete and current: 45 questions, 6 unverifiable anchors in the 4 written so far. Not a 5 for the reason the two previous DEFINEs gave — half the rows are consumers (ADR-004, ADR-005), not people |
| Success criteria include numbers | 4 | Eight of nine criteria are exact counts, and the recall criterion names its denominators (4 questions, 6 paths, k = 3/10/20). Not a 5, and the reason is real rather than modest: the central quality criterion has **no pass threshold**. That is the honest choice with no baseline, but a criterion that cannot fail is a weaker criterion, and calling it a 5 would paper over that |
| **Total** | **13/15** | Above the 12/15 gate |
