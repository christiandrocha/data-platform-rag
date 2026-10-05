"""generation.answer with stubs: no key, no API, no database (ADR-021).

Retrieval is replaced by a function returning hand-built chunks, the connection by
a recorder, the client by a stub, and the tracer by a recording fake. The
database half of the path is covered in tests/integration/test_answer_postgres.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from data_platform_rag.config import Settings, get_settings
from data_platform_rag.contracts import (
    AnswerResult,
    ChunkMetadata,
    RetrievedChunk,
    RetrievedSource,
)
from data_platform_rag.generation import answer as answer_module
from data_platform_rag.generation.answer import (
    FAILED_MESSAGE,
    answer,
    shown_text_for,
)
from data_platform_rag.generation.prompt import (
    CONTEXT_FORMAT_VERSION,
    FALLBACK_MESSAGE,
    SYSTEM_PROMPT_VERSION,
)
from data_platform_rag.observability.tracing import QueryTracer

REFUSAL = "I can't answer that. See https://www.linkedin.com/in/christiandrocha/"


def chunk(rank: int, *, adr_id: str | None = "ADR-007") -> RetrievedChunk:
    return RetrievedChunk(
        id=100 + rank,
        content=f"content {rank}",
        metadata=ChunkMetadata(
            source_project="sdd-kafka-databricks",
            source_type="adr",
            source_path=f"docs/adr/ADR-00{rank}.md",
            source_anchor="Decision",
            adr_id=adr_id,
            chunk_index=0,
            token_count=10,
        ),
        dense_distance=0.1 * rank,
        dense_rank=rank,
    )


CHUNKS = [chunk(1), chunk(2), chunk(3, adr_id=None)]


class StubClient:
    def __init__(self, text: str = "An answer [databricks ADR-007].", raises=None):
        self.text = text
        self.raises = raises
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)],
            model="claude-sonnet-4-6",
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1234, output_tokens=56),
        )


class RecordingConn:
    """Stands in for a psycopg connection. Records what the insert sent."""

    def __init__(self, fail_insert: bool = False):
        self.fail_insert = fail_insert
        self.inserts: list[dict] = []
        self.commits = 0
        self.closed = False

    def rollback(self):
        return None

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True

    def cursor(self):
        conn = self

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params):
                if conn.fail_insert:
                    raise RuntimeError("insert refused")
                conn.inserts.append(params)

        return _Cursor()


class RecordingObservation:
    id = "trace-123"

    def __init__(self):
        self.spans: list[dict] = []
        self.generations: list[dict] = []
        self.updates: list[dict] = []

    def span(self, **kwargs):
        self.spans.append(kwargs)

    def generation(self, **kwargs):
        self.generations.append(kwargs)

    def update(self, **kwargs):
        self.updates.append(kwargs)


class RecordingLangfuse:
    def __init__(self):
        self.traces: list[RecordingObservation] = []

    def trace(self, **kwargs):
        observation = RecordingObservation()
        observation.start_kwargs = kwargs
        self.traces.append(observation)
        return observation


class RaisingLangfuse:
    def trace(self, **kwargs):
        raise ConnectionError("langfuse is down")


@pytest.fixture
def retrieved(monkeypatch: pytest.MonkeyPatch) -> list:
    """Replace retrieval with the hand-built chunks; record each call."""
    calls: list = []

    def fake_retrieve(question, top_k=None, conn=None):
        calls.append((question, top_k, conn))
        return list(CHUNKS)

    monkeypatch.setattr("data_platform_rag.retrieval.pipeline.retrieve", fake_retrieve)
    return calls


def run(client, *, conn=None, langfuse=None):
    conn = conn if conn is not None else RecordingConn()
    langfuse = langfuse if langfuse is not None else RecordingLangfuse()
    result = answer(
        "Why Lakeflow?", client, connect_fn=lambda: conn, tracer=QueryTracer(langfuse)
    )
    return result, conn, langfuse


# ─── The display per class (DEFINE Q2) ───────────────────────────────────────


@pytest.mark.parametrize(
    ("output_class", "text", "shown"),
    [
        ("answer", "An answer.", "An answer."),
        ("fallback", f"  {FALLBACK_MESSAGE}\n", FALLBACK_MESSAGE),
        ("empty", "   ", FALLBACK_MESSAGE),
        ("non_compliant_refusal", REFUSAL, REFUSAL),
    ],
)
def test_shown_text_follows_the_class(output_class, text, shown) -> None:
    assert shown_text_for(output_class, text) == shown


@pytest.mark.parametrize(
    ("output_class", "failed", "fired"),
    [
        ("answer", False, False),
        ("fallback", False, True),
        ("non_compliant_refusal", False, True),
        ("empty", False, True),
        (None, True, False),
    ],
)
def test_fallback_fired_is_derived_from_the_class(output_class, failed, fired) -> None:
    result = AnswerResult(
        question="q",
        failed=failed,
        output_class=output_class,
        shown_text="x",
        sources=[],
        generation=None,
        system_prompt_version="v",
        context_format_version="v",
        latency_ms=0,
        logged=True,
    )
    assert result.fallback_fired is fired


def test_retrieved_source_carries_the_citation_fields() -> None:
    source = RetrievedSource.from_chunk(chunk(2))
    assert source.chunk_id == 102
    assert source.source_path == "docs/adr/ADR-002.md"
    assert source.adr_id == "ADR-007"
    assert source.dense_distance == pytest.approx(0.2)


# ─── Rejected questions run nothing (DESIGN D5) ──────────────────────────────


@pytest.mark.parametrize("question", ["", "   "])
def test_an_empty_question_is_rejected_before_anything_runs(question) -> None:
    def must_not_connect():
        raise AssertionError("connect_fn was called")

    client = StubClient()
    with pytest.raises(ValueError, match="non-empty"):
        answer(question, client, connect_fn=must_not_connect, tracer=QueryTracer(RaisingLangfuse()))
    assert client.calls == 0


def test_an_over_cap_question_is_rejected_before_anything_runs() -> None:
    cap = get_settings().max_question_chars

    def must_not_connect():
        raise AssertionError("connect_fn was called")

    client = StubClient()
    with pytest.raises(ValueError, match="limit"):
        answer("x" * (cap + 1), client, connect_fn=must_not_connect)
    assert client.calls == 0


def test_a_cap_below_the_longest_evaluated_question_is_a_startup_error() -> None:
    with pytest.raises(ValidationError):
        Settings(max_question_chars=215)
    assert Settings(max_question_chars=216).max_question_chars == 216


# ─── The path, per class ─────────────────────────────────────────────────────


def test_an_answer_is_shown_with_its_sources_and_recorded_once(retrieved) -> None:
    result, conn, langfuse = run(StubClient("An answer [databricks ADR-007]."))

    assert result.output_class == "answer"
    assert result.failed is False
    assert result.shown_text == "An answer [databricks ADR-007]."
    assert [s.chunk_id for s in result.sources] == [101, 102, 103]
    assert result.system_prompt_version == SYSTEM_PROMPT_VERSION
    assert result.context_format_version == CONTEXT_FORMAT_VERSION
    assert result.trace_id == "trace-123"
    assert result.logged is True
    assert retrieved == [("Why Lakeflow?", get_settings().rerank_top_k, conn)]

    assert len(conn.inserts) == 1
    row = conn.inserts[0]
    assert row["retrieved_ids"] == [101, 102, 103]
    assert row["retrieved_scores"] == pytest.approx([0.1, 0.2, 0.3])
    assert row["output_class"] == "answer"
    assert row["fallback_fired"] is False
    assert row["answer_length"] == len(result.shown_text)
    assert row["input_tokens"] == 1234
    assert row["output_tokens"] == 56
    assert row["model"] == "claude-sonnet-4-6"
    assert row["stop_reason"] == "end_turn"
    assert row["trace_id"] == "trace-123"
    assert row["failed"] is False and row["error"] is None
    assert conn.closed is True


def test_the_trace_has_one_retrieval_span_and_one_generation(retrieved) -> None:
    result, _, langfuse = run(StubClient())

    assert len(langfuse.traces) == 1
    trace = langfuse.traces[0]
    assert trace.start_kwargs == {"name": "query", "input": "Why Lakeflow?"}
    assert [s["name"] for s in trace.spans] == ["dense_retrieval"]
    output = trace.spans[0]["output"]
    assert [pair[0] for pair in output] == [101, 102, 103]
    assert [pair[1] for pair in output] == pytest.approx([0.1, 0.2, 0.3])
    assert [g["name"] for g in trace.generations] == ["anthropic_call"]
    assert trace.generations[0]["usage_details"] == {"input": 1234, "output": 56}
    assert trace.generations[0]["model"] == "claude-sonnet-4-6"
    assert len(trace.updates) == 1
    assert trace.updates[0]["output"] == result.shown_text
    assert trace.updates[0]["metadata"]["output_class"] == "answer"


@pytest.mark.parametrize(
    ("text", "output_class", "shown"),
    [
        (f"\n{FALLBACK_MESSAGE}  ", "fallback", FALLBACK_MESSAGE),
        ("", "empty", FALLBACK_MESSAGE),
        (REFUSAL, "non_compliant_refusal", REFUSAL),
    ],
)
def test_no_answer_classes_fire_the_fallback_flag(retrieved, text, output_class, shown) -> None:
    result, conn, _ = run(StubClient(text))

    assert result.output_class == output_class
    assert result.shown_text == shown
    assert result.fallback_fired is True
    row = conn.inserts[0]
    assert row["fallback_fired"] is True
    assert row["output_class"] == output_class
    assert row["answer_length"] == 0


# ─── Failures (DEFINE Q3, DESIGN D6) ─────────────────────────────────────────


def test_a_failed_call_shows_the_failed_message_never_the_fallback(retrieved) -> None:
    result, conn, _ = run(StubClient(raises=TimeoutError("read timed out")))

    assert result.failed is True
    assert result.output_class is None
    assert result.shown_text == FAILED_MESSAGE
    assert result.shown_text != FALLBACK_MESSAGE
    assert result.fallback_fired is False
    assert result.generation is None
    # Retrieval ran, so the row records what the context would have been.
    assert [s.chunk_id for s in result.sources] == [101, 102, 103]
    row = conn.inserts[0]
    assert row["failed"] is True
    assert row["error"] == "TimeoutError: read timed out"
    assert row["output_class"] is None
    assert row["model"] is None


def test_a_failed_retrieval_records_a_row_without_chunks(monkeypatch) -> None:
    def broken_retrieve(question, top_k=None, conn=None):
        raise RuntimeError("relation chunks does not exist")

    monkeypatch.setattr("data_platform_rag.retrieval.pipeline.retrieve", broken_retrieve)
    client = StubClient()
    result, conn, _ = run(client)

    assert result.failed is True
    assert result.sources == []
    assert client.calls == 0
    row = conn.inserts[0]
    assert row["retrieved_ids"] is None
    assert row["error"].startswith("RuntimeError")


def test_the_error_text_is_bounded(retrieved) -> None:
    result, conn, _ = run(StubClient(raises=RuntimeError("x" * 2000)))
    assert len(conn.inserts[0]["error"]) == answer_module.ERROR_MAX_CHARS


def test_a_failed_connection_still_tries_once_more_for_the_row(retrieved) -> None:
    conn = RecordingConn()
    attempts = []

    def flaky_connect():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("connection refused")
        return conn

    result = answer(
        "Why Lakeflow?",
        StubClient(),
        connect_fn=flaky_connect,
        tracer=QueryTracer(RecordingLangfuse()),
    )
    assert result.failed is True
    assert result.logged is True
    assert len(attempts) == 2
    assert len(conn.inserts) == 1
    assert conn.closed is True


def test_a_failed_insert_does_not_fail_the_answer(retrieved) -> None:
    result, conn, _ = run(StubClient(), conn=RecordingConn(fail_insert=True))

    assert result.output_class == "answer"
    assert result.shown_text == "An answer [databricks ADR-007]."
    assert result.logged is False
    assert conn.closed is True


def test_langfuse_down_changes_nothing_the_visitor_or_the_row_sees(retrieved) -> None:
    healthy, healthy_conn, _ = run(StubClient())
    down, down_conn, _ = run(StubClient(), langfuse=RaisingLangfuse())

    assert down.shown_text == healthy.shown_text
    assert down.output_class == healthy.output_class
    assert down.logged is True
    assert down.trace_id is None
    varying = ("trace_id", "latency_ms")
    expected = {k: v for k, v in healthy_conn.inserts[0].items() if k not in varying}
    actual = {k: v for k, v in down_conn.inserts[0].items() if k not in varying}
    assert actual == expected
