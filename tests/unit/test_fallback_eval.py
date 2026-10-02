"""scripts/fallback_eval.py with stubs: no key, no API, no database (ADR-020)."""

from __future__ import annotations

import builtins
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fallback_eval  # noqa: E402
from fallback_eval import (  # noqa: E402
    EvalQuestion,
    PreflightError,
    assemble_report,
    measure,
    population_problem,
    retrieve_contexts,
    summarize_run,
)

from data_platform_rag.config import get_settings  # noqa: E402
from data_platform_rag.contracts import (  # noqa: E402
    ChunkMetadata,
    FallbackEvalItem,
    FallbackEvalReport,
    RetrievedChunk,
)
from data_platform_rag.generation.prompt import FALLBACK_MESSAGE  # noqa: E402

PARAPHRASE = "Not covered. Ask on https://linkedin.com/in/christiandrocha please."


def chunk(rank: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        id=rank,
        content="body",
        metadata=ChunkMetadata(
            source_project="sdd-kafka-databricks",
            source_type="adr",
            source_path="docs/adr/ADR-007.md",
            adr_id="ADR-007",
            chunk_index=0,
            token_count=5,
        ),
        dense_distance=0.3,
        dense_rank=rank,
    )


def question(qid: str, *, oos: bool, band: str | None = None) -> EvalQuestion:
    return EvalQuestion(
        id=qid,
        question=f"question {qid}?",
        source="out_of_scope_set" if qid.startswith("oos") else "golden",
        intent="out-of-scope" if oos else "decision",
        band=band if oos else None,
        expects_fallback=oos,
    )


def item(qid: str, cls: str, *, oos: bool, run: int = 1, stop: str = "end_turn"):
    return FallbackEvalItem(
        run=run,
        question_id=qid,
        source="golden",
        intent="out-of-scope" if oos else "decision",
        band="adjacent" if oos else None,
        expects_fallback=oos,
        retrieved=[],
        output_text="x",
        output_class=cls,
        stop_reason=stop,
        input_tokens=10,
        output_tokens=2,
    )


class ScriptedClient:
    """Answers by the question text; raises `fail` on call number `fail_at`."""

    def __init__(self, answers: dict[str, str], fail_at: int | None = None, fail=None):
        self.answers = answers
        self.fail_at = fail_at
        self.fail = fail
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        if self.fail_at is not None and self.calls == self.fail_at:
            raise self.fail
        content = kwargs["messages"][0]["content"]
        text = next(a for q, a in self.answers.items() if f"Question: {q}" in content)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            model="claude-sonnet-4-6",
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )


# ─── summarize_run ───────────────────────────────────────────────────────────


def test_b1_and_b2_counts_from_hand_built_items() -> None:
    items = [
        item("q005", "fallback", oos=True),
        item("oos001", "answer", oos=True),
        item("oos002", "non_compliant_refusal", oos=True),
        item("oos003", "empty", oos=True),
        item("q001", "answer", oos=False),
        item("q002", "fallback", oos=False),
        item("q003", "non_compliant_refusal", oos=False),
        item("q004", "empty", oos=False, stop="max_tokens"),
        item("q006", "answer", oos=False),
    ]
    s = summarize_run(1, items)
    assert (s.out_of_scope_fallback, s.out_of_scope_total) == (1, 4)
    assert (s.in_scope_false_fallback, s.in_scope_total) == (3, 5)
    # A non-compliant refusal and an empty output are B1 misses (ADR-020).
    assert s.missed_ids == ["oos001", "oos002", "oos003"]
    assert s.non_compliant_out_of_scope_ids == ["oos002"]
    # In-scope: fallback, non-compliant and empty all count against B2.
    assert s.false_fallback_ids == ["q002", "q003", "q004"]
    assert s.empty_ids == ["oos003", "q004"]
    assert s.non_end_turn_ids == ["q004"]


def test_summaries_are_per_run() -> None:
    items = [item("q005", "fallback", oos=True, run=1), item("q005", "answer", oos=True, run=2)]
    assert summarize_run(1, items).missed_ids == []
    assert summarize_run(2, items).missed_ids == ["q005"]


# ─── population and retrieval ────────────────────────────────────────────────


def test_the_population_must_be_45_plus_35(monkeypatch: pytest.MonkeyPatch) -> None:
    questions = [question("q001", oos=False), question("q005", oos=True)]
    assert population_problem(questions) is not None
    monkeypatch.setattr(fallback_eval, "IN_SCOPE_TOTAL", 1)
    monkeypatch.setattr(fallback_eval, "OUT_OF_SCOPE_TOTAL", 1)
    assert population_problem(questions) is None


def test_retrieval_runs_once_per_question() -> None:
    asked: list[str] = []

    def retriever(q: str) -> list[RetrievedChunk]:
        asked.append(q)
        return [chunk()]

    questions = [question("q001", oos=False), question("q005", oos=True)]
    contexts = retrieve_contexts(questions, retriever)
    assert asked == ["question q001?", "question q005?"]
    assert set(contexts) == {"q001", "q005"}


def test_an_empty_retrieval_stops_before_any_call() -> None:
    with pytest.raises(PreflightError, match="no chunks"):
        retrieve_contexts([question("q001", oos=False)], lambda q: [])


# ─── measure and the artifact ────────────────────────────────────────────────


QUESTIONS = [question("q001", oos=False), question("q005", oos=True, band="adjacent")]
CONTEXTS = {"q001": [chunk()], "q005": [chunk()]}
ANSWERS = {
    "question q001?": "An answer (ADR-007, sdd-kafka-databricks).",
    "question q005?": FALLBACK_MESSAGE,
}


def report_for(items, reason) -> FallbackEvalReport:
    return assemble_report(
        items,
        reason,
        settings=get_settings(),
        runs=3,
        snapshots=[],
        golden_set_sha256="g",
        out_of_scope_set_sha256="o",
    )


def test_three_runs_over_every_question_reuse_one_context() -> None:
    client = ScriptedClient(ANSWERS)
    items, reason = measure(QUESTIONS, CONTEXTS, client, runs=3)
    assert reason is None
    assert client.calls == 6
    assert [(i.run, i.question_id) for i in items] == [
        (1, "q001"),
        (1, "q005"),
        (2, "q001"),
        (2, "q005"),
        (3, "q001"),
        (3, "q005"),
    ]
    assert [i.output_class for i in items] == ["answer", "fallback"] * 3
    assert items[1].band == "adjacent" and items[0].band is None


def test_a_complete_report_carries_the_numbers_and_parses_back() -> None:
    items, reason = measure(QUESTIONS, CONTEXTS, ScriptedClient(ANSWERS), runs=3)
    report = report_for(items, reason)
    assert report.complete and report.incomplete_reason is None
    assert [s.run for s in report.summaries] == [1, 2, 3]
    assert report.total_input_tokens == 600 and report.total_output_tokens == 120
    assert (report.model, report.temperature, report.max_tokens) == ("claude-sonnet-4-6", 0.0, 1024)
    assert FallbackEvalReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize(
    ("fail", "reason"),
    [(RuntimeError("API down"), "RuntimeError: API down"), (KeyboardInterrupt(), "interrupted")],
)
def test_a_failure_or_interrupt_makes_an_incomplete_report_with_no_numbers(fail, reason) -> None:
    client = ScriptedClient(ANSWERS, fail_at=4, fail=fail)
    items, got = measure(QUESTIONS, CONTEXTS, client, runs=3)
    assert got == reason
    assert len(items) == 3  # the outputs already paid for are kept
    report = report_for(items, got)
    assert not report.complete
    assert report.incomplete_reason == reason
    assert report.summaries == []


# ─── main: preflight writes nothing ──────────────────────────────────────────


@pytest.fixture
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(fallback_eval, "REPORT_DIR", report_dir)

    @contextmanager
    def no_database(settings):
        raise AssertionError("preflight must stop before retrieval")
        yield

    monkeypatch.setattr(fallback_eval, "retrieval_session", no_database)
    return report_dir


def test_an_empty_key_exits_2_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, isolated_paths: Path, capsys
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    assert fallback_eval.main([]) == 2
    assert "ANTHROPIC_API_KEY is empty" in capsys.readouterr().err
    assert not isolated_paths.exists()


def test_a_missing_anthropic_package_exits_2_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, isolated_paths: Path, capsys
) -> None:
    real_import = builtins.__import__

    def no_anthropic(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    assert fallback_eval.main([]) == 2
    assert "anthropic" in capsys.readouterr().err
    assert not isolated_paths.exists()


def test_an_incomplete_population_exits_2_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, isolated_paths: Path, capsys
) -> None:
    """A population other than 45 + 35 is refused before retrieval.

    Built here rather than read from the real files: this test once relied on
    the out-of-scope set being incomplete, and broke when the set reached 30.
    """
    monkeypatch.setattr(fallback_eval, "make_client", lambda key: object())
    monkeypatch.setattr(fallback_eval, "load_questions", lambda: QUESTIONS)
    assert fallback_eval.main([]) == 2
    assert "Finish curating" in capsys.readouterr().err
    assert not isolated_paths.exists()


def test_main_end_to_end_with_stubs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(fallback_eval, "REPORT_DIR", report_dir)
    monkeypatch.setattr(fallback_eval, "load_questions", lambda: QUESTIONS)
    monkeypatch.setattr(fallback_eval, "IN_SCOPE_TOTAL", 1)
    monkeypatch.setattr(fallback_eval, "OUT_OF_SCOPE_TOTAL", 1)
    monkeypatch.setattr(fallback_eval, "make_client", lambda key: ScriptedClient(ANSWERS))
    asked: list[str] = []

    @contextmanager
    def stub_session(settings):
        def retriever(q):
            asked.append(q)
            return [chunk()]

        yield retriever, []

    monkeypatch.setattr(fallback_eval, "retrieval_session", stub_session)
    # An empty index is refused...
    assert fallback_eval.main([]) == 2
    assert not report_dir.exists()

    # ...and a populated one is measured.
    from data_platform_rag.contracts import IndexedSnapshot

    snapshot = IndexedSnapshot(
        source_project="sdd-kafka-databricks",
        repo_url="https://example.com/r",
        commit_sha="a" * 40,
        file_count=1,
        manifest_created_at="2026-10-02T00:00:00Z",
        manifest_schema_version=1,
        embedding_model="m",
        embedding_dim=384,
        chunk_count=1,
    )

    @contextmanager
    def populated(settings):
        def retriever(q):
            asked.append(q)
            return [chunk()]

        yield retriever, [snapshot]

    monkeypatch.setattr(fallback_eval, "retrieval_session", populated)
    asked.clear()
    assert fallback_eval.main([]) == 0
    assert asked == ["question q001?", "question q005?"]  # once each, for 3 runs
    (artifact,) = report_dir.iterdir()
    report = FallbackEvalReport.model_validate(json.loads(artifact.read_text()))
    assert report.complete and len(report.items) == 6
    out = capsys.readouterr().out
    assert "Run 3: out-of-scope fallback 1/1   in-scope false fallback 0/1" in out
