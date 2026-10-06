"""Stage 1, the golden-set loader and the CLI's refusals (ADR-008). No API, no network."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from data_platform_rag.config import get_settings
from data_platform_rag.contracts import (
    AnswerResult,
    EvalRun,
    GoldenQuestion,
    RetrievedSource,
)
from data_platform_rag.evaluation import generate as gen
from data_platform_rag.evaluation import golden_set_loader
from data_platform_rag.generation.answer import FAILED_MESSAGE
from data_platform_rag.generation.prompt import CONTEXT_FORMAT_VERSION, SYSTEM_PROMPT_VERSION

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


class FakeConn:
    """Answers the two queries stage 1 makes: corpus_snapshot and chunks by id."""

    def __init__(self, chunks: dict[int, str], snapshots=None):
        self.chunks = chunks
        default = [("sdd-kafka-databricks@" + "f" * 40, "bge")]
        self.snapshots = default if snapshots is None else snapshots
        self.closed = 0

    def cursor(self):
        conn = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return None

            def execute(self, sql, params=None):
                if "corpus_snapshot" in sql:
                    self.rows = conn.snapshots
                else:
                    self.rows = [(i, conn.chunks[i]) for i in params[0] if i in conn.chunks]

            def fetchall(self):
                return self.rows

        return Cursor()

    def close(self):
        self.closed += 1


def source(chunk_id: int) -> RetrievedSource:
    return RetrievedSource(
        chunk_id=chunk_id,
        source_project="sdd-kafka-databricks",
        source_path="docs/adr/x.md",
        source_anchor=None,
        adr_id=None,
        dense_distance=0.1,
    )


def result_for(question: str, ids: list[int], failed: bool = False) -> AnswerResult:
    return AnswerResult(
        question=question,
        failed=failed,
        output_class=None if failed else "answer",
        shown_text=FAILED_MESSAGE if failed else "An answer.",
        sources=[source(i) for i in ids],
        generation=None,
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        context_format_version=CONTEXT_FORMAT_VERSION,
        latency_ms=5,
        trace_id=None,
        logged=True,
    )


def questions() -> list[GoldenQuestion]:
    return [
        GoldenQuestion(id="q1", intent="decision", question="Why A?", expected_answer="X."),
        GoldenQuestion(id="q2", intent="decision", question="Why B?", expected_answer="Y."),
        GoldenQuestion(id="oos1", intent="out-of-scope", question="Salary?", expected_answer=None),
    ]


def provenance(conn) -> gen.EvalProvenance:
    return gen.read_provenance(conn, get_settings(), "a" * 40, False, NOW)


# ─── Stage 1 ─────────────────────────────────────────────────────────────────


def test_every_question_becomes_one_record_with_contexts_in_source_order(tmp_path):
    conn = FakeConn({1: "chunk one", 2: "chunk two", 3: "chunk three"})
    calls = []

    def fake_answer(question, client, *, connect_fn, origin):
        calls.append((question, origin))
        return result_for(question, {"Why A?": [3, 1], "Why B?": [2]}.get(question, []))

    out = tmp_path / "eval-run-x.json"
    run = gen.generate_run(
        questions(),
        object(),
        provenance(conn),
        connect_fn=lambda: conn,
        out_path=out,
        answer_fn=fake_answer,
    )
    assert [r.question.id for r in run.records] == ["q1", "q2", "oos1"]
    assert run.records[0].contexts == ["chunk three", "chunk one"]
    assert run.records[2].contexts == []
    assert {origin for _, origin in calls} == {"eval"}
    assert EvalRun.model_validate_json(out.read_text()) == run
    assert run.run_id == "eval-run-x"


def test_a_failed_answer_is_recorded_and_the_run_continues(tmp_path):
    conn = FakeConn({1: "chunk one"})

    def fake_answer(question, client, *, connect_fn, origin):
        return result_for(
            question, [] if question == "Why A?" else [1], failed=question == "Why A?"
        )

    run = gen.generate_run(
        questions(),
        object(),
        provenance(conn),
        connect_fn=lambda: conn,
        out_path=tmp_path / "r.json",
        answer_fn=fake_answer,
    )
    assert run.records[0].result.failed
    assert len(run.records) == 3


def test_the_run_file_is_rewritten_after_every_question(tmp_path):
    conn = FakeConn({1: "chunk one"})
    out = tmp_path / "r.json"
    seen = []

    def fake_answer(question, client, *, connect_fn, origin):
        if out.exists():
            seen.append(len(EvalRun.model_validate_json(out.read_text()).records))
        return result_for(question, [1])

    gen.generate_run(
        questions(),
        object(),
        provenance(conn),
        connect_fn=lambda: conn,
        out_path=out,
        answer_fn=fake_answer,
    )
    assert seen == [1, 2]


def test_a_chunk_gone_mid_run_stops_the_run(tmp_path):
    conn = FakeConn({1: "chunk one"})

    def fake_answer(question, client, *, connect_fn, origin):
        return result_for(question, [1, 99])

    with pytest.raises(gen.StaleIndexError, match="99"):
        gen.generate_run(
            questions(),
            object(),
            provenance(conn),
            connect_fn=lambda: conn,
            out_path=tmp_path / "r.json",
            answer_fn=fake_answer,
        )


def test_provenance_reads_the_index_and_the_settings():
    prov = provenance(FakeConn({}))
    assert prov.corpus_commits == ["sdd-kafka-databricks@" + "f" * 40]
    assert prov.embedding_model == "bge"
    assert prov.rerank_top_k == get_settings().rerank_top_k
    assert prov.generation_model == get_settings().llm_model


def test_an_empty_index_or_two_embedding_models_refuse():
    with pytest.raises(gen.StaleIndexError, match="empty"):
        provenance(FakeConn({}, snapshots=[]))
    with pytest.raises(gen.StaleIndexError, match="disagree"):
        provenance(FakeConn({}, snapshots=[("a@1", "m1"), ("b@2", "m2")]))


def test_run_id_is_the_timestamp():
    assert gen.run_id_for(NOW) == "eval-run-20261005-120000"


# ─── The golden set ──────────────────────────────────────────────────────────


def test_the_golden_set_loads_45_in_scope_and_5_out_of_scope():
    loaded = golden_set_loader.load()
    assert len(loaded) == 50
    assert sum(q.in_scope for q in loaded) == 45
    assert all(q.expected_answer for q in loaded if q.in_scope)


def test_the_golden_set_sha_is_the_files_last_commit():
    sha, _ = golden_set_loader.version()
    expected = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", golden_set_loader.GOLDEN_SET],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert sha == expected


def test_a_shallow_clone_is_refused(monkeypatch):
    monkeypatch.setattr(
        golden_set_loader, "_git", lambda *a, cwd: "true" if "--is-shallow-repository" in a else ""
    )
    with pytest.raises(golden_set_loader.GoldenSetVersionError, match="shallow"):
        golden_set_loader.version()


def test_an_uncommitted_edit_is_dirty(monkeypatch):
    answers = {"--is-shallow-repository": "false", "log": "a" * 40, "status": " M file"}

    def fake_git(*args, cwd):
        return next(v for k, v in answers.items() if k in args)

    monkeypatch.setattr(golden_set_loader, "_git", fake_git)
    assert golden_set_loader.version() == ("a" * 40, True)


@pytest.mark.parametrize(
    ("intent", "expected"), [("decision", None), ("out-of-scope", "An answer.")]
)
def test_a_reference_must_match_the_scope(intent, expected):
    with pytest.raises(ValidationError, match="expected_answer"):
        GoldenQuestion(id="q", intent=intent, question="?", expected_answer=expected)


# ─── The CLI refuses before any call ─────────────────────────────────────────


@pytest.mark.parametrize("argv", [["generate"], ["all"], ["score", "missing.json"]])
def test_no_key_exits_2_before_any_work(monkeypatch, capsys, argv):
    import scripts.run_evaluation as cli

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    touched = []
    monkeypatch.setattr(cli, "generate_run", lambda *a, **k: touched.append("generate"))
    monkeypatch.setattr(cli, "connector", lambda s: touched.append("db"))
    assert cli.main(argv) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert touched == []


def test_compare_of_a_non_report_exits_2(tmp_path, capsys):
    import scripts.run_evaluation as cli

    bad = tmp_path / "x.json"
    bad.write_text("{}")
    assert cli.main(["compare", str(bad), str(bad)]) == 2
    assert "not a report" in capsys.readouterr().err
