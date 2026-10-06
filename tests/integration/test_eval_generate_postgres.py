"""Stage 1 against real Postgres: real `answer()`, `origin`, contexts (ADR-008).

Runs on the dedicated `_test` database (conftest). The LLM is a stub and the query
vector hand-chosen, as in `test_answer_postgres.py`, whose seed this reuses. No
key, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_platform_rag.config import get_settings
from data_platform_rag.contracts import GoldenQuestion
from data_platform_rag.evaluation.generate import generate_run, read_provenance
from data_platform_rag.generation.answer import answer
from data_platform_rag.indexer.writer import connect
from data_platform_rag.observability.tracing import QueryTracer
from tests.integration.test_answer_postgres import (
    PROJECT,
    SHA,
    StubClient,
    seed,
    unit,
)

ROOT = Path(__file__).resolve().parents[2]


class MetadataLangfuse:
    """Keeps each trace's final metadata, where `answer()` records the origin."""

    def __init__(self):
        self.metadata: list[dict] = []

    def trace(self, **kwargs):
        langfuse = self

        class Observation:
            id = f"trace-{len(langfuse.metadata)}"

            def span(self, **kw):
                return None

            def generation(self, **kw):
                return None

            def update(self, **kw):
                langfuse.metadata.append(kw.get("metadata", {}))

        return Observation()


@pytest.fixture(autouse=True)
def stub_api_key(monkeypatch: pytest.MonkeyPatch):
    """`answer()` reads `get_settings()`; CI has no `.env` (see PR #35)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seeded(conn, monkeypatch: pytest.MonkeyPatch):
    seed(conn)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE query_log")
    conn.commit()
    monkeypatch.setattr(
        "data_platform_rag.retrieval.pipeline.embed_query", lambda text: tuple(unit(0))
    )
    yield conn
    with conn.cursor() as cur:
        cur.execute("TRUNCATE query_log")
    conn.commit()


def origins(conn) -> list[str]:
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT origin FROM query_log ORDER BY id")
        return [row[0] for row in cur.fetchall()]


def test_stage_1_writes_eval_rows_and_the_chunk_text(seeded, test_dsn, tmp_path):
    questions = [
        GoldenQuestion(id="q1", intent="decision", question="Why A?", expected_answer="A."),
        GoldenQuestion(id="oos1", intent="out-of-scope", question="Salary?", expected_answer=None),
    ]
    langfuse = MetadataLangfuse()

    def traced_answer(question, client, *, connect_fn, origin):
        return answer(
            question, client, connect_fn=connect_fn, tracer=QueryTracer(langfuse), origin=origin
        )

    def connect_fn():
        return connect(test_dsn)

    prov_conn = connect_fn()
    try:
        provenance = read_provenance(
            prov_conn, get_settings(), "a" * 40, False, datetime(2026, 10, 5, tzinfo=UTC)
        )
    finally:
        prov_conn.close()
    run = generate_run(
        questions,
        StubClient("A is chosen [databricks ADR-001]."),
        provenance,
        connect_fn=connect_fn,
        out_path=tmp_path / "eval-run-x.json",
        answer_fn=traced_answer,
    )

    assert origins(seeded) == ["eval", "eval"]
    assert provenance.corpus_commits == [f"{PROJECT}@{SHA}"]
    first = run.records[0]
    with seeded.cursor() as cur:
        cur.execute(
            "SELECT id, content FROM chunks WHERE id = ANY(%s)",
            ([s.chunk_id for s in first.result.sources],),
        )
        content = dict(cur.fetchall())
    assert first.contexts == [content[s.chunk_id] for s in first.result.sources]
    assert first.contexts[0] == "chunk A"  # rank order: unit(0) is A
    assert [m["origin"] for m in langfuse.metadata] == ["eval", "eval"]
    assert [r.result.trace_id for r in run.records] == ["trace-0", "trace-1"]


def test_the_page_path_writes_visitor(seeded, test_dsn):
    answer("Why A?", StubClient("A."), connect_fn=lambda: connect(test_dsn))
    assert origins(seeded) == ["visitor"]


def test_sql_05_applied_twice_keeps_rows_intact(seeded, test_dsn):
    answer("Why A?", StubClient("A."), connect_fn=lambda: connect(test_dsn), origin="eval")
    sql = (ROOT / "sql/05_query_log_origin.sql").read_text()
    with seeded.cursor() as cur:
        cur.execute(sql)
        cur.execute(sql)
    seeded.commit()
    assert origins(seeded) == ["eval"]
