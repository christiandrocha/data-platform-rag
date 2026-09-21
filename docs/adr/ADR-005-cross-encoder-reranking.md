# ADR-005 — Cross-encoder reranking of the RRF top 20

**Status**: Planned — decision rule fixed here, promoted or rejected by the measurement in BUILD
**Date**: 2026-09-21

> Listed in the index since 2026-09-10 as "Reranking with bge-reranker-base
> cross-encoder", with no file behind it. This is the first written version. The
> title is neutral on purpose: which model, if any, is what this ADR decides.

## Context

Generation will receive `settings.rerank_top_k` = 3 chunks. Today those are the
first three of the RRF fusion (ADR-003), and source recall at k=3 (ADR-014) is
**3/6**, against **5/6** at k=20. Two declared paths sit inside the top 20 but
outside the top 3: q002's `007_pipeline_unification.md` at rank 7 and q003's
`0030_avro_and_schema_registry…` at rank 5. On today's evidence, two answers
would be grounded on the wrong documents.

The problem is the order at the top. `sparse-query-strategy` tried to fix it
with a populated sparse side and was rejected (ADR-015): recall did not move, and
q001's correct ADR tied with a wrong one. A bi-encoder embeds the question and
the chunk separately; a **cross-encoder** reads them together, which is the
mechanism this case lacks.

What a reranker of the top 20 can reach is fixed before any model runs (baseline
`retrieval-recall-20260921-163500.json`, snapshot `f1295df9` / `82a2e269`):

| group | paths |
|---|---|
| gainable | q002 `007…` (rank 7), q003 `0030…` (rank 5) |
| protected | q001 `0029…`, q003 `README.md`, q004 `README.md` — already in the top 3 |
| unreachable | q004 `0030…` — not in the top 20 |

**The ceiling at k=3 is 5/6.**

### Two candidates, and what they cost

The project has named `bge-reranker-base` since 2026-09-10, by argument; the
README credits it with "~100ms latency" that was never measured. A feasibility
probe on 2026-09-21 measured it beside a smaller English model, on the same
100 (question, chunk) pairs, **printing no rankings and no scores**, so the rule
below is still fixed blind to the outcome:

| | `BAAI/bge-reranker-base` | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
|---|---|---|
| on disk | 1134 MB | 92 MB |
| RSS on load | +561 MB | +79 MB |
| **latency, 20 pairs, CPU** | **15.2–16.2 s** | **2.4–2.8 s** |
| pairs over 512 tokens | **18 / 100** (max 717) | 0 / 100 (max 510) |
| deterministic across two passes | yes | yes |

`bge-reranker-base` uses XLM-R's tokenizer, under which a chunk ADR-007 capped at
500 tokens (WordPiece) reaches 717. One pair in five would be scored on a
truncated chunk. MiniLM shares the embedder's tokenizer family and truncates
none, with a margin of 2 tokens.

## Decision

**Add a cross-encoder stage that reorders the RRF top `settings.hybrid_top_k`
and passes the first `settings.rerank_top_k` on**, with the model chosen between
the two candidates by the rule below. The model is `settings.reranker_model`;
both candidates run through the same code, switched by `RERANKER_MODEL` alone.

- The score is the model's raw `predict` output, stored in
  `RerankedChunk.rerank_score` and never compared against a constant here.
- A pair over the model's window is scored truncated and **flagged**
  (`RerankedChunk.truncated`), never dropped and never silent.
- Ties break by RRF score, then id.
- `retrieve()` is unchanged; `retrieve_and_rerank()` composes the two, so source
  recall keeps its pre-rerank definition and gains a post-rerank reading.

**Status is Planned.** BUILD runs `make retrieval-recall` once per model, twice
each, on the same snapshot, and this ADR is promoted or rejected by:

Each model on its own:

| reading | classification |
|---|---|
| loses ≥ 1 protected path from the top 3 | **rejected** |
| loses none, gains 0 | **no effect** |
| loses none, gains ≥ 1 | **eligible** |

The two compared:

| MiniLM-L-6 | bge-reranker-base | outcome |
|---|---|---|
| eligible | any | **Accepted with MiniLM.** One extra path of six does not buy ~6× the latency |
| no effect / rejected | eligible | **Accepted with bge**, its latency and truncation as known gaps |
| no effect | no effect / rejected | **Rejected** — reranking is not the bottleneck at this scale |
| rejected | rejected / no effect | **Rejected**, each rejected model's lost path recorded |

The rows cover all nine combinations: 3 + 2 + 2 + 2.

## Consequences

**Generation gets a stage that can fix the order it receives**, on a question
that today would be answered from the wrong ADR.

**There is finally a relevance score.** RRF tops out at 0.0164 for any non-empty
result, which is why ADR-006's 0.35 threshold is meaningless today. A
cross-encoder score can carry a threshold. **This ADR does not set one:** the
golden set has one out-of-scope question, and one point calibrates nothing.
q005's rerank score is recorded for the ADR that will.

**Latency moves from milliseconds to seconds.** 2.4–2.8 s per question with
MiniLM, 15.2–16.2 s with bge, measured on this machine's CPU, before generation
spends anything. The README's "~100ms" is corrected whatever the outcome.
Streamlit Cloud is unmeasurable until a deploy exists.

**A second tokenizer now reads the chunks.** ADR-007's 500-token cap was set
against the embedder's tokenizer. The truncation count per run is the check that
the cap still holds for the reranker's.

**A cold process pays for a model load**: 5.0 s (MiniLM) or 6.2 s (bge) from
cache, and a one-off download of 92 MB or 1,134 MB. `make test` loads no model;
CI never downloads one.

**Decided on six paths.** One question decides a row of the rule. The verdict is
directional, like every number since ADR-014, and must be revisited when the
golden set grows.

## Alternatives considered

**1. `bge-reranker-base` without a comparison.** What the index row promised.
Rejected as a *default* on the probe: ~16 s per question and 18 % truncated
pairs. It remains a candidate in the rule above.

**2. One chunk per document before the top 3 (no model).** Raises document
recall by construction, because ADR-014 counts documents. It would win on the
metric without being better, and it evicts the second and third sections of the
one ADR a single-document question needs.

**3. Listwise reranking by an LLM.** Likely the strongest judgement, but it puts
a paid network call inside retrieval, needs an API key for `make ask`, and does
not reproduce run to run, which every measurement here depends on.

**4. A hosted rerank API (Cohere, Voyage).** The LLM option's network, secret and
cost, plus a new vendor, without its advantage. `PRE_BUILD_VALIDATION.md` §R
already kept Cohere as a v2 candidate only.

**5. Fine-tuning a reranker.** There is no training set: six labelled paths.

**6. No reranker, and work on the embedding instead (ADR-004).** Not an
alternative so much as the next step if this ADR is rejected: the rule's
"no effect" rows point there.
