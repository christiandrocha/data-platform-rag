"""scripts/check_deploy_gate.py: deploy only once ADR-020 is Accepted (ADR-021)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_deploy_gate import ADR_020, gate_status  # noqa: E402


def adr(tmp_path: Path, status_line: str | None) -> Path:
    path = tmp_path / "ADR-020.md"
    lines = ["# ADR-020 — rule 3", ""]
    if status_line is not None:
        lines.append(status_line)
    lines += ["**Date**: 2026-10-02", "", "## Context"]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_accepted_opens_the_gate(tmp_path: Path) -> None:
    is_open, reason = gate_status(adr(tmp_path, "**Status**: Accepted — 2026-11-01"))
    assert is_open is True
    assert "Accepted" in reason


@pytest.mark.parametrize(
    "status_line",
    [
        "**Status**: Planned — 2026-10-02. Measurement pending an API key",
        "**Status**: Rejected — 2026-11-01 (B1 failed)",
        "**Status**: Superseded by ADR-022",
        None,
    ],
)
def test_anything_else_keeps_it_closed(tmp_path: Path, status_line) -> None:
    is_open, _ = gate_status(adr(tmp_path, status_line))
    assert is_open is False


def test_a_missing_file_keeps_it_closed(tmp_path: Path) -> None:
    is_open, reason = gate_status(tmp_path / "absent.md")
    assert is_open is False
    assert "not found" in reason


def test_the_real_adr_020_is_read_and_closed_today() -> None:
    """Points at the real file, so a rename breaks this test instead of the gate."""
    root = Path(__file__).resolve().parents[2]
    is_open, reason = gate_status(root / ADR_020)
    assert "not found" not in reason
    assert is_open is reason.removeprefix("ADR-020 status: ").startswith("Accepted")
