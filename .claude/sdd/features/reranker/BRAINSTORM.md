# BRAINSTORM: Reranking the top-20 (ADR-005)

> Free exploration. No commitments. No commits from this file alone.

## Date
2026-09-21

## Prompt

ADR-005 has been "Planned" since 2026-09-10 and exists only as a row in
`docs/adr/index.md`: no file, no Context, no decision rule. What it left behind
in code is unused: `RerankedChunk` in `contracts.py`, `settings.rerank_top_k = 3`,
`settings.reranker_model = "BAAI/bge-reranker-base"`.

Two things make it the next question now:

- **`sparse-query-strategy` shipped a rejection** and ended on this open question:
  reranker before term filtering? Recall at k=20 is already 5/6 dense-only, and
  where OR failed was the order at the top, which is what a cross-encoder redoes.
- **Generation will receive `rerank_top_k` = 3 chunks.** Today those are the RRF
  top 3, and recall at k=3 is 3/6. The `retrieval` BUILD_REPORT said it plainly:
  on today's evidence q002 would be answered from the wrong documents.

### What a reranker can and cannot move

Read from the recorded baseline (`retrieval-recall-20260921-142654.json`), not
from a new measurement:

| declared path | rank today | reachable by a reranker of the top 20? |
|---|---|---|
| q001 `0029_snowpipe_streaming…` | 1 | already at k=3; **can only lose** |
| q002 `007_pipeline_unification.md` | 7 | yes |
| q003 `README.md` | 1 | already at k=3; can only lose |
| q003 `0030_avro_and_schema_registry…` | 5 | yes |
| q004 `README.md` (databricks) | 1 | already at k=3; can only lose |
| q004 `0030_avro_and_schema_registry…` | not in top 20 | **no**: never reaches the reranker |

So **the ceiling at k=3 is 5/6**: two paths to gain, three to protect, one out of
reach. This fixes the shape of any decision rule before a model is loaded.

## Options considered

### Option 1: `bge-reranker-base` cross-encoder over the top 20, keep `rerank_top_k`

- **Description.** What the config already names. `CrossEncoder.predict` scores
  each (question, chunk) pair, the 20 are re-sorted by that score, and the first
  `settings.rerank_top_k` become `RerankedChunk`s.
- **Pros.**
  - Already declared: config, contract and the stack in AGENTS.md all name it.
    No new dependency (`sentence-transformers` 6.1.0 has `CrossEncoder`).
  - Local and free at query time, like the embedder.
  - It reads the question and the chunk *together*, which the bi-encoder does not.
    That is the mechanism the q002 case needs.
  - **It produces a relevance score with a meaning**, unlike RRF, whose maximum
    is 0.0164 regardless of relevance. That is where ADR-006's fallback threshold
    can live.
- **Cons.**
  - Not downloaded. Its size, load time and CPU latency for 20 pairs are
    **unmeasured** here; no model-card figure is being used.
  - Its tokenizer is not the embedder's. Chunks are capped at 500 tokens *by
    the bge-small tokenizer*; question + chunk under the reranker's own tokenizer
    may pass 512 and be truncated silently: the same failure ADR-007 was written
    against. Unmeasured.
  - Multilingual XLM-R base, for an English-only corpus: capacity spent on
    nothing.
  - Streamlit Cloud memory is unknown, because no deploy exists.

### Option 2: a small English cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`)

- **Description.** Same mechanism as Option 1, a much smaller model trained on
  MS MARCO passage ranking.
- **Pros.** Smaller and faster by construction (6 layers vs 12), English-only,
  and the same code path as Option 1: the model name is a config field.
- **Cons.**
  - Trained on web search queries against web passages, not on design questions
    against ADR sections. Whether that transfers is exactly what is unmeasured.
  - Changes a declared default, so the ADR has to argue it rather than inherit it.
  - Its raw scores are unnormalised logits, as with Option 1, so a threshold on
    them is calibrated per model, not portable between them.

### Option 3: collapse to one chunk per document before taking the top 3 (no model)

- **Description.** Keep the RRF order and skip any chunk whose
  `(source_project, source_path)` is already in the top 3.
- **Pros.**
  - No model, no latency, deterministic by construction.
  - On the recorded baseline it would lift q003's `0030` from rank 5 into the
    top 3, because the four chunks above it are all `README.md` sections.
- **Cons.**
  - **It improves source recall by definition, not by relevance.** ADR-014
    counts documents; forcing three distinct documents into three slots
    manufactures document recall. The metric would reward it whether or not
    the answer gets better.
  - It hurts single-document questions. q001's best context is two or three
    sections of the *same* ADR (Alternatives, Rationale, Context). Collapse would
    swap those for other documents.
  - It cannot move q002: `007` is behind four other documents, not behind copies
    of one.
  - Better treated as a possible *addition* to Option 1 or 2, decided on its own
    evidence later, than as a reranker.

### Option 4: listwise reranking by Claude (Haiku 4.5)

- **Description.** Send the question and the 20 chunks to an LLM and ask for an
  ordered list of ids, validated by a pydantic model with the one-shot repair
  AGENTS.md requires.
- **Pros.** Likely the strongest relevance judgement of the four. It reads all
  20 at once, so it can prefer complementary chunks over near-duplicates.
- **Cons.**
  - A paid network call inside *retrieval*, before generation. That doubles the
    points of failure, and `make ask` / `make retrieval-recall` would need an API
    key and spend money on every run.
  - Not reproducible run to run, which breaks the two-identical-runs discipline
    every measurement in this project has kept since ADR-014.
  - Contradicts the declared local stack, so it would need an ADR arguing against
    AGENTS.md itself.

## Discarded early

- **A hosted rerank API (Cohere, Voyage).** Brings Option 4's network, secret and
  cost problems without its advantage, plus a new vendor.
- **Fine-tuning a reranker.** There is no training set: 6 labelled paths.
- **ColBERT / late interaction.** A new index and a new storage format to solve a
  problem that is 20 candidates wide.
- **Tuning `RRF_K`.** Rejected as the wrong lever in ADR-015 Alternative 5, and a
  constant cannot recover `007` from rank 7.
- **Reranking only to feed the fallback, without reordering.** It would throw away
  the reordering, which is the reason the reranker exists.

## Cross-cutting questions for DEFINE

1. **The decision rule must cover every reading**, including "nothing moved",
   the hole ADR-015 had. With two paths to gain and three to protect, a per-path
   table fits better than an aggregate threshold. What decided ADR-015 was a
   criterion on a named case (q001), not a threshold.
2. **Before and after in the same run.** `make retrieval-recall` should report k=3
   both pre- and post-rerank, so one artifact carries the comparison on the same
   snapshot.
3. **The fallback is a separate decision.** A cross-encoder score finally gives
   ADR-006 something to threshold, but the golden set has **one** out-of-scope
   question. One point cannot calibrate a threshold. Proposal: record q005's
   rerank score next to the in-scope ones, as `retrieval` did for RRF, and leave
   the threshold to its own ADR.
4. **Truncation must be measured, not assumed**: how many (question, chunk) pairs
   exceed the reranker's window under its own tokenizer.
5. **Determinism**: two consecutive runs must give identical scores. Ties in
   rerank score break by RRF order, then id.
6. **Latency and memory** are recorded as measured on this machine, with
   Streamlit Cloud marked unmeasurable until a deploy exists.

## Feasibility probe (2026-09-21)

Measured before DEFINE, on purpose **without looking at rankings or scores**: a
scratch script loaded each model, scored the RRF top 20 of all five golden
questions, and printed only cost, truncation and determinism. The decision rule
can still be fixed blind to the outcome.

Same machine (CPU, 4 threads), same 100 (question, chunk) pairs:

| | Option 1: `bge-reranker-base` | Option 2: `ms-marco-MiniLM-L-6-v2` |
|---|---|---|
| on-disk size | 1134 MB | 92 MB |
| RSS added on load | +561 MB | +79 MB |
| load, cached | 6.2 s | 5.0 s |
| **latency per question, 20 pairs** | **15.2–16.2 s** | **2.4–2.8 s** |
| pairs over 512 tokens | **18 / 100** (median 344, max 717) | 0 / 100 (median 314, max 510) |
| two scoring passes identical | yes | yes |

- **Option 1's tokenizer inflates the chunks.** A chunk capped at 500 tokens by
  bge-small's WordPiece reaches 717 under XLM-R's SentencePiece. Nearly one pair
  in five would lose its tail silently, the failure ADR-007 exists to prevent.
- **Option 2 shares the embedder's tokenizer family**, so ADR-007's cap holds, but
  with a margin of 2 tokens: the longest pair is 510 of 512. A longer question
  would truncate.
- **Neither number says which model ranks better.** That remains unmeasured.

Not measured, and so not used as argument: fewer candidates (top 10), batching
by length to cut padding, ONNX or quantised inference.

## Emerging preference

**Option 2, `ms-marco-MiniLM-L-6-v2`, as the candidate, with Option 1 kept in the
BUILD measurement as the comparison.** The probe triggered this file's own
mind-changer: Option 1 costs about 16 s per question and truncates 18 % of its
pairs, before generation has spent anything. Option 2 costs about 2.5 s and
truncates none.

This is a preference on **cost**, not on **quality**. BUILD still runs both
under one rule fixed in DEFINE, and Option 1 can win back on ranking quality
only if the rule says a quality gain justifies ~6× the latency. The rule must
say that before the measurement.

Changing the default from `bge-reranker-base` means ADR-005 argues against
`config.py`, AGENTS.md's stack line and `PRE_BUILD_VALIDATION.md`, all of which
name Option 1. Whichever model wins, those three change in the same pass.

Option 3 is parked as a possible later addition, because it games the metric
this project decides with. Option 4 is out while the stack is local and
measurements must reproduce.

**What would change our mind:**

- ~~Option 1 truncates a meaningful share of pairs, or is too slow.~~ **Measured:
  both.** Option 2 leads on cost.
- Option 2 ranks visibly worse than Option 1 on the golden set, by a margin the
  DEFINE rule says is worth ~6× the latency. Then Option 1 comes back.
- Neither moves q002 or q003-`0030` into the top 3. Then reranking is not the
  bottleneck at this scale, and the next place to look is the embedding (ADR-004)
  or the golden set itself (q004's anchor).
- Either one drops q001, q003-`README` or q004-`README` out of the top 3. Same
  lesson as ADR-015: a gain that costs a protected path does not ship.

## Next step

- [ ] Write DEFINE with the decision rule fixed before any model is loaded
- [ ] Or park with `status: Parked` and revisit
