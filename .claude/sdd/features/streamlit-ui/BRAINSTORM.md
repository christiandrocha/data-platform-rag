# BRAINSTORM: The product query path, and the Streamlit page over it

> Free exploration. No commitments. No commits from this file alone.

## Date
2026-10-05

## Prompt
ADR-020's measurement waits for an API key, and everything after it does too.
The author chose to move to the product side meanwhile: the page a visitor uses.

Today `ui/app.py` is a placeholder that says so. Underneath it, nothing joins the
stages into a product query. `retrieval/pipeline.py` retrieves and
`generation/client.py` generates, but the client is the **evaluation path**: its
docstring says it writes no `query_log` row and no Langfuse trace, and that "the
product path wraps it when the UI is built". AGENTS.md requires both for every
user query: one `query_log` row (the analytics source of truth) and one Langfuse
trace with a span per stage (the observability source of truth).

So the feature is not only a page. It is the missing **product query path**
(retrieve → generate → classify → log → trace) and a page on top of it. Both
must be buildable and testable **without an API key**, as `fallback-eval` was:
the client is injected, and tests use a stub.

### What the code shows before any option

- **`AnswerResult` in `contracts.py` describes a pipeline that no longer
  exists.** It carries `intent: IntentClassification`, `top_chunks:
  list[RerankedChunk]` and `top_score`. There is no intent classifier, no
  reranker (ADR-005 rejected it), and no score gate (ADR-019 superseded it).
  Nothing imports it. It has to be rewritten, not filled in.
- **`query_log` has the same problem.** It has columns for `intent` and
  `reranker_top_score`, which nothing would fill. It has no column for the
  output class (ADR-020's four classes), the model, the prompt version, the
  tokens, or the corpus snapshot that answered. `fallback_fired` exists, but
  since ADR-019 it is the LLM's choice, read from the text by
  `generation/fallback.py`.
- **The Langfuse client is a no-op singleton** typed `Any`, pinned to SDK 2.x.
  No trace is emitted anywhere yet.
- **Rule 3 is the only out-of-scope gate, and it is unmeasured.** ADR-020 is
  Planned. A public page answering visitors before that measurement is exactly
  the risk ADR-006 named: fabricated answers that look grounded.

## Options considered

### Option 1: One feature, the whole path and a minimal page, built in two PRs
- **What:** a product function `answer(question, client, conn)` →
  `AnswerResult` (rewritten): retrieve once, generate under `SYSTEM_PROMPT`,
  classify the output with ADR-020's classifier, write one `query_log` row,
  emit one Langfuse trace (fire-and-forget, no-op when disabled). The page: a
  question box, the answer, and its sources (project, path, ADR id) under it;
  the fallback shown as the fallback. One DEFINE, one DESIGN and one ADR (the
  `query_log` columns, the trace shape, the deploy gate). BUILD lands as two PRs:
  the path first, the page second.
- **Pros:** one decision record for one product path. The page is thin because
  the path does the work. The two PRs keep each diff reviewable. Everything is
  testable on a stub client and the local database.
- **Cons:** the largest DEFINE so far that ends in user-visible code. The
  `query_log` change touches the schema (create-only bootstrap, ADR-013), so it
  needs care: `ADD COLUMN IF NOT EXISTS`, never a `DROP` in `sql/00`–`03`.

### Option 2: Two features, the path first, the page later
- **What:** feature `query-path` (the same backend as Option 1, no UI), then
  feature `streamlit-ui` over it.
- **Pros:** each feature is smaller. The path can be exercised from the command
  line (`make ask --generate`, which ADR-020's DESIGN deferred) before any page
  exists.
- **Cons:** two DEFINEs and two DESIGNs for what is one product decision. The
  page's needs (what a source looks like, what an error shows) shape the
  contract, and splitting decides the contract before those needs are written
  down.

### Option 3: A retrieval-only page now, generation when the key exists
- **What:** `make ask` in a browser. Question in, ranked chunks out, no LLM.
- **Pros:** works today, no key, very small.
- **Cons:** it is not the product, and it is rebuilt when generation arrives. A
  list of chunks is not an answer, and showing one publicly blurs AGENTS.md's
  rule "never return an answer without at least one citation" from the other
  side. It writes no meaningful `query_log` row.

## Discarded early

- **Build the intent classifier first** (README roadmap item 4). Nothing
  measured asks for it: retrieval searches both collections by default
  (ADR-018), and the classifier is one more LLM call that needs the key it is
  waiting for. It stays a separate feature with its own measurement.
- **Streaming responses.** Deferred in the README with a trigger ("user feedback
  shows perceived latency friction"). No users yet.
- **Thumbs up/down feedback.** Deferred in the README until v1 is stable.
- **Deploy to Streamlit Cloud as part of this feature.** The page goes public
  only after ADR-020's rule 3 is measured and Accepted. Before that, the one gate
  between a visitor and a fabricated answer is unmeasured. This becomes a stated
  gate in the ADR, not a forgotten step.
- **Upgrade Langfuse to SDK 3.x on the way.** A separate change. The pin to 2.x
  is deliberate (`pyproject.toml`) and the KB is written against it.

## Emerging preference
**Option 1.** The product path and the page are one decision: what a visitor
asks, what comes back, and what is recorded about it. One DEFINE writes it down
once. Splitting the BUILD into two PRs (path, then page) gives the small reviews
Option 2 offers, without splitting the reasoning.

What would change our mind: if DEFINE shows the `query_log` and trace questions
are big enough on their own (for example, a privacy question about storing
visitor questions, which ADR-009 already flags), the path becomes its own
feature, as in Option 2.

### Questions DEFINE must settle
1. **`query_log`:** which new columns (output class, model, prompt version,
   tokens, snapshot id), and what happens to `intent` and `reranker_top_score`
   (left NULL and documented, never dropped from the bootstrap path).
2. **Without a key:** what the local page shows. A clear "generation is not
   configured" message, with no answer and no sources, is the candidate.
3. **A failed call or a non-`end_turn` stop:** what the visitor sees, and what
   the row and the trace record.
4. **The deploy gate:** ADR-020 Accepted before `make deploy`. Stated in the
   ADR, checked by a human, or checked by code?
5. **What counts as done without a key:** tests on a stub, `make dev` against
   the local database showing the no-key message, and a trace in the no-op
   client. The real end-to-end check waits for the key, as ADR-020 does.

## Next step
- [ ] Write DEFINE if a clear direction emerged (after the author confirms)
- [ ] Or park with `status: Parked` and revisit
