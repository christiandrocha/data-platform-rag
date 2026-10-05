# Langfuse Python SDK — data-platform-rag integration

## Setup

```python
# data_platform_rag/observability/langfuse_client.py
from functools import lru_cache
from langfuse import Langfuse

@lru_cache(maxsize=1)
def get_client() -> Langfuse:
    """Singleton. Returns no-op client if LANGFUSE_ENABLED != 'true'."""
    from data_platform_rag.config import settings
    if not settings.langfuse_enabled:
        return _NoopLangfuse()
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_host,
    )
```

## The pipeline entry point: explicit calls, not the decorator

`generation/answer.py :: answer()` does not use `@observe`. It calls
`observability/tracing.py`, which wraps the 2.x low-level API (`trace`,
`trace.span`, `trace.generation`, `trace.update`, `trace.id`) and catches every
exception in one place (ADR-021). The decorator would put Langfuse inside the
call path, where an SDK error is harder to contain.

```python
trace = (tracer or get_tracer()).start(question)        # never raises
chunks = retrieve(question, top_k=settings.rerank_top_k, conn=conn)
trace.retrieval(question=..., top_k=..., chunks=chunks, start_time=..., end_time=...)
result = generate(question, chunks, client)             # no score gate (ADR-019)
trace.generation(user_message=..., result=result, start_time=..., end_time=...)
output_class = classify_output(result.text)             # ADR-020's four classes
trace.finish(shown_text=..., output_class=..., ...)     # after the query_log row
```

## Flushing before shutdown

Streamlit reruns often — SDK batches by default. On graceful shutdown call
`langfuse.flush()` to ensure last batch is sent.

## Failure isolation

Wrap Langfuse calls in try/except. If Langfuse is down, log locally and
continue serving queries. Observability is nice-to-have; UX is non-negotiable.
