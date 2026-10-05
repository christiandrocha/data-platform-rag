"""The product path against real Postgres: one `query_log` row per query (ADR-021).

Runs on the dedicated `_test` database (conftest), never the configured one. The
embedding model is not loaded: `embed_query` returns a hand-chosen vector, so
retrieval runs its real SQL over hand-placed chunks. The LLM is a stub and the
tracer a recording fake. No key, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from data_platform_rag.config import get_settings
from data_platform_rag.contracts import Chunk, ChunkMetadata, IndexedSnapshot
from data_platform_rag.generation.answer import FAILED_MESSAGE, answer
from data_platform_rag.generation.prompt import FALLBACK_MESSAGE, SYSTEM_PROMPT_VERSION
from data_platform_rag.indexer.writer import connect, write_project
from data_platform_rag.observability.tracing import QueryTracer

DIM = 384
PROJECT = "sdd-kafka-databricks"
SHA = "f" * 40
REFUSAL = "Not covered. See https://www.linkedin.com/in/christiandrocha/"
ROOT = Path(__file__).resolve().parents[2]


def unit(index: int) -> list[float]:
    vector = [0.0] * DIM
    vector[index] = 1.0
    return vector


def seed(conn) -> None:
    chunks = [
        Chunk(
            content=f"chunk {name}",
            collection="decisions",
            metadata=ChunkMetadata(
                source_project=PROJECT,
                source_type="adr",
                source_path=f"docs/adr/{name}.md",
                source_anchor="Decision",
                adr_id="ADR-001",
                chunk_index=index,
                token_count=2,
            ),
        )
        for index, name in enumerate(["A", "B", "C", "D"])
    ]
    snapshot = IndexedSnapshot(
        source_project=PROJECT,
        repo_url=f"https://github.com/christiandrocha/{PROJECT}",
        commit_sha=SHA,
        file_count=4,
        manifest_created_at=datetime(2026, 10, 5, tzinfo=UTC),
        manifest_schema_version=1,
        embedding_model="fixture/hand-chosen",
        embedding_dim=DIM,
        chunk_count=4,
    )
    write_project(conn, snapshot, chunks, [unit(i) for i in range(4)])
    conn.commit()


class StubClient:
    def __init__(self, text: str = "", raises: Exception | None = None):
        self.text, self.raises, self.messages = text, raises, self

    def create(self, **kwargs):
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)],
            model="claude-sonnet-4-6",
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=900, output_tokens=40),
        )


class RecordingLangfuse:
    def __init__(self):
        self.traces = []

    def trace(self, **kwargs):
        observation = SimpleNamespace(id=f"trace-{len(self.traces)}", spans=[], generations=[])
        observation.span = lambda **kw: observation.spans.append(kw)
        observation.generation = lambda **kw: observation.generations.append(kw)
        observation.update = lambda **kw: None
        self.traces.append(observation)
        return observation


@pytest.fixture
def product(conn, test_dsn, monkeypatch: pytest.MonkeyPatch):
    """A seeded index, an empty query_log, and a hand-chosen query vector."""
    seed(conn)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE query_log")
    conn.commit()
    monkeypatch.setattr(
        "data_platform_rag.retrieval.pipeline.embed_query", lambda text: tuple(unit(0))
    )
    langfuse = RecordingLangfuse()

    def ask(client):
        return answer(
            "Why A?",
            client,
            connect_fn=lambda: connect(test_dsn),
            tracer=QueryTracer(langfuse),
        )

    yield ask, langfuse
    with conn.cursor() as cur:
        cur.execute("TRUNCATE query_log")
    conn.commit()


def rows(conn) -> list[dict]:
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT query_text, retrieved_ids, retrieved_scores, fallback_fired,
                      answer_length, output_class, failed, error, model,
                      system_prompt_version, input_tokens, output_tokens, stop_reason,
                      corpus_commits, embedding_model, trace_id, intent, reranker_top_score
               FROM query_log ORDER BY id"""
        )
        names = [d.name for d in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


@pytest.mark.parametrize(
    ("text", "output_class", "fired"),
    [
        ("A is chosen [databricks ADR-001].", "answer", False),
        (FALLBACK_MESSAGE, "fallback", True),
        (REFUSAL, "non_compliant_refusal", True),
        ("", "empty", True),
    ],
)
def test_each_class_writes_exactly_one_matching_row(conn, product, text, output_class, fired):
    ask, langfuse = product
    result = ask(StubClient(text))

    logged = rows(conn)
    assert len(logged) == 1
    row = logged[0]
    assert result.logged is True
    assert row["query_text"] == "Why A?"
    assert row["output_class"] == output_class
    assert row["fallback_fired"] is fired
    assert row["failed"] is False
    assert row["answer_length"] == (len(result.shown_text) if output_class == "answer" else 0)
    assert row["retrieved_ids"] == [s.chunk_id for s in result.sources]
    assert row["retrieved_scores"][0] == pytest.approx(0.0, abs=1e-6)
    assert row["model"] == "claude-sonnet-4-6"
    assert row["system_prompt_version"] == SYSTEM_PROMPT_VERSION
    assert (row["input_tokens"], row["output_tokens"]) == (900, 40)
    assert row["stop_reason"] == "end_turn"
    assert row["corpus_commits"] == [f"{PROJECT}@{SHA}"]
    assert row["embedding_model"] == "fixture/hand-chosen"
    assert row["trace_id"] == result.trace_id == "trace-0"
    assert row["intent"] is None and row["reranker_top_score"] is None

    assert len(langfuse.traces) == 1
    assert len(langfuse.traces[0].spans) == 1
    assert len(langfuse.traces[0].generations) == 1


def test_the_context_is_the_top_rerank_top_k_in_rank_order(conn, product):
    ask, _ = product
    result = ask(StubClient("x"))
    # Query vector = e0: A at distance 0, B, C, D at distance 1, tie broken by id.
    assert [s.source_path for s in result.sources][0] == "docs/adr/A.md"
    # 4 chunks are indexed, so the cap is visible only when rerank_top_k < 4.
    assert len(result.sources) == min(get_settings().rerank_top_k, 4)


def test_a_failed_call_writes_one_failed_row(conn, product):
    ask, _ = product
    result = ask(StubClient(raises=TimeoutError("read timed out")))

    assert result.shown_text == FAILED_MESSAGE != FALLBACK_MESSAGE
    (row,) = rows(conn)
    assert row["failed"] is True
    assert row["output_class"] is None
    assert row["fallback_fired"] is False
    assert row["error"] == "TimeoutError: read timed out"
    assert row["model"] is None
    # Retrieval ran, so the chunks and their provenance are still recorded.
    assert row["corpus_commits"] == [f"{PROJECT}@{SHA}"]


def test_a_failed_retrieval_writes_one_row_without_chunks(conn, product, monkeypatch):
    ask, _ = product

    def broken(text):
        raise RuntimeError("embedding model unavailable")

    monkeypatch.setattr("data_platform_rag.retrieval.pipeline.embed_query", broken)
    result = ask(StubClient("never called"))

    assert result.failed is True
    (row,) = rows(conn)
    assert row["failed"] is True
    assert row["retrieved_ids"] is None
    assert row["corpus_commits"] is None
    assert row["embedding_model"] is None


def test_langfuse_down_still_writes_the_row(conn, test_dsn, product):
    class Down:
        def trace(self, **kwargs):
            raise ConnectionError("langfuse is down")

    result = answer(
        "Why A?",
        StubClient("A is chosen."),
        connect_fn=lambda: connect(test_dsn),
        tracer=QueryTracer(Down()),
    )
    assert result.shown_text == "A is chosen."
    (row,) = rows(conn)
    assert row["output_class"] == "answer"
    assert row["trace_id"] is None


def test_sql_04_is_idempotent_on_a_populated_query_log(conn, product):
    ask, _ = product
    ask(StubClient("A is chosen."))
    before = rows(conn)

    with conn.cursor() as cur:
        cur.execute((ROOT / "sql/04_query_log_product.sql").read_text())
        cur.execute((ROOT / "sql/04_query_log_product.sql").read_text())
    conn.commit()

    assert rows(conn) == before
