# SHIPPED: Reranking the top-20 (ADR-005)

## Metadata

| Field | Value |
|-------|-------|
| Feature | reranker |
| Shipped date | 2026-09-22 |
| PR | [#7](https://github.com/christiandrocha/data-platform-rag/pull/7), merged by rebase |
| Deploy | **none exists.** `ui/app.py` is a TODO stub and no Streamlit Cloud URL has ever been published |
| ADR | [ADR-005](../../../../docs/adr/ADR-005-cross-encoder-reranking.md) — **Rejected** |

## What shipped, and what did not

**The feature this DEFINE asked for did not ship.** Its goal was a better top-3
order from a cross-encoder over the RRF top 20. Two models were built into the
stage, measured, and rejected by a rule written before the measurement.
Retrieval behaves as it did before this feature, which the recall artifact
proves ranking for ranking (`-220507` == `-163500`).

What shipped is the evidence, and the instrument that produced it:

- ADR-005, Rejected in place, with per-path ranks, measured cost and the top
  score per question.
- The stage as measured, kept as commit `3b07aa1` and reverted by `e391a69`.
  A re-measurement is one `git revert` away, with the same code.
- The README no longer claims a "~100ms" reranker. It was never measured, and
  both models measured in seconds.
- AGENTS.md, ARCHITECTURE.md, rag-architect and the KB describe the pipeline
  that runs, not the one that was planned.

## What users see

Nothing. There is no UI and no generation. The curator sees the same
`make ask` and `make retrieval-recall` output as before.

## What we learned

**The per-path rule did the job an aggregate threshold would have failed.**
MiniLM raised recall at k=3 from 3/6 to 4/6. A threshold on the total would
have shipped it. The rule protects each path, and MiniLM had moved q004's
protected `README.md` from rank 1 to rank 8. On six paths, two gained and one
lost is a swap.

**The rule covered the reading this time.** ADR-015's rule had no row for
"nothing moved". This DEFINE listed all nine combinations of the two models'
classifications in advance, and the result landed in a written row: rejected
against rejected.

**Both models failed on the same question, which points upstream.** Two
different cross-encoders lost the same protected path on q004, the question
that already had one unreachable path. That points to what reaches the top 20,
or to how q004 is anchored, more than to the choice of reranker. It is a
hypothesis, recorded in ADR-005 and not acted on.

**A documented number had never been measured.** "~100ms latency" sat in the
README's stack table from the start. The measurement said 3–5 s for the
smallest model and 18–29 s for the one the README named.

## Retrospective for the log

- **Commit the measured implementation, then revert it.** ADR-015's OR
  expression survives only as prose. This feature kept the code that produced
  the numbers as its own commit, so the next measurement uses the same
  instrument instead of a rewrite.
- **Write drafts to disk before pausing.** The BUILD_REPORT draft lived only in
  the conversation and was lost across the session break. It was re-derived
  from ADR-005's Outcome, and a criterion with no recorded evidence (the q002
  `make ask` check) was left out rather than marked done from memory.
- **Measured latency is not stable across runs on a shared machine.** BUILD
  measured higher than the feasibility probe for both models. Any future
  latency criterion should name the conditions it is measured under.
- **Next decision:** the embedding (ADR-004) or q004's anchors in the golden
  set. Two fixes to the top-3 order have now been rejected, and both left
  recall at k=20 at 5/6.
