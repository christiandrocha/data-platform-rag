"""observability.tracing: never block on Langfuse (ADR-021). No network."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from data_platform_rag.contracts import GenerationResult
from data_platform_rag.observability.langfuse_client import NoopLangfuse
from data_platform_rag.observability.tracing import QueryTrace, QueryTracer, get_tracer

NOW = datetime(2026, 10, 5, tzinfo=UTC)
RESULT = GenerationResult(
    text="t", model="claude-sonnet-4-6", stop_reason="end_turn", input_tokens=1, output_tokens=2
)


class RaisingObservation:
    @property
    def id(self):
        raise RuntimeError("no id")

    def span(self, **kwargs):
        raise RuntimeError("span down")

    def generation(self, **kwargs):
        raise RuntimeError("generation down")

    def update(self, **kwargs):
        raise RuntimeError("update down")


def call_everything(trace: QueryTrace) -> None:
    trace.retrieval(question="q", top_k=3, chunks=[], start_time=NOW, end_time=NOW)
    trace.generation(user_message="m", result=RESULT, start_time=NOW, end_time=NOW)
    trace.finish(
        shown_text="s",
        output_class="answer",
        fallback_fired=False,
        failed=False,
        system_prompt_version="v",
        context_format_version="v",
        latency_ms=1,
    )


def test_every_method_swallows_a_raising_client_and_warns_once(caplog) -> None:
    trace = QueryTrace(RaisingObservation())
    with caplog.at_level(logging.WARNING):
        call_everything(trace)
        assert trace.id is None
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 3


def test_a_trace_that_cannot_start_is_a_silent_trace(caplog) -> None:
    class Down:
        def trace(self, **kwargs):
            raise ConnectionError("down")

    with caplog.at_level(logging.WARNING):
        trace = QueryTracer(Down()).start("q")
        call_everything(trace)
    assert trace.id is None
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_the_noop_client_runs_the_whole_shape_without_warnings(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        trace = QueryTracer(NoopLangfuse()).start("q")
        call_everything(trace)
    assert trace.id is None
    assert caplog.records == []


def test_a_disabled_langfuse_gives_the_noop_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    from data_platform_rag.observability import langfuse_client

    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    langfuse_client.get_client.cache_clear()
    try:
        trace = get_tracer().start("q")
        assert trace.id is None
    finally:
        langfuse_client.get_client.cache_clear()
