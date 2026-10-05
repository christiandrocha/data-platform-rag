# Trace hierarchy for data-platform-rag

## Structure per query

Implemented in `observability/tracing.py`, called by `generation/answer.py`
(ADR-021, which supersedes ADR-009's span list).

```
Trace: "query"
  input:  the visitor's question
  output: what the visitor saw (answer, FALLBACK_MESSAGE, or the failed message)
  metadata: {output_class, fallback_fired, failed, system_prompt_version,
             context_format_version, latency_ms}

  ├─ Span: "dense_retrieval"
  │    input: {question, top_k: settings.rerank_top_k}
  │    output: [[chunk_id, dense_distance], ...]
  │
  │    (no intent-classification span: no classifier is built, and retrieval
  │     searches both collections. No reranking span: ADR-005 rejected the
  │     reranker. No threshold span: ADR-019 superseded the score gate.)
  │
  └─ Generation: "anthropic_call" (every query that retrieved something)
       model: as the API reports it (settings.llm_model requested)
       input: the user message (context + question)
       output: the raw output text
       usage_details: {input, output} tokens
       metadata: {stop_reason}
```

A failed query still gets its trace: the span or generation that did not happen
is absent, and `failed: true` is in the trace metadata.

**Never block on Langfuse.** Every `QueryTrace` method catches `Exception`, logs
one warning and returns. On the no-op client (`LANGFUSE_ENABLED=false`) the
same calls run and the trace id is `None`.

**The Postgres twin.** The same query writes one `query_log` row (`sql/04`):
`output_class`, `failed`, `error`, `model`, prompt and context versions, tokens,
`stop_reason`, `corpus_commits` (`project@sha` of the retrieved chunks),
`embedding_model` and `trace_id`, which joins the row to this trace.

## Why this hierarchy

- One trace per query lets us compute end-to-end latency directly.
- Spans expose which stage owns each ms of latency.
- The Generation entity is Langfuse-native and unlocks cost tracking.
- There is no threshold-check span: ADR-019 superseded the score gate, so the
  fallback decision happens inside the Generation (rule 3). The trace's
  `fallback_fired` metadata records it.
