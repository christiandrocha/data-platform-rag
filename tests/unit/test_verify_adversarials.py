"""verify_adversarials collects the out-of-scope questions of both files (ADR-020)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from verify_adversarials import QUESTION_FILES, load_adversarials  # noqa: E402


def write(path: Path, body: str) -> Path:
    path.write_text(body)
    return path


def test_both_question_files_are_gated() -> None:
    names = {p.name for p in QUESTION_FILES}
    assert names == {"evaluation_questions.yml", "out_of_scope_questions.yml"}


def test_out_of_scope_questions_of_both_files_are_collected(tmp_path: Path) -> None:
    golden = write(
        tmp_path / "golden.yml",
        """
- {id: q001, intent: decision}
- {id: q005, intent: out-of-scope}
""",
    )
    oos = write(tmp_path / "oos.yml", "- {id: oos001, intent: out-of-scope}\n")
    ids = [q["id"] for q in load_adversarials((golden, oos))]
    assert ids == ["q005", "oos001"]


def test_an_empty_out_of_scope_set_is_fine(tmp_path: Path) -> None:
    golden = write(tmp_path / "golden.yml", "- {id: q005, intent: out-of-scope}\n")
    oos = write(tmp_path / "oos.yml", "[]\n")
    assert [q["id"] for q in load_adversarials((golden, oos))] == ["q005"]


def test_a_missing_file_is_reported_not_skipped(tmp_path: Path) -> None:
    golden = write(tmp_path / "golden.yml", "- {id: q005, intent: out-of-scope}\n")
    with pytest.raises(ValueError, match="not found"):
        load_adversarials((golden, tmp_path / "absent.yml"))
