"""The golden set, as a run reads it, and its version (ADR-008, ADR-011).

ADR-011 commitment 2: every run records the git SHA of `evaluation_questions.yml`,
and two runs with different SHAs are not comparable. The SHA is the last commit
that touched the file, which is what changes when a scored field changes. A file
with uncommitted edits is flagged as dirty, because its SHA does not describe it.
"""

from __future__ import annotations

# A fixed git argv below, no shell, no user input.
import subprocess  # nosec B404
from pathlib import Path

import yaml

from data_platform_rag.contracts import GoldenQuestion

GOLDEN_SET = Path("docs/golden-set/evaluation_questions.yml")


class GoldenSetVersionError(Exception):
    """The golden set's version cannot be read honestly."""


def load(path: Path = GOLDEN_SET) -> list[GoldenQuestion]:
    """Every question in file order. A malformed entry raises ValidationError."""
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        GoldenQuestion(
            id=entry["id"],
            intent=entry["intent"],
            question=entry["question"],
            expected_answer=entry.get("expected_answer") or None,
        )
        for entry in entries
    ]


def _git(*args: str, cwd: Path) -> str:
    # Fixed argv, no shell, no user input; git from PATH, as scripts/fetch_corpus.py.
    result = subprocess.run(  # nosec B603 B607  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def version(path: Path = GOLDEN_SET) -> tuple[str, bool]:
    """(last commit SHA of the file, whether it has uncommitted changes).

    Refuses a shallow clone. There `git log -- FILE` stops at the graft and names
    the clone's only commit, whatever last touched the file, so the SHA would be
    wrong without any error. `actions/checkout` is shallow by default, which is
    why `ragas.yml` fetches the full history.
    """
    repo = path.resolve().parent
    try:
        if _git("rev-parse", "--is-shallow-repository", cwd=repo) == "true":
            raise GoldenSetVersionError(
                "the repository is a shallow clone, so the golden set's last commit "
                "cannot be read. Fetch the full history (fetch-depth: 0)."
            )
        sha = _git("log", "-1", "--format=%H", "--", path.name, cwd=repo)
        dirty = _git("status", "--porcelain", "--", path.name, cwd=repo) != ""
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GoldenSetVersionError(f"git could not read {path}: {exc}") from exc
    if not sha:
        raise GoldenSetVersionError(f"{path} has no commit: commit it before a run.")
    return sha, dirty
