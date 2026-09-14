# Cost tracking for data-platform-rag

## What we track

- Per-query cost via the `Generation` entity (Langfuse native)
- Per-day aggregate via dashboard
- Alert threshold: not implemented in v1 (Langfuse cloud free tier). Manual
  review trigger: sustained cost above ~$0.0095/query, i.e. the Section 7 gate
  less a small margin.

## Model definitions

Register Claude Sonnet in Langfuse UI once with correct input/output token
prices from anthropic.com/pricing. Every Generation observation then attaches
cost automatically.

## What we do NOT track

- Embedding cost — bge-small runs locally
- Reranker cost — bge-reranker-base runs locally
- Postgres cost — flat via Neon free tier

## Cost per query estimate

Query shape after the top-k reduction (`rerank_top_k = 3`, decided 2026-09-14 —
see `.claude/dev/logs/2026-09-14-phase0-tracked-findings.md`):

| Component | Tokens | Direction |
|-----------|--------|-----------|
| System prompt (v1.1.0) | ~500 | input |
| Retrieved context (top 3 chunks @ ~400) | ~1200 | input |
| Query | ~50 | input |
| **Input subtotal** | **~1750** | |
| Answer | ~200 | output |
| **Total** | **~1950** | |

At Claude Sonnet 4.6 pricing ($3 / $15 per MTok):

```
input:   1750 × $3/1M   = $0.00525
output:   200 × $15/1M  = $0.00300
                          ---------
total                   ≈ $0.0083 per query
```

That clears the Section 7 publication gate (< $0.01 per non-fallback query),
with roughly 17% of headroom.

**Do not scale this figure linearly with total tokens.** Output tokens cost 5×
input tokens, and output did not shrink when top-k did — only the context did.
Scaling the previous $0.0107 by the token ratio (1950/2750) yields $0.0076,
which understates the real cost by about 8%. Always recompute per direction.

Every number above is an estimate until `make eval-ci` produces measured
Langfuse cost data. Per AGENTS.md, published figures come from runs, not from
this table.

## Fallback queries are free

When the fallback fires, no Generation is created. Only spans up to
threshold_check exist. Fallback queries cost $0 in tokens.
