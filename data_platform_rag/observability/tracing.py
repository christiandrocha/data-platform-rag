"""One Langfuse trace per product query, that can never break the query (ADR-021).

AGENTS.md: "Never block the query pipeline on Langfuse. Fire-and-forget; log
failures locally and continue." That rule lives here, once. Every method catches
`Exception`, logs one warning and returns, so `generation/answer.py` calls the
tracer without a guard of its own and a missed guard cannot exist.

The trace shape is ADR-021's, which supersedes ADR-009's span list:

    trace "query"                 input question, output what the visitor saw
      span "dense_retrieval"      input question and top_k, output [chunk_id, distance]
      generation "anthropic_call" model, user message, output text, token usage

Written against the Langfuse 2.x SDK (`trace`, `span`, `generation`,
`update`, `id`), pinned in `pyproject.toml`. The no-op client answers the same
calls and has `id = None`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol

from data_platform_rag.contracts import GenerationResult, OutputClass, RetrievedChunk

logger = logging.getLogger(__name__)


class _Observation(Protocol):
    id: str | None

    def span(self, **kwargs: object) -> object: ...

    def generation(self, **kwargs: object) -> object: ...

    def update(self, **kwargs: object) -> object: ...


class _LangfuseLike(Protocol):
    def trace(self, **kwargs: object) -> _Observation: ...


class QueryTrace:
    """One query's trace. Every method is safe to call in any state."""

    def __init__(self, observation: _Observation | None) -> None:
        self._observation = observation

    @property
    def id(self) -> str | None:
        """The trace id, or None on the no-op client or after a failed start."""
        try:
            value = getattr(self._observation, "id", None)
        except Exception:  # noqa: BLE001 - a property of a third-party object
            return None
        return value if isinstance(value, str) else None

    def retrieval(
        self,
        *,
        question: str,
        top_k: int,
        chunks: list[RetrievedChunk],
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        if self._observation is None:
            return
        try:
            self._observation.span(
                name="dense_retrieval",
                input={"question": question, "top_k": top_k},
                output=[[c.id, c.dense_distance] for c in chunks],
                start_time=start_time,
                end_time=end_time,
            )
        except Exception as exc:  # noqa: BLE001 - never block on Langfuse
            logger.warning("langfuse retrieval span failed: %s", exc)

    def generation(
        self,
        *,
        user_message: str,
        result: GenerationResult,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        if self._observation is None:
            return
        try:
            self._observation.generation(
                name="anthropic_call",
                model=result.model,
                input=user_message,
                output=result.text,
                usage_details={"input": result.input_tokens, "output": result.output_tokens},
                metadata={"stop_reason": result.stop_reason},
                start_time=start_time,
                end_time=end_time,
            )
        except Exception as exc:  # noqa: BLE001 - never block on Langfuse
            logger.warning("langfuse generation failed: %s", exc)

    def finish(
        self,
        *,
        shown_text: str,
        output_class: OutputClass | None,
        fallback_fired: bool,
        failed: bool,
        system_prompt_version: str,
        context_format_version: str,
        latency_ms: int,
        origin: str = "visitor",
    ) -> None:
        if self._observation is None:
            return
        try:
            self._observation.update(
                output=shown_text,
                metadata={
                    "output_class": output_class,
                    "fallback_fired": fallback_fired,
                    "failed": failed,
                    "system_prompt_version": system_prompt_version,
                    "context_format_version": context_format_version,
                    "latency_ms": latency_ms,
                    "origin": origin,
                },
            )
        except Exception as exc:  # noqa: BLE001 - never block on Langfuse
            logger.warning("langfuse trace update failed: %s", exc)


class QueryTracer:
    """Starts query traces on a Langfuse client, or on the no-op one."""

    def __init__(self, client: _LangfuseLike) -> None:
        self._client = client

    def start(self, question: str) -> QueryTrace:
        try:
            return QueryTrace(self._client.trace(name="query", input=question))
        except Exception as exc:  # noqa: BLE001 - never block on Langfuse
            logger.warning("langfuse trace start failed: %s", exc)
            return QueryTrace(None)


def get_tracer() -> QueryTracer:
    """The tracer over the process's Langfuse singleton (no-op when disabled)."""
    from data_platform_rag.observability.langfuse_client import NoopLangfuse, get_client

    try:
        return QueryTracer(get_client())
    except Exception as exc:  # noqa: BLE001 - a bad Langfuse config never blocks a query
        logger.warning("langfuse client unavailable, tracing disabled: %s", exc)
        return QueryTracer(NoopLangfuse())
