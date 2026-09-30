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
  ├─ Span: "dense_retrieval"
  │    input: {query, collections, top_k}
  │    output: [chunk_id, dense_distance] * 20
  │    metadata: {dense_hits}
  │    latency: ~50ms
  │
  │    (no reranking span: ADR-005 rejected the reranker; the top
  │     settings.rerank_top_k chunks go to the Generation as they are)
  │
  └─ Generation: "anthropic_call" (every query; no score gate since ADR-019)
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
- There is no threshold-check span: ADR-019 superseded the score gate, so the
  fallback decision happens inside the Generation (rule 3). The trace's
  `fallback_fired` metadata records it.
