# DEFINE: Reranking the top-20 (ADR-005)

> Reorder the RRF top 20 with a cross-encoder so the three chunks generation
> receives are the right ones, and decide by a rule fixed here which model, if
> any, does it.

## Metadata

| Field | Value |
|-------|-------|
| Feature | reranker |
| Date | 2026-09-21 |
| Author | christiandrocha |
| Status | Ready for Design |
| Clarity Score | 13/15 |
| BRAINSTORM | [BRAINSTORM.md](BRAINSTORM.md) — emerging preference: Option 2 (`ms-marco-MiniLM-L-6-v2`) on cost, Option 1 (`bge-reranker-base`) measured alongside |

## Problem statement

Generation will receive `settings.rerank_top_k` = 3 chunks, and today those are
the RRF top 3: source recall at k=3 is **3/6**. q002's declared ADR sits at rank
7 and q003's `0030` at rank 5, both inside the top 20 and outside the top 3, so
on today's evidence two answers would be grounded on the wrong documents.
Nothing between retrieval and generation can fix the order, because the
reranking stage ADR-005 names exists only as an index row, an unused contract
and two unused settings.

## Users

| User | Role | Pain point |
|------|------|-----------|
| The curator (repo author) | Runs `make ask` / `make retrieval-recall` | Sees the right document at rank 5–7 and has no stage that can promote it |
| Generation, once built | Consumes `rerank_top_k` chunks | Would answer q002 from `001_databricks_vs_snowflake.md` instead of the ADR that decided it |
| The fallback (ADR-006), once built | Needs a score to threshold | RRF tops out at 0.0164 for any non-empty result; there is nothing meaningful to compare 0.35 against |
| The end user | Asks about platform decisions | Hypothetical: no UI exists. Their tolerance for latency is unknown, which is why this DEFINE refuses to invent a latency ceiling |

## Goals (prioritized)

| Priority | Goal |
|----------|------|
| MUST | A rerank stage turns the RRF top `settings.hybrid_top_k` into the top `settings.rerank_top_k` as `RerankedChunk`s |
| MUST | The model is a config field; both candidates run through the same code path, switched by `RERANKER_MODEL` alone |
| MUST | `make retrieval-recall` reports k=3 **before and after** reranking in one artifact, naming the model and the snapshot |
| MUST | The decision below is applied as written, including its "nothing moved" and "both rejected" rows |
| MUST | `make test` loads no model and needs no network, as today |
| SHOULD | A pair longer than the model's window is **counted and reported**, never truncated silently |
| SHOULD | `make ask` shows the rerank score next to the RRF score |
| SHOULD | q005's top rerank score is recorded next to the four in-scope ones, as evidence for a later fallback ADR |
| COULD | Per-question rerank latency is written into the artifact |

## Success criteria (measurable)

Before-reading: `.claude/dev/reports/retrieval-recall-20260921-163500.json`,
snapshot `sdd-kafka-databricks@f1295df9`, `sdd-kafka-snowflake-2@82a2e269`.
k=3 **3/6**, k=10 **5/6**, k=20 **5/6**.

The six declared paths fall into three groups, fixed now from that artifact:

| group | paths | today |
|---|---|---|
| **Gainable** | q002 `007_pipeline_unification.md` (rank 7), q003 `0030_avro…` (rank 5) | in top 20, outside top 3 |
| **Protected** | q001 `0029_snowpipe…`, q003 `README.md`, q004 `README.md` (databricks) | in top 3 |
| **Unreachable** | q004 `0030_avro…` | not in top 20; no reranker of the top 20 can reach it |

- [ ] For each model, post-rerank k=3 reported per path, from one artifact per model
- [ ] The adopted model loses **0 of 3** protected paths from the top 3
- [ ] The adopted model gains **≥ 1 of 2** gainable paths into the top 3
- [ ] Two consecutive runs per model produce **identical** rerank scores and orderings
- [ ] Truncated pairs for the adopted model reported; the count on the golden set is **0** or the truncation is a recorded gap
- [ ] `make test` green with **≥ 8** new tests, none of which loads a model
- [ ] Recall at k=20 is **unchanged** (5/6), by construction: a reranker of the top 20 cannot change it; if it does, the stage is wrong

**The decision rule, fixed before any ranking is looked at:**

Each model is first classified on its own:

| reading | classification |
|---|---|
| loses ≥ 1 protected path from the top 3 | **rejected** — no gain compensates; a swap on n=6 is churn, not improvement |
| loses none, gains 0 | **no effect** — reranking is not the bottleneck at this scale |
| loses none, gains ≥ 1 | **eligible** |

Then the two are compared:

| MiniLM-L-6 | bge-reranker-base | verdict |
|---|---|---|
| eligible | any | **MiniLM ships.** The bge does not win back on one extra path of six at ~6× the latency |
| no effect / rejected | eligible | **bge ships**, with its measured latency and truncation recorded as known gaps and the unmeasured reductions (top 10, length batching, ONNX) as the next step |
| no effect | no effect / rejected | **Neither ships.** ADR-005 is Rejected; the next place to look is the embedding (ADR-004) or q002/q003's anchors |
| rejected | rejected / no effect | **Neither ships.** ADR-005 is Rejected, with each rejected model's lost path recorded |

Every combination of the two classifications falls in exactly one row: 3 + 2 + 2
+ 2 = 9, the three classifications of one model against the three of the other.

## Acceptance tests

- [ ] `make ask q="Why does the Databricks project use one unified Lakeflow pipeline instead of many parametrized notebooks?"` prints `rerank_top_k` rows with a rerank score beside the RRF score
- [ ] `RERANKER_MODEL=BAAI/bge-reranker-base make retrieval-recall` and the same with `cross-encoder/ms-marco-MiniLM-L-6-v2` both run with **no code change** and write artifacts naming their model
- [ ] Each artifact carries k=3 pre- and post-rerank, per-path ranks, the snapshot SHAs and the truncated-pair count
- [ ] A unit test with a fake scorer asserts the reorder is by rerank score, ties broken by RRF order and then by id
- [ ] A unit test asserts an empty candidate list returns `[]` **without loading the model**
- [ ] A unit test with a fake tokenizer asserts a pair over the window is counted, not silently passed
- [ ] A unit test asserts the stage returns exactly `rerank_top_k` chunks when given more, and all of them when given fewer
- [ ] `make test` passes with the model absent from the Hugging Face cache

## Non-goals

- **The fallback threshold.** A cross-encoder score gives ADR-006 something to
  threshold, and one out-of-scope question cannot calibrate it. q005's score is
  recorded; the threshold is its own ADR.
- **Latency optimisation**: top 10 instead of 20, length batching, ONNX,
  quantisation. Unmeasured, and only opened if the bge row of the rule fires.
- **One-chunk-per-document collapse** (BRAINSTORM Option 3). It raises the metric
  this project decides with by construction.
- **LLM reranking** (Option 4).
- **q004's missing Snowflake ADR.** Unreachable by definition here.
- **Growing the golden set**, generation, UI, deploy.

## Open questions

- [ ] **Where does the model load, and when?** A cached singleton like the
      embedder's `get_model()`, loaded on first rerank — DESIGN decides, and
      states the 5–6 s cold load it costs.
- [ ] **Does `retrieve()` rerank by default, or does a new function wrap it?**
      `make retrieval-recall` needs both lists from one retrieval. DESIGN decides.
- [ ] **What does the stage do with a pair over the window?** Truncate and count,
      or drop the chunk. DEFINE only requires that it is not silent.
- [ ] **Whichever model ships, what else names the default?** `config.py`,
      AGENTS.md's stack line, `PRE_BUILD_VALIDATION.md` and the KB all say
      `bge-reranker-base`. DESIGN lists them; BUILD changes them in one pass.

## Clarity Score self-check

| Dimension | Score | Notes |
|-----------|-------|-------|
| Problem is specific and testable | 5 | Two named paths at named ranks, a recorded artifact, and a ceiling (5/6) derived before any model ran |
| Users are named and their pain is real | 4 | The curator's pain is current; generation's and the fallback's are real but downstream of stages that do not exist yet; the end user is hypothetical |
| Success criteria include numbers | 4 | Every criterion has one, and the rule covers every reading. Not a 5: the denominator is six, so one question decides a row, and no number here can say more than that |

**Total: 13/15** — above the 12/15 gate.
