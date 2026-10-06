"""The product query path: a visitor's question in, what they see out (ADR-021).

`answer()` retrieves once, generates under `SYSTEM_PROMPT`, classifies the text
with ADR-020's `classify_output()`, writes one `query_log` row and emits one
Langfuse trace. Retrieval, prompt, context format and model are exactly the ones
ADR-020 measures: this module changes none of them, it records them.

**What the visitor sees follows the class** (DEFINE Q2): an answer with its
sources; `FALLBACK_MESSAGE` for `fallback` and for `empty`; the model's own text
for `non_compliant_refusal`, which carries the LinkedIn link.

**A failure is not a fallback** (DEFINE Q3). If retrieval or the call raises, the
visitor gets `FAILED_MESSAGE`, the row records `failed`, and nothing claims the
question was out of scope.

**Recording never fails the answer.** The tracer swallows its own errors
(`observability/tracing.py`), and a failed `query_log` insert is logged and
reported as `logged=False` (DESIGN D6).

The client is injected, as in `generation/client.py`, so every test runs on a
stub and nothing here imports the SDK.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING

from data_platform_rag.config import get_settings
from data_platform_rag.contracts import (
    AnswerResult,
    GenerationResult,
    Origin,
    OutputClass,
    RetrievedChunk,
    RetrievedSource,
)
from data_platform_rag.generation.client import LLMClient, build_user_message, generate
from data_platform_rag.generation.fallback import classify_output
from data_platform_rag.generation.prompt import (
    CONTEXT_FORMAT_VERSION,
    FALLBACK_MESSAGE,
    SYSTEM_PROMPT_VERSION,
)
from data_platform_rag.observability.tracing import QueryTrace, QueryTracer, get_tracer

if TYPE_CHECKING:  # pragma: no cover - typing only
    import psycopg

logger = logging.getLogger(__name__)

FAILED_MESSAGE = "Sorry, I could not answer right now. Please try again in a moment."

# Bounds what one failure writes into `query_log.error`.
ERROR_MAX_CHARS = 500

ConnectFn = Callable[[], "psycopg.Connection"]

# `corpus_commits` and `embedding_model` come from the chunks that were retrieved,
# inside the insert, so they record what answered rather than what settings say
# should be indexed. `project@sha` survives a reindex; a snapshot id would not
# (ADR-021). With no chunks, both subqueries return NULL.
_INSERT_QUERY_LOG = """
    INSERT INTO query_log (
        query_text, retrieved_ids, retrieved_scores, fallback_fired, answer_length,
        latency_ms, output_class, failed, error, model, system_prompt_version,
        context_format_version, input_tokens, output_tokens, stop_reason,
        corpus_commits, embedding_model, trace_id, origin
    )
    VALUES (
        %(query_text)s, %(retrieved_ids)s::bigint[], %(retrieved_scores)s::real[],
        %(fallback_fired)s, %(answer_length)s, %(latency_ms)s, %(output_class)s,
        %(failed)s, %(error)s, %(model)s, %(system_prompt_version)s,
        %(context_format_version)s, %(input_tokens)s, %(output_tokens)s, %(stop_reason)s,
        (SELECT array_agg(DISTINCT s.source_project || '@' || s.commit_sha
                          ORDER BY s.source_project || '@' || s.commit_sha)
           FROM chunks c JOIN corpus_snapshot s ON s.id = c.snapshot_id
          WHERE c.id = ANY(%(retrieved_ids)s::bigint[])),
        (SELECT min(s.embedding_model)
           FROM chunks c JOIN corpus_snapshot s ON s.id = c.snapshot_id
          WHERE c.id = ANY(%(retrieved_ids)s::bigint[])),
        %(trace_id)s, %(origin)s
    )
"""


def shown_text_for(output_class: OutputClass, text: str) -> str:
    """What the page displays for one classified output (DEFINE Q2)."""
    if output_class in ("fallback", "empty"):
        return FALLBACK_MESSAGE
    # An answer, or a refusal worded by the model: it already carries the link.
    return text


def validate_question(question: str, max_chars: int) -> None:
    """Reject a question no query should run for. Raises ValueError.

    Checked before anything runs, so a rejected question writes no row: no query
    happened (DESIGN D5).
    """
    if not question or not question.strip():
        raise ValueError("question must be a non-empty string")
    if len(question) > max_chars:
        raise ValueError(f"question is {len(question)} characters; the limit is {max_chars}")


def answer(
    question: str,
    client: LLMClient,
    *,
    connect_fn: ConnectFn | None = None,
    tracer: QueryTracer | None = None,
    origin: Origin = "visitor",
) -> AnswerResult:
    """Answer one visitor question, and record it once in Postgres and Langfuse.

    Raises only ValueError, for a question `validate_question` rejects. Every
    other failure becomes `failed=True` with `FAILED_MESSAGE`.

    `origin` marks who asked, in the row and the trace: the page leaves it at
    `"visitor"`, and `make eval` stage 1 passes `"eval"` (ADR-008).
    """
    settings = get_settings()
    validate_question(question, settings.max_question_chars)

    if connect_fn is None:
        from data_platform_rag.indexer.writer import connect

        def connect_fn() -> psycopg.Connection:
            return connect(str(settings.database_url))

    trace = (tracer or get_tracer()).start(question)
    started = perf_counter()

    conn: psycopg.Connection | None = None
    chunks: list[RetrievedChunk] = []
    generation: GenerationResult | None = None
    output_class: OutputClass | None = None
    error: str | None = None
    try:
        conn = connect_fn()
        chunks = _retrieve(question, settings.rerank_top_k, conn, trace)
        generation = _generate(question, chunks, client, trace)
        output_class = classify_output(generation.text)
    except Exception as exc:  # noqa: BLE001 - every failure reaches the visitor as one message
        error = f"{type(exc).__name__}: {exc}"[:ERROR_MAX_CHARS]
        logger.warning("query failed: %s", error)

    failed = error is not None
    if failed or output_class is None or generation is None:
        shown_text = FAILED_MESSAGE
    else:
        shown_text = shown_text_for(output_class, generation.text)
    latency_ms = int((perf_counter() - started) * 1000)

    unlogged = AnswerResult(
        question=question,
        failed=failed,
        output_class=None if failed else output_class,
        shown_text=shown_text,
        sources=[RetrievedSource.from_chunk(c) for c in chunks],
        generation=generation,
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        context_format_version=CONTEXT_FORMAT_VERSION,
        latency_ms=latency_ms,
        trace_id=trace.id,
        logged=False,
    )
    try:
        logged = _log_query(conn, connect_fn, unlogged, error, origin)
    finally:
        _close(conn)
    result = unlogged.model_copy(update={"logged": logged})

    trace.finish(
        shown_text=result.shown_text,
        output_class=result.output_class,
        fallback_fired=result.fallback_fired,
        failed=result.failed,
        system_prompt_version=result.system_prompt_version,
        context_format_version=result.context_format_version,
        latency_ms=result.latency_ms,
        origin=origin,
    )
    return result


def _now() -> datetime:
    return datetime.now(UTC)


def _retrieve(
    question: str, top_k: int, conn: psycopg.Connection, trace: QueryTrace
) -> list[RetrievedChunk]:
    from data_platform_rag.retrieval.pipeline import retrieve

    start = _now()
    chunks = retrieve(question, top_k=top_k, conn=conn)
    trace.retrieval(
        question=question, top_k=top_k, chunks=chunks, start_time=start, end_time=_now()
    )
    return chunks


def _generate(
    question: str, chunks: list[RetrievedChunk], client: LLMClient, trace: QueryTrace
) -> GenerationResult:
    start = _now()
    result = generate(question, chunks, client)
    # Built again only for the trace; `generate` builds the same message for the
    # call. Done after the call, so a trace error cannot precede it.
    trace.generation(
        user_message=build_user_message(question, chunks),
        result=result,
        start_time=start,
        end_time=_now(),
    )
    return result


def _log_query(
    conn: psycopg.Connection | None,
    connect_fn: ConnectFn,
    result: AnswerResult,
    error: str | None,
    origin: Origin,
) -> bool:
    """Write the query's one `query_log` row. Never raises (DESIGN D6)."""
    generation = result.generation
    params = {
        "query_text": result.question,
        "retrieved_ids": [s.chunk_id for s in result.sources] or None,
        "retrieved_scores": [s.dense_distance for s in result.sources] or None,
        "fallback_fired": result.fallback_fired,
        "answer_length": len(result.shown_text) if result.output_class == "answer" else 0,
        "latency_ms": result.latency_ms,
        "output_class": result.output_class,
        "failed": result.failed,
        "error": error,
        "model": generation.model if generation else None,
        "system_prompt_version": result.system_prompt_version,
        "context_format_version": result.context_format_version,
        "input_tokens": generation.input_tokens if generation else None,
        "output_tokens": generation.output_tokens if generation else None,
        "stop_reason": generation.stop_reason if generation else None,
        "trace_id": result.trace_id,
        "origin": origin,
    }
    opened: psycopg.Connection | None = None
    try:
        if conn is None:
            # Retrieval never got a connection. One more attempt, for the row.
            conn = opened = connect_fn()
        # A failure inside retrieval can leave the transaction aborted.
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(_INSERT_QUERY_LOG, params)
        conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - logging never fails the answer
        logger.warning("query_log insert failed: %s", exc)
        return False
    finally:
        _close(opened)


def _close(conn: psycopg.Connection | None) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception as exc:  # noqa: BLE001 - closing is best effort
        logger.warning("closing the connection failed: %s", exc)
