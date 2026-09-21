# BRAINSTORM: The tsquery function — making the sparse side exist

> Free exploration. No commitments. No commits from this file alone.

## Date

2026-09-21

## Prompt

ADR-003 Amendment 1 §B, written during the `retrieval` BUILD and merged into
`main` today, records a measurement rather than an opinion: the sparse half of
hybrid retrieval has never returned a row for a question-shaped input.

`plainto_tsquery` conjoins every term with `&`, so one chunk must contain all of
them. Across the five golden-set questions the sparse side matched **0 chunks for
four of them and 2 for the fifth**. The planner says it plainly —
`Subquery Scan on s … rows=0`, `Rows Removed by Filter: 304`.

So this project's "hybrid" retrieval is dense-only, and has been since the query
was written. The fusion arithmetic is correct and was asserted by hand in
`tests/integration/test_hybrid_search_postgres.py`; it is simply never given a
second list to fuse.

The amendment deliberately did not fix it, because changing how the tsquery is
built is a retrieval-strategy decision and AGENTS.md requires an ADR before code.
This is that decision.

Four things constrain it, and they are worth stating before any option:

**1. The schema is not in question.** `chunks.content_tsv` and its GIN index
already exist (ADR-013). Every option below changes the *query*, not the table,
except where noted as discarded.

**2. RRF weights the two sides equally, and there is no weight to turn.** The
query adds `1/(60+dense_rank)` and `1/(60+sparse_rank)` with no coefficient.
Whatever the sparse side ranks first contributes exactly as much as whatever the
dense side ranks first. If the sparse list goes from 0 rows to ~200, that is not
a small change to the fused ordering — it is a second voter with an equal ballot,
and today nobody has heard it vote. ADR-003 says the weights are RAGAS-tuned;
there is no weight field in the query or in `config.py` to tune.

**3. The measurement that would judge any option has a denominator of six.**
`make retrieval-recall` (ADR-014) covers 4 in-scope questions and 6 declared
source paths. One path moving is 17 percentage points. The golden set is 5 of a
planned 50.

**4. Today's recall baseline was measured with the sparse side inert.** Whatever
is chosen here invalidates it as a comparison point unless the before/after is
re-run on the same day, on the same snapshot, with the same embedding model.

## Options considered

### Option 1: OR-join the lexemes `plainto_tsquery` already produces

Rewrite the conjunction into a disjunction, in SQL, without building query
strings in Python:

```sql
replace(plainto_tsquery('english', %(query_text)s)::text, ' & ', ' | ')::tsquery
```

`plainto_tsquery` does the parsing, stemming, stopword removal and — the part
that matters — the sanitising. The rewrite touches only the operators, so no
user text ever reaches the query as syntax.

- **Pros**
  - The sparse side becomes non-empty for every question, which is the whole
    point; `ts_rank_cd` then does what it was always supposed to do: rank by how
    well and how densely the matched terms cover the chunk.
  - Smallest possible change. One expression, used twice in `HYBRID_QUERY`
    (the `ts_rank_cd` argument and the sparse filter), no new dependency, no
    schema change, no Python-side text handling.
  - Keeps exact-term matching, which is the reason to have a sparse side at all:
    `Snowpipe`, `ADR-0029`, `Lakeflow`, `Unity Catalog` are where a 384-dim
    `bge-small` embedding is weakest and a lexeme match is strongest.
- **Cons**
  - 158–211 of 304 chunks match (measured, ADR-003 Amendment 1 §B). Two thirds
    of the corpus enters the sparse list, so the `top_k` cut, not the match,
    becomes the filter. Whether the right chunk lands in that cut is **not
    measured**.
  - A chunk can top `ts_rank_cd` on a generic term — "project", "data",
    "pipeline" — and collect a rank-1 RRF contribution equal to the best dense
    hit. This is the risk that constraint 2 describes, and it arrives the day
    this option ships.
  - `ts_rank_cd` is already computed over all 304 candidate rows before either
    side is limited (a known gap from the `retrieval` BUILD). Irrelevant at this
    size, and this option does not make it worse, but it does make it load-bearing.

### Option 2: Drop generic terms first, then OR the rest

Same disjunction as Option 1, but the question's terms are filtered by how common
they are in this corpus before being joined. Postgres can supply the document
frequencies itself, from `ts_stat` over `content_tsv`, so the corpus stays the
source of truth about what is generic in it.

- **Pros**
  - Attacks the precise failure mode Option 1 is exposed to. "Why did the
    Snowflake **project** choose **Snowpipe** Streaming" should not let
    `project` vote.
  - A term appearing in 200 of 304 chunks carries almost no information; dropping
    it is closer to what a sparse retriever is for.
  - Degrades sensibly: if every term is generic, fall back to Option 1's full
    disjunction rather than to an empty list.
- **Cons**
  - Needs a threshold, and a threshold needs a justification against the golden
    set — a second tuning knob measured on the same denominator of six.
  - The frequencies must live somewhere: recomputed per query (a scan), cached in
    a table (a new object, so a schema change and a refresh policy tied to
    `corpus_snapshot`), or frozen into a constant (which silently rots the day
    the corpus grows).
  - More machinery than the problem has yet been shown to need, since Option 1's
    precision has not been measured.

### Option 3: AND first, OR only when AND returns nothing

Keep `plainto_tsquery` as the primary, and fall back to the disjunction when the
conjunction yields zero rows.

- **Pros**
  - Keeps the precision of a conjunction for the input shape where it works —
    short keyword queries, which is what `make ask --collections` and any future
    UI search box will actually receive.
  - Strictly additive against today's behaviour: no query that works now changes.
- **Cons**
  - Two retrieval behaviours behind one entry point, selected by a property of
    the data rather than of the request. The fused ordering for a question is
    then not explainable without knowing which branch fired.
  - Evaluation gets harder in exactly the way ADR-014 was written to avoid: a
    recall number would average two different retrievers.
  - On today's evidence the AND branch fires for roughly one question in five, so
    this is mostly Option 1 with a rarely-taken shortcut and twice the surface.

### Option 4: Delete the sparse side and call it dense-only

Remove the sparse CTE and the fusion, keep dense + reranker, amend ADR-003 to
record that hybrid retrieval was tried and abandoned.

- **Pros**
  - Honest. The README, AGENTS.md and ADR-003 all claim hybrid retrieval today,
    and the claim is false. That is a documentation defect right now, whichever
    option wins.
  - Removes a CTE, a join, a rank computation and two contract fields from the
    hot path, and removes the equal-ballot risk of constraint 2 entirely.
  - The reranker (ADR-005, still Planned) is the real precision instrument.
    Dense recall feeding a cross-encoder is a defensible architecture and is what
    the system would actually be.
- **Cons**
  - Gives up exact-term matching permanently, and the corpus is dense with
    identifiers that embeddings handle badly.
  - Reverses a decision on the strength of a measurement taken with a broken
    implementation — the sparse side has never been given a fair run.
  - Throws away working, hand-asserted fusion code to avoid choosing a tsquery
    function.

## Discarded early

- **`websearch_to_tsquery` as a drop-in.** Measured on 2026-09-18 across the
  same five questions: identical results to `plainto_tsquery`, 0 chunks for four
  of them. It ORs nothing unless the user types `or`. Recorded in ADR-003
  Amendment 1 §B so this does not get proposed again.
- **`pg_trgm` trigram similarity instead of tsvector.** A different index on a
  different column for a problem that lives in query construction. `content_tsv`
  and its GIN index already exist and work; the lexemes are not the failure.
- **Extracting keywords in Python with an NLP library.** Adds a dependency, and
  moves knowledge about this corpus's vocabulary out of the database that holds
  the corpus. Postgres already stems, stops and counts; `ts_stat` is right there.
- **Tuning `RRF_K` to compensate.** The constant is fixed at 60 by ADR-003 and
  changing it cannot turn an empty list into a populated one. Wrong lever.

## Emerging preference

**Option 1, on the condition that it is measured before it is believed** — and
the measurement is the substance of the decision, not a formality after it.

The reasoning: Option 1 is the minimum change that makes the sparse side exist,
and none of the more elaborate options can be judged until it does. Option 2 is a
refinement of Option 1 and stays available; Option 3 is Option 1 carrying a
second retriever it rarely uses; Option 4 is the right answer only if the sparse
side, given a fair run, adds nothing.

The measurement already exists: `make retrieval-recall`, ADR-014, run before and
after on the same snapshot. Three readings decide it:

| reading | meaning |
|---|---|
| recall at k=3 improves | Option 1 ships |
| recall at k=3 flat, k=10/k=20 improves | the reranker's problem, not retrieval's — ADR-005 gets the case |
| recall at k=3 **degrades** | the equal-ballot risk is real → Option 2, or Option 4 |

**What would change my mind.** If the sparse list drowns the dense one — if a
chunk that only matches `project` and `data` displaces q001's correct ADR from
rank 1 — then the honest answer is that RRF with equal weights is the wrong
fusion for a 200-row sparse list, and the decision becomes weighting or Option 4
rather than the tsquery function. That is a question about the fusion, and it is
the one this brainstorm would rather hand to DEFINE with a number attached.

**Two things this cannot be decided on today, and both are gaps, not estimates:**

- **The database is not running.** `docker compose ps` is empty, so no option
  above has been measured beyond the match counts already in ADR-003. Every
  precision claim in this file is marked unmeasured on purpose.
- **The denominator is six.** A conclusion drawn from 6 declared paths across 4
  questions is directional. ADR-014's own Consequences forbid quoting these
  numbers without it, and that applies to whatever DEFINE measures next.

## Next step

- [x] Write DEFINE if a clear direction emerged — Option 1, gated on a
      before/after `make retrieval-recall` on the same snapshot
- [ ] Or park with `status: Parked` and revisit

Prerequisite for DEFINE, and it is not optional: `make bootstrap` +
`make fetch-corpus` + `make index-corpus`, so that a before-reading exists to
compare against. The current baseline in the `retrieval` BUILD_REPORT was taken
on the 2026-09-18 snapshot; if the refetched snapshot moves, the before-reading
must be retaken rather than quoted from that report.
