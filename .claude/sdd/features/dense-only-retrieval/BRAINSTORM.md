# BRAINSTORM: Honest dense-only retrieval

> Free exploration. No commitments. No commits from this file alone.

## Date
2026-09-30

## Prompt

ADR-017 was rejected on 2026-09-30 by its own rule, the second lexical repair of
the sparse side to fail after ADR-015. Both failed on the same mechanism. RRF gives
the two lists an equal ballot, so a chunk that ranks mid-list on both sides
outscores the right chunk at dense rank 1. The author pre-agreed that a rejection
opens **the honest dense-only ADR** (sparse-df-filter BRAINSTORM, Option 2; ADR-017
Alternative 7).

What is true today, without measuring anything new:

- **The system already is dense-only for 43 of 50 golden questions.**
  `plainto_tsquery` ANDs every term, and the sparse side returned rows for 7 of 50
  (`retrieval-recall-20260929-190639.json`). For those 43, removing the sparse
  side changes nothing, by construction.
- **The sparse side is alive for keyword input.** `make ask q="why Snowpipe
  Streaming?"` gets real sparse scores (ADR-015 Context). No UI exists, so which
  input shape real users type is unknown.
- **The public text claims hybrid in five places.** README ("Why it exists", the
  mermaid diagram, the architecture tree, the stack table), AGENTS.md (stack,
  pgvector discipline), ADR-003, and the KB. README Known Gaps already says the
  claim does not hold for question-shaped input.
- **ADR-006's fallback threshold was written in cosine** ("baseline: 0.35
  cosine"). Under RRF the top score is `1/61` for every dense-only question, in or
  out of scope (0.01639 for all five out-of-scope questions). The threshold has had
  nothing to act on. A dense-only ranking has a cosine similarity to report again.

The question is not *whether* to go dense-only. The author settled that. It is
**how far**: what leaves the query, what stays in the schema, what the score
means, and what counts as "it did no harm".

## Options considered

### Option 1: Dense-only query, schema untouched

Rank by cosine distance alone. Remove the sparse CTE and the RRF fusion from
`HYBRID_QUERY`. Leave `content_tsv`, its GIN index and `pg_trgm` in the schema,
documented as unused by retrieval.

- **Pros**
  - The query does what the docs say, for every input shape. No retriever
    silently switches on when the user happens to type keywords.
  - No `DROP`. The bootstrap path stays create-only (ADR-013 §5). A future sparse
    attempt (a weighted one, once RAGAS can tune a weight) needs no migration.
  - The simplest hot path. One ranked list means no ties between two ballots.
  - Identical rankings for the 43 questions where sparse is already empty, so any
    change in recall is confined to the 7 where it fires, and those can be named.
- **Cons**
  - Drops exact-term matching for keyword input. That is the one case where the
    sparse side demonstrably returns something. Whether it *helps* there is
    unmeasured.
  - Leaves an unused generated column and index in the schema. They are honest
    only if the schema comments say so.
  - The public "hybrid" story goes. That is a product change, which the author
    already accepted as the rejection branch.

### Option 2: Dense-only query, and drop the sparse schema too

Option 1, plus removing `content_tsv` and `idx_chunks_content_tsv_gin`.

- **Pros**
  - Nothing unused remains, and the schema is what retrieval reads.
- **Cons**
  - A `DROP COLUMN` / `DROP INDEX` has nowhere legal to live. `sql/00`–`03` are
    create-only, and `90_reset.sql` destroys everything. Adding a migration path
    to this project is its own decision.
  - It makes the next sparse attempt a schema change instead of a query change.
  - It saves almost nothing at 304 rows.

### Option 3: Keep `plainto_tsquery` as it is, and make the claims honest

No code change. Rewrite README, AGENTS.md and ADR-003 to say "dense retrieval,
plus an exact-match sparse vote that fires only when one chunk contains every
query term".

- **Pros**
  - Keeps the keyword behaviour, which is real.
  - Zero risk to recall. Nothing moves.
- **Cons**
  - The ranking policy is chosen by a property of the input, not by a decision.
    ADR-015 rejected Alternative 3 ("AND first, OR on zero") for exactly this: two
    retrievers behind one entry point, and a recall number that averages them.
  - It keeps RRF, so the fallback score stays `1/61` for most questions and
    ADR-006's threshold keeps acting on nothing.
  - It is not what the author pre-agreed. It is the status quo, renamed.

### Option 4: Dense-only, and the score becomes cosine similarity

Option 1, plus the ranked chunks carry `1 - cosine distance` as their score, so
the fallback threshold of ADR-006 has a number with a meaning.

- **Pros**
  - It removes the reason `top_rrf_score` is 0.01639 for every out-of-scope
    question. Out-of-scope separation becomes measurable on the 5 out-of-scope
    golden questions.
- **Cons**
  - It widens the change into the contract (`RetrievedChunk.rrf_score`), into
    `ask.py` and the recall report, and into ADR-006's territory. Choosing a
    threshold value is a separate decision, and generation, which uses it, does
    not exist yet.
  - Mixing "remove sparse" with "redefine the score" makes the measurement read
    two changes at once.

## Discarded early

- **A weight on the sparse RRF term.** Out of scope in both prior features, for the
  same reason: nothing can tune it while RAGAS cannot run.
- **A third lexical repair** (another cutoff, BM25 via `pg_search`, trigrams).
  Two measured failures shared the equal-ballot mechanism. A different lexeme set
  does not change the ballot.
- **A mode switch (`retrieve(..., sparse=True)`).** It is a knob with nothing to
  set it. No UI, no intent classifier. ADR-017's DESIGN rejected the same thing
  as "two retrievers under one name".
- **The per-project share for comparison questions.** A real lever for the
  comparison misses (sparse-df-filter BRAINSTORM, "A different problem"), but it is
  its own ADR and needs the intent classifier. It retakes its before-reading on
  whatever state this feature leaves.

## Emerging preference

**Option 1: dense-only query, schema untouched.** Option 4's cosine score is
recorded in the ADR as the consequence that opens ADR-006's recalibration, but it
is not done here.

- It is what the author pre-agreed, and it makes every public claim fixable with a
  true sentence.
- It keeps each measurement reading one change. This feature removes the sparse
  side. The score's meaning is the fallback ADR's question.
- No `DROP`, so it stays inside ADR-013's bootstrap boundary.

**The measurement is a non-inferiority test, not an improvement test.** The gain
here is honesty and simplicity, not recall. So DEFINE's rule should ask "did
removing the sparse side cost anything the LLM sees?", fixed before measuring,
like ADR-017's. A shape to settle in DEFINE:

- k=3 stays **≥ 38/57**, and **no path in today's top 3 leaves it**. If it costs a
  path, which of the 7 sparse-active questions lost it gets named in the ADR, and
  the author decides with that name in hand, not with a number alone.
- k=10 ≥ 44 and k=20 ≥ 46.
- The 43 sparse-empty questions have identical rankings (a correctness check on
  the change, not a result).

**What would change my mind:** if the 7 sparse-active questions turn out to hold
top-3 paths that only the sparse vote puts there, then dense-only costs something
the LLM sees. Option 3's honesty rewrite would then deserve a second look.
DEFINE has to decide in advance what happens in that case, so the reading cannot
choose it.

**Not looked at, on purpose:** which of the 7 questions' declared paths carry a
sparse rank today. The before-reading JSON has it, but reading it now would let
the result choose the rule. DEFINE fixes the rule first, as in ADR-017.

## Next step

- [x] Author confirms Option 1 (2026-09-30)
- [ ] Write DEFINE: the non-inferiority rule, and what happens if dense-only costs a
      top-3 path
- [x] Branch: `dense-only-retrieval`, from `sparse-df-filter` (stacked, like the
      branches before it)
