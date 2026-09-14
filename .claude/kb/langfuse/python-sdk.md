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

## Decorator on the pipeline entry point

```python
from langfuse.decorators import observe

@observe(name="query")
async def answer_query(query: str, session_id: str | None = None) -> AnswerResult:
    intent = await classify_intent(query)
    candidates = await hybrid_search(query, intent.collections)
    top5 = await rerank(query, candidates)
    if top5[0].score < settings.fallback_threshold:
        return AnswerResult(text=FALLBACK_MESSAGE, fallback=True, ...)
    answer = await generate(query, top5)  # @observe(as_type="generation")
    return AnswerResult(...)
```

## Flushing before shutdown

Streamlit reruns often — SDK batches by default. On graceful shutdown call
`langfuse.flush()` to ensure last batch is sent.

## Failure isolation

Wrap Langfuse calls in try/except. If Langfuse is down, log locally and
continue serving queries. Observability is nice-to-have; UX is non-negotiable.
