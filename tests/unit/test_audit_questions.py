"""The Layer 2 audit reads both question files (ADR-020)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import audit_questions  # noqa: E402


@pytest.fixture
def two_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    golden = tmp_path / "golden.yml"
    golden.write_text(
        "- {id: q001, intent: decision, provenance: human}\n"
        "- {id: q005, intent: out-of-scope, provenance: human}\n"
    )
    oos = tmp_path / "oos.yml"
    oos.write_text("- {id: oos001, intent: out-of-scope, provenance: llm}\n")
    monkeypatch.setattr(audit_questions, "QUESTION_FILES", (golden, oos))


def test_an_out_of_scope_set_question_can_be_audited_by_id(two_files) -> None:
    assert [q["id"] for q in audit_questions.load_questions(None, "oos001")] == ["oos001"]


def test_both_files_are_read(two_files) -> None:
    ids = [q["id"] for q in audit_questions.load_questions(None, None)]
    assert ids == ["q001", "q005", "oos001"]


def test_provenance_filters_across_both_files(two_files) -> None:
    ids = [q["id"] for q in audit_questions.load_questions("llm", None)]
    assert ids == ["oos001"]
