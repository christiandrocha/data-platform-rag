# BUILD REPORT: Reranking the top-20 (ADR-005)

## Metadata

| Field | Value |
|-------|-------|
| Feature | reranker |
| DEFINE | [DEFINE.md](DEFINE.md) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| ADR | [ADR-005](../../../../docs/adr/ADR-005-cross-encoder-reranking.md) — **Rejected** |
| Start date | 2026-09-21 |
| End date | 2026-09-21 |
| PR | pending |

## Outcome in one paragraph

The rerank stage was built, tested and measured with two local cross-encoders,
and **the rule fixed in DEFINE rejected both**. Each one lost q004's protected
databricks `README.md` from the top 3: MiniLM-L-6 moved it to rank 8,
bge-reranker-base to rank 4. MiniLM raised recall at k=3 from 3/6 to 4/6, and
the rule still rejected it, because it protects each path rather than the total.
The stage is reverted. The implementation stays in history as commit `94accd9`,
so the measurement can be re-run with the same instrument. After the revert,
`make retrieval-recall` reproduces the pre-feature artifact exactly.

## What was built (and what remains after the revert)

| File | Change | Status |
|---|---|---|
| `data_platform_rag/retrieval/reranker.py` | Cached `CrossEncoder` over `settings.reranker_model`, one `predict` per question, over-window pairs flagged; ties by RRF score, then id | **reverted** |
| `data_platform_rag/retrieval/pipeline.py` | `retrieve_and_rerank()`; `retrieve()` untouched | **reverted** |
| `data_platform_rag/contracts.py` | `RerankedChunk.truncated`, required, no default | **reverted** |
| `scripts/ask.py`, `Makefile` | `make ask` reranks by default; `NO_RERANK=1` shows the RRF list | **reverted** |
| `scripts/retrieval_recall.py` | k=3/10/20 pre- and post-rerank from one retrieval; model, activation, load time, latency, truncated pairs in the artifact | **reverted** |
| `tests/unit/test_reranker.py`, `test_retrieval_recall.py`, `test_contracts.py` | 15 tests, none loads a model | **reverted** |
| `.claude/kb/pydantic/models.md` | `truncated` field mirrored | **reverted** with the contract |
| `docs/adr/ADR-005-…md` | Status → Rejected, Outcome section added in place | — |
| `docs/adr/index.md` | ADR-005 row → Rejected, 2026-09-21 | — |
| `README.md` | "~100ms latency" replaced with the measured seconds; diagram, stack table and "What is next" updated | **kept** |
| `AGENTS.md`, `ARCHITECTURE.md`, `rag-architect.md` | Reranker described as measured and rejected, not as a live stage | **kept** |
| `.claude/kb/pydantic/config-pattern.md` | `rerank_top_k` default 5 → 3, to match `config.py` | **kept** |
| `.claude/kb/langfuse/cost-tracking.md` | No reranker cost, because no reranker runs | **kept** |

`settings.reranker_model` and `settings.rerank_top_k` stay in `config.py`, so a
re-measurement is one `git revert` plus one setting away.

`make test`: 182 → 197 with the stage → **182** after the revert.

## What deviated from design

- **15 tests, not the 12 in the test plan.** DEFINE asked for ≥ 8. All 15 run
  offline with an empty Hugging Face cache.
- **The `make ask` opt-out is `NO_RERANK=1`, not `--no-rerank`.** It is a make
  target, so an environment variable is how a flag reaches it.
- **Measured latency is higher than the feasibility probe's for both models**
  (MiniLM 3.16–5.44 s against 2.4–2.8 s; bge 18.11–28.99 s against 15.2–16.2 s).
  BUILD also counts tokens per pair, and the two ran at different times on a
  shared machine. Recorded in ADR-005, not explained away.
- **bge-reranker-base truncated 18 of 100 pairs** on the golden set. DEFINE
  allowed that only as a recorded gap for an adopted model. The model was
  rejected, so it is a recorded fact, not a gap.
- **The KB's `rerank_top_k` default was already wrong** (5, against 3 in
  `config.py`) before this feature. Corrected in the same pass.
- **DESIGN's open question on activations is answered:** MiniLM-L-6 `predict`
  returns raw logits (Identity), bge-reranker-base applies a Sigmoid.

## Measurement

Same snapshot throughout (`sdd-kafka-databricks@f1295df9`,
`sdd-kafka-snowflake-2@82a2e269`). Before: `retrieval-recall-20260921-163500.json`.
MiniLM-L-6: `-210556` and `-210622`. bge-reranker-base: `-210824` and `-211026`.
Each pair identical. After revert: `-220507`, identical to before.

| | RRF (before) | MiniLM-L-6 | bge-reranker-base | after revert |
|---|---|---|---|---|
| source recall k=3 | 3/6 | 4/6 | 3/6 | 3/6 |
| source recall k=10 | 5/6 | 5/6 | 5/6 | 5/6 |
| source recall k=20 | 5/6 | 5/6 | 5/6 | 5/6 |
| protected paths lost from top 3 | — | **1** (q004, → 8) | **1** (q004, → 4) | — |
| gainable paths gained into top 3 | — | 2 | 1 | — |
| classification | — | **rejected** | **rejected** | — |

Per-path ranks, the cost table and the top score per question (including q005)
are in ADR-005's Outcome. They are not repeated here.

### DEFINE success criteria

- [x] Post-rerank k=3 reported per path, one artifact per model (two per model)
- [ ] **The adopted model loses 0 of 3 protected paths: no model adopted.** Both lost q004's `README.md`
- [ ] The adopted model gains ≥ 1 of 2 gainable paths: no model adopted (MiniLM 2, bge 1)
- [x] Two consecutive runs per model identical
- [x] Truncated pairs reported (MiniLM 0, bge 18 of 100)
- [x] `make test` green with ≥ 8 new tests, none loads a model (15)
- [x] Recall at k=20 unchanged, 5/6 for both models

Verdict by the rule's last row, rejected against rejected: **neither ships.**

## RAGAS delta

**Not applicable, and no number is written.** RAGAS grades generated answers,
and no generation exists. The metric standing in for it is source recall at k
(ADR-014), above: +1 path at k=3 for MiniLM before the revert, zero after.

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | pending | pending | — |
| Context Precision | pending | pending | — |
| Answer Relevance | pending | pending | — |
| Context Recall | pending | pending | — |
| Fallback rate | pending | pending | — |

`make eval` not run: `scripts/run_evaluation.py` is a stub.

## Known gaps at merge time

- **The top-3 order is still unfixed.** Two attempts are now measured and
  rejected: ADR-015 and ADR-005. The next place to look is the embedding
  (ADR-004), which decides what reaches the top 20.
- **q004's anchoring is in doubt, and that is a hypothesis, not a measurement.**
  One declared path is unreachable, and both rerankers lost the other. It is an
  input to the golden-set work, not acted on here.
- **The next decision rule must say in advance** what happens when a protected
  path is lost on a question whose anchoring is itself in doubt.
- **ADR-006's fallback threshold still has nothing to operate on.** Both
  cross-encoders separated q005 from the in-scope questions, where RRF did not.
  One out-of-scope question calibrates nothing.
- **Six declared paths is a small sample.** Re-run this measurement when the
  golden set grows: `git revert` the revert commit, then the same two
  `make retrieval-recall` calls.

## Verification

- [x] `make lint`: ruff and bandit clean (bandit only notes existing `nosec` lines)
- [x] `make test`: 182 passed, with Postgres up (re-run 2026-09-22)
- [ ] `make eval`: not applicable, no generation exists
- [ ] `make verify-indexes`: not run, since this feature changed no SQL and no index
- [x] `make retrieval-recall`: twice per model, once after the revert; artifacts listed above
