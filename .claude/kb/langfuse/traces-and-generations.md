# Trace hierarchy for data-platform-rag

## Structure per query

```
Trace: "query"
  metadata: {intent, collections_searched, fallback_fired, latency_ms}
  input:  user query text
  output: final answer (or fallback message)

  ├─ Span: "intent_classification"
  │    input: query text
  │    output: {intent: "decision", confidence: 0.87}
  │    latency: ~200ms
  │
  ├─ Span: "hybrid_retrieval"
  │    input: {query, collections, top_k}
  │    output: [chunk_id, score] * 20
  │    metadata: {dense_hits, sparse_hits, fused_count}
  │    latency: ~50ms
  │
  ├─ Span: "reranking"
  │    input: 20 candidates
  │    output: top 3 with reranker scores
  │    latency: ~150ms
  │
  ├─ Span: "threshold_check"
  │    input: top_1_score
  │    output: {fallback_fired: bool}
  │    latency: <1ms
  │
  └─ Generation: "anthropic_call" (only if fallback not fired)
       model: claude-sonnet-4-6
       input: {system_prompt, context, query}
       output: generated answer
       usage: {input_tokens, output_tokens, total_cost}
       latency: 1-3s
```

## Why this hierarchy

- One trace per query lets us compute end-to-end latency directly.
- Spans expose which stage owns each ms of latency.
- The Generation entity is Langfuse-native and unlocks cost tracking.
- Threshold check is a span even at <1ms because it records the gating decision.
