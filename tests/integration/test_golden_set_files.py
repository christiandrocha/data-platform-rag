"""The real golden-set files, through the same entry points `make` uses.

Unit tests cover each check as a pure function. What they cannot catch is the
file on disk drifting from the vocabulary the code enforces — a project name
that no longer matches contracts.SourceProject, or a script that exits non-zero
during curation and turns a build red. These run the scripts as subprocesses,
with PYTHONPATH set the way the Makefile sets it, so the tested path is the
path that actually runs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from data_platform_rag.contracts import SourceProject
from data_platform_rag.indexer.corpus import SNAPSHOT_GLOB, SNAPSHOT_PARENT

REPO = Path(__file__).resolve().parents[2]
GOLDEN_SET = REPO / "docs/golden-set/evaluation_questions.yml"


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": "."}
    return subprocess.run(
        [sys.executable, f"scripts/{script}", *args],
        cwd=REPO, env=env, capture_output=True, text=True,
    )


@pytest.fixture(scope="module")
def questions() -> list[dict]:
    return yaml.safe_load(GOLDEN_SET.read_text())


def test_real_golden_set_validates_clean():
    result = run("validate_golden_set.py")
    assert result.returncode == 0, result.stdout + result.stderr


def test_coverage_warns_without_failing_while_the_set_is_incomplete():
    result = run("golden_set_coverage.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "uncovered. Next:" in result.stdout
    assert "warning only" in result.stdout


def test_every_project_is_a_contract_member(questions):
    allowed = set(SourceProject.__args__)
    cited = {s["project"] for q in questions for s in q.get("expected_source_paths") or []}
    assert cited <= allowed


def test_every_path_is_a_plain_relative_path(questions):
    paths = [s["path"] for q in questions for s in q.get("expected_source_paths") or []]
    assert paths
    for path in paths:
        assert not path.startswith("/") and ".." not in Path(path).parts


def test_contamination_check_passes_against_the_real_snapshot():
    if not any(SNAPSHOT_PARENT.glob(SNAPSHOT_GLOB)):
        pytest.skip("no corpus snapshot; run make fetch-corpus")
    result = run("check_contamination.py")
    assert result.returncode == 0, result.stdout + result.stderr
