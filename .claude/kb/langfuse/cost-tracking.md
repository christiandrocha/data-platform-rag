# Cost tracking for data-platform-rag

## What we track

- Per-query cost via the `Generation` entity (Langfuse native)
- Per-day aggregate via dashboard
- Alert threshold: not implemented in v1 (Langfuse cloud free tier)

## Model definitions

Register Claude Sonnet in Langfuse UI once with correct input/output token
prices from anthropic.com/pricing. Every Generation observation then attaches
cost automatically.

## What we do NOT track

- Embedding cost — bge-small runs locally
- Reranker cost — bge-reranker-base runs locally
- Postgres cost — flat via Neon free tier

## Cost per query estimate

Typical query shape (~2750 tokens per query):
- System prompt: ~500 tokens
- Retrieved context (top 5 chunks): ~2000 tokens
- Query: ~50 tokens
- Answer: ~200 tokens

Under $0.005 per query is expected. If dashboard shows > $0.01/query
systematically, investigate — either context is bloated or fallback isn't
firing often enough.

## Fallback queries are free

When the fallback fires, no Generation is created. Only spans up to
threshold_check exist. Fallback queries cost $0 in tokens.
