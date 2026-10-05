"""The page (ADR-021), run in-process with Streamlit's AppTest.

`answer()` is replaced by a fake that returns a hand-built `AnswerResult`, and the
SDK client by a sentinel, so no test needs a key, a database or the network.
What is under test is the page: what it draws for each result, and that without
a key it draws no form and runs nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from data_platform_rag.config import get_settings, get_settings_without_llm
from data_platform_rag.contracts import AnswerResult, GenerationResult, RetrievedSource
from data_platform_rag.generation import answer as answer_module
from data_platform_rag.generation.answer import FAILED_MESSAGE, validate_question
from data_platform_rag.generation.prompt import (
    CONTEXT_FORMAT_VERSION,
    FALLBACK_MESSAGE,
    SYSTEM_PROMPT_VERSION,
)
from data_platform_rag.ui.app import LOGGED_NOTICE, NOT_CONFIGURED, source_lines

APP = Path(__file__).resolve().parents[2] / "data_platform_rag" / "ui" / "app.py"


def source(
    rank: int,
    *,
    path: str = "docs/adr/ADR-001.md",
    adr_id: str | None = "ADR-001",
    anchor: str | None = "Decision",
) -> RetrievedSource:
    return RetrievedSource(
        chunk_id=rank,
        source_project="sdd-kafka-databricks",
        source_path=path,
        source_anchor=anchor,
        adr_id=adr_id,
        dense_distance=0.1 * rank,
    )


def result(output_class, shown_text: str, *, failed: bool = False) -> AnswerResult:
    return AnswerResult(
        question="Why A?",
        failed=failed,
        output_class=output_class,
        shown_text=shown_text,
        sources=[source(1), source(2), source(3, path="README.md", adr_id=None, anchor=None)],
        generation=None
        if failed
        else GenerationResult(
            text=shown_text,
            model="claude-sonnet-4-6",
            stop_reason="end_turn",
            input_tokens=900,
            output_tokens=40,
        ),
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        context_format_version=CONTEXT_FORMAT_VERSION,
        latency_ms=1200,
        logged=True,
    )


@pytest.fixture(autouse=True)
def fresh_caches():
    """The page reads `get_settings_without_llm` and caches the client per key."""
    for cache in (get_settings, get_settings_without_llm):
        cache.cache_clear()
    st.cache_resource.clear()
    yield
    for cache in (get_settings, get_settings_without_llm):
        cache.cache_clear()
    st.cache_resource.clear()


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch):
    """Record `answer()` calls; the test sets what it returns."""
    recorded: dict = {"questions": [], "returns": None}

    def fake_answer(question, client):
        validate_question(question, 500)
        recorded["questions"].append(question)
        return recorded["returns"]

    monkeypatch.setattr(answer_module, "answer", fake_answer)
    monkeypatch.setattr("data_platform_rag.generation.sdk.build_client", lambda key: object())
    return recorded


def ask(question: str) -> AppTest:
    app = AppTest.from_file(str(APP)).run()
    app.text_area[0].input(question)
    app.button[0].click().run()
    return app


def texts(elements) -> list[str]:
    return [element.value for element in elements]


# ─── source_lines ────────────────────────────────────────────────────────────


def test_source_lines_dedupes_a_section_in_rank_order():
    lines = source_lines(
        [source(1), source(2), source(3, path="README.md", adr_id=None, anchor=None)]
    )
    assert lines == [
        "sdd-kafka-databricks · `docs/adr/ADR-001.md` · ADR-001 · Decision",
        "sdd-kafka-databricks · `README.md`",
    ]


def test_source_lines_keeps_two_sections_of_one_file():
    lines = source_lines([source(1, anchor="Context"), source(2, anchor="Decision")])
    assert len(lines) == 2


# ─── the page ────────────────────────────────────────────────────────────────


def test_no_key_draws_no_form_and_runs_nothing(monkeypatch, calls):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert texts(app.info) == [NOT_CONFIGURED]
    assert len(app.text_area) == 0
    assert calls["questions"] == []


def test_the_form_caps_the_question_and_states_the_logging(calls):
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert app.text_area[0].max_chars == get_settings().max_question_chars
    assert LOGGED_NOTICE in texts(app.caption)


def test_an_answer_shows_its_text_then_its_sources(calls):
    calls["returns"] = result("answer", "A is chosen [databricks ADR-001].")
    app = ask("  Why A?\n")
    assert not app.exception
    assert calls["questions"] == ["Why A?"]
    shown = texts(app.markdown)
    assert shown[0] == "A is chosen [databricks ADR-001]."
    assert "**Sources**" in shown
    assert shown[-1] == (
        "- sdd-kafka-databricks · `docs/adr/ADR-001.md` · ADR-001 · Decision\n"
        "- sdd-kafka-databricks · `README.md`"
    )


@pytest.mark.parametrize(
    ("output_class", "shown_text", "failed"),
    [
        ("fallback", FALLBACK_MESSAGE, False),
        ("empty", FALLBACK_MESSAGE, False),
        ("non_compliant_refusal", "Not covered. See LinkedIn.", False),
        (None, FAILED_MESSAGE, True),
    ],
)
def test_every_other_result_shows_its_text_and_nothing_else(
    calls, output_class, shown_text, failed
):
    calls["returns"] = result(output_class, shown_text, failed=failed)
    app = ask("Why A?")
    assert not app.exception
    assert texts(app.markdown) == [shown_text]


def test_a_blank_question_is_a_warning_not_a_query(calls):
    app = ask("   ")
    assert not app.exception
    assert calls["questions"] == []
    assert texts(app.warning) == ["question must be a non-empty string"]
