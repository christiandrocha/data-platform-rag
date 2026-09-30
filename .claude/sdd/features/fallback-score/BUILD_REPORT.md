# BUILD REPORT: Does cosine similarity separate in scope from out of scope?

## Metadata

| Field | Value |
|-------|-------|
| Feature | fallback-score |
| DEFINE | [DEFINE.md](DEFINE.md) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| ADR | [ADR-019](../../../../docs/adr/ADR-019-similarity-separability-decides-the-fallback-gate.md), **Accepted, branch "not separable"**, 2026-09-30. Supersedes ADR-006's score gate |
| Start date | 2026-09-30 |
| End date | 2026-09-30 |
| PR | not opened yet |

## Outcome in one paragraph

The recall report now records every question's top-1 cosine similarity, and the
one measurement it enabled took the fork's **not separable** branch. The highest
out-of-scope question (q005, 0.7360) outscores 14 of the 45 in-scope questions,
and 4 of the 5 out-of-scope questions sit above the lowest in-scope one (q027,
0.6040). Only the prompt-extraction probe (q050, 0.5628) sits below them all.
Similarity measures topic proximity, not answerability. ADR-006's score gate was
superseded in part: the fallback stays, and the LLM sends it under rule 3.
Retrieval did not move (38/44/46, 50/50 identical rankings).

## What was built

Cited by commit subject (the branch may be rebase-merged):

1. `docs(adr): ADR-019 planned -- similarity separability decides the fallback gate`.
   ADR Planned, with the fork copied byte-identical from DEFINE.
2. `feat(eval): top-1 similarity separability in the recall report (ADR-019, pre-measurement)`.
   - `scripts/retrieval_recall.py`: `dense_distance` per ranked chunk,
     `top_similarity` per question, a pure `separability()` returning the four
     numbers, and a printed block with the out-of-scope questions and the lowest
     in-scope ones sorted by similarity. It replaces the "Top RRF score per
     question" printout, whose 50 values were all `1/61`. `top_rrf_scores` stays
     in the artifact (DEFINE Q2)
   - `scripts/ask.py`: a `sim` column
   - `tests/unit/test_retrieval_recall.py`: 7 tests (top similarity, separable,
     one overlap, exact tie, intent-based population, recall population, a
     missing class)
3. This commit, docs after the Outcome:
   - ADR-019 Outcome, Status Accepted, and the ADR index
   - ADR-006: score gate superseded in place, fallback kept
   - AGENTS.md RAG-discipline line: the LLM sends the fallback under rule 3, with
     no score gate
   - README: the query-path text, the mermaid diagram (the fallback edge now
     leaves the LLM), the ASCII architecture, and the Known Gaps bullet
   - `config.py`: a comment marks `fallback_threshold` unused (value unchanged),
     mirrored in KB `pydantic/config-pattern.md`
   - KB: `rag/dense-retrieval.md` ("What the score cannot do"),
     `rag/rag-architecture.md` principle 1, `langfuse/python-sdk.md` (the example
     no longer gates on a score), `langfuse/traces-and-generations.md` (no
     `threshold_check` span), `langfuse/cost-tracking.md` ("Fallback queries are
     not free")

## The measurement

Pre-measurement checks: the fork is byte-identical to DEFINE's (`awk` range and
`diff`, 14 lines). The golden set is unchanged. `--baseline` confirmed the same
snapshot, model and declared paths. `make lint` was clean and `make test` passed
227.

`make retrieval-recall baseline=.claude/dev/reports/retrieval-recall-20260930-182208.json`,
twice (`-20260930-185210.json`, `-185224.json`; `results` and `summary` equal):

```
Separability of top-1 cosine similarity (ADR-019, numbers only):
  lowest in-scope:     0.6040  (q027, of 45)
  highest out-of-scope: 0.7360  (q005, of 5)
  in-scope at or below the highest out-of-scope: 14
  out-of-scope at or above the lowest in-scope:  4

  out-of-scope, by top similarity:
    q050  0.5628
    q049  0.6228
    q048  0.6519
    q047  0.7194
    q005  0.7360

  A1  k=3 found:   38 -> 38 /57  (+0)
  A2  top-3 paths lost: 0
  A3  k=10 found:  44 -> 44 /57
      k=20 found:  46 -> 46 /57
      sparse-empty questions ranked identically: 50/50  (ADR-018 A4)
```

Both counts are non-zero, so the reading is **not separable**. Predictions: P1
right, P2 right (4), P3 wrong and inverted (q005 is the highest, not the lowest).

## What deviated from design

- **The "Top RRF score per question" printout was replaced**, not kept alongside.
  DESIGN only added a block. Fifty lines of `0.01639` hid the new block and carried
  no information. The values stay in the artifact's `top_rrf_scores`.
- **The KB `langfuse/python-sdk.md` example also stopped calling `rerank()`.**
  It slices `candidates[: settings.rerank_top_k]` now. The reranker was rejected by
  ADR-005, and a corrected example should not reintroduce it. This is outside the
  feature's letter, and it is recorded here.
- **README's diagram changed shape**: the fallback edge leaves the LLM node, not
  the reranker node. DEFINE only required that the README "stop implying a
  calibrated 0.35 cosine gate exists".

## RAGAS delta

**Not measured. `make eval` does not produce scores yet.** On 2026-09-30 it prints
`scripts/run_evaluation.py — not yet implemented (BUILD phase pending)`. No number
is written here.

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | pending | pending | — |
| Context Precision | pending | pending | — |
| Answer Relevance | pending | pending | — |
| Context Recall | pending | pending | — |
| Fallback rate | pending | pending | — |

This feature's decision moves the fallback onto the LLM, which makes
`fallback_accuracy` the number that matters most once `make eval` exists.

## Query plan

Not affected. No SQL changed, so `sql/99_verify.sql` was not re-run for this
feature. ADR-018's BUILD_REPORT holds the current plan.

## Known gaps at merge time

- **The fallback now depends on the LLM, and that is unmeasured**
  (`fallback_accuracy`). It needs generation and an API key. Recorded in README
  Known Gaps.
- **`settings.fallback_threshold` and `rrf_score` still exist.** Both leave in the
  ADR-019 follow-up (DEFINE), a contract and config change of its own.
- **KB `langfuse/traces-and-generations.md` still shows a "reranking" span**, and
  KB `rag/rag-architecture.md` principle 4 still claims a reranking lift. ADR-005
  rejected reranking. Both predate the feature and are flagged, not changed.
- **README Known Gaps says "The golden set holds 5 of 50 questions".** It holds 50.
  This predates the feature and is flagged.
- **3 integration tests skip** without `/tmp/dpr-corpus-*`. This predates the
  feature.

## Verification

- [x] `make lint` clean
- [x] `make test` green: 227 passed, 3 skipped
- [ ] `make eval` results attached: **not possible**, stub
- [x] `make verify-indexes`: not applicable, no query changed
- [x] Two identical runs. The fork was applied once, to the first
- [x] Retrieval unchanged: 38/44/46 and 50/50 identical rankings against ADR-018's artifact
