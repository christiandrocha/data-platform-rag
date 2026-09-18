# BRAINSTORM: Retrieval — turning 304 indexed rows into ranked chunks

> Free exploration. No commitments. No commits from this file alone.

## Date

2026-09-18

## Prompt

`corpus-indexing` is finished and merged: 304 chunks are in Postgres with
provenance, an HNSW index and a GIN index. Nothing reads them. The question is
what the next feature should contain — where retrieval starts and where it stops.

Three things found while reading the existing code, before proposing anything.
They are not opinions and they shape the options:

**1. `HYBRID_QUERY` cannot execute as written.** It uses `$1`, `$2`, `$3`
placeholders — asyncpg syntax. This project declares and uses `psycopg`
(`pyproject.toml`, and `indexer/writer.py` throughout), which uses `%s`. The
query has never been run against a database. `tests/unit/test_hybrid_search_query.py`
asserts `"embedding <=> $1::vector" in HYBRID_QUERY`, so the test currently
*pins the unexecutable form* — the test will have to change with the query, which
is worth knowing before someone treats it as a regression.

**2. The query cannot build a `RetrievedChunk`.** That contract nests
`ChunkMetadata`, whose required fields are `source_project`, `source_type`,
`source_path`, `chunk_index`, `token_count`. The final `SELECT` returns `id`,
`content`, `source_project`, `adr_id`, `source_path`, the two raw scores and
`rrf_score`. Three required fields are missing. Either the SELECT widens or the
contract is wrong; ADR-010 says the contract is the source of truth, so the
SELECT widens.

**3. `build_hybrid_query(collections)` ignores its argument.** It validates that
the list is non-empty and then returns the constant unchanged. The collections
were meant to arrive as `$3`. Not a bug today, because nothing calls it.

Also relevant: `settings.hybrid_top_k` exists and is 20, and the query hardcodes
`LIMIT 20` three times. AGENTS.md says retrieval weights are RAGAS-tuned rather
than guessed — which cannot happen while the number is a literal.

## Options considered

### Option 1: Thin executor only

One function: question text plus collections in, `list[RetrievedChunk]` out. Fix
the placeholders, widen the SELECT, point the limits at settings. No intent
classification — the caller passes collections and the default is both.

- **Pros.** Smallest possible unit. Every one of the three findings above gets
  fixed. Testable against the real 304 rows with real embeddings. Nothing about
  it presumes how the rest of the pipeline will be shaped.
- **Cons.** Still nothing a person can *run*. The curator cannot use it without
  writing Python, so the feedback loop that motivates the work stays shut.

### Option 2: Executor + intent classifier

Option 1 plus the LLM call that chooses `decision` / `architecture` /
`comparison` / `hybrid` and maps it to collections, per ADR-002.

- **Pros.** Completes the "retrieval" stage as the README pipeline draws it. The
  collection filter stops being a caller's guess.
- **Cons.** Couples a deterministic, offline-testable component to an LLM call
  with cost, latency and non-determinism. Two very different testing strategies
  in one feature. The classifier also has a real open question — whether an LLM
  is needed at all, or whether keyword heuristics would do — and that deserves
  its own brainstorm rather than being decided as a side effect of this one.

### Option 3: Thin executor + a `make ask` command

Option 1 plus a small script that embeds a question, runs retrieval and prints
the ranked chunks with their scores and citations. No LLM anywhere.

- **Pros.** Closes the curator's feedback loop, which DEFINE of slice 2 named as
  the sharpest present-tense pain: 45 questions left to write, with no way to
  check whether a question retrieves the ADR it was anchored to. Makes the
  retrieval quality *visible* before any generation exists to hide it. Gives
  ADR-004 and ADR-005 a manual instrument to compare against later.
- **Cons.** A CLI that is not part of the product, and may be thrown away once
  the Streamlit UI exists. Slightly widens the feature beyond a library function.

### Option 4: Full vertical slice to an answer

Retrieval, reranking and the Claude call, ending in a cited answer.

- **Pros.** Produces the thing the project is actually for. Would let RAGAS run.
- **Cons.** Three features in a trench coat, two of which have unwritten ADRs
  (ADR-005 is Planned). It would also produce the project's first answer quality
  numbers against a golden set of 5 of 50 — a measurement taken too early to
  mean anything, and the kind of number the AGENTS.md boundary exists to prevent.

## Discarded early

- **Switch to asyncpg so `HYBRID_QUERY` runs unchanged** — the writer, the
  connection helper and the pgvector adapter registration are all psycopg, and
  the app is Streamlit, which is synchronous. Changing driver to avoid editing
  three placeholders is the tail wagging the dog.
- **Two queries, fused in Python** — dense and sparse separately, RRF in
  application code. Easier to unit test, but it doubles the round trips and
  moves ranking logic out of the place ADR-003 put it. Revisit only if the one
  query proves untunable.
- **Include reranking here** — ADR-005 is Planned, cross-encoder inference is a
  different performance and testing problem, and the reranker is meaningless
  until there is something to rerank.
- **Tune RRF weights or `k` in this feature** — AGENTS.md requires RAGAS tuning,
  and RAGAS needs generation and a populated golden set. Make the numbers
  configurable here; tune them when tuning is possible.

## Emerging preference

**Option 3** — the thin executor plus `make ask`.

Option 1 is the honest core and Option 3 is Option 1 plus roughly thirty lines
that make it usable by a person. That is a small price for closing the curator's
loop, and the loop is the reason retrieval is next rather than the golden set:
building retrieval first makes the remaining 45 questions cheaper to write,
while doing the golden set first gets no equivalent benefit from retrieval
arriving later.

Option 2 is the main rival and is deliberately deferred, not rejected. The
intent classifier deserves its own brainstorm, because "does this need an LLM at
all" is a genuine open question and answering it inside a retrieval feature
would answer it by accident.

**What would change our mind.** If a manual run shows the collection filter
matters enough that retrieving across both collections is visibly worse, the
classifier stops being deferrable and Option 2 becomes the scope. The `make ask`
command from Option 3 is exactly the instrument that would show this — which is
another argument for building it.

## Next step

- [x] Write DEFINE if a clear direction emerged — **pending user confirmation**
- [ ] Or park with `status: Parked` and revisit

Not started. DEFINE would need to settle, at minimum: whether the three findings
above are fixed inside this feature or split out as a separate fix; what
`make ask` prints and whether it is a product surface or a dev tool; and what
"retrieval works" means as a number when no RAGAS score can exist yet.
