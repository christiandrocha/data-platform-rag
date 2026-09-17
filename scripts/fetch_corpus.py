"""Create the canonical corpus snapshot. Per ADR-012.

Shallow-clones each corpus repo, copies only the in-corpus file set into
/tmp/dpr-corpus-{timestamp}/{project}/, writes MANIFEST.json recording the commit
SHA and a sha256 per file, and deletes the full clone before exiting.

The snapshot persists — that is the point. Its consumers are the ADR-011
adversarial gate, the Layer 2 auditor, and the inventory staleness check, none of
which can run against a directory that deletes itself.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from data_platform_rag.config import Settings, get_settings
from data_platform_rag.contracts import (
    CorpusFile,
    CorpusManifest,
    CorpusProject,
    SourceProject,
)
from data_platform_rag.indexer.corpus import (
    MANIFEST_NAME,
    SNAPSHOT_GLOB,
    SNAPSHOT_PARENT,
    classified_files,
    corpus_projects,
)

_SETTINGS_FIELD = {
    "sdd-kafka-snowflake-2": "corpus_repo_snowflake",
    "sdd-kafka-databricks": "corpus_repo_databricks",
}


def repo_urls() -> dict[SourceProject, str]:
    """Clone URLs for both corpora, from config.py — the single declaration.

    Falls back to the *declared field defaults* when a full Settings cannot be
    built. Settings requires an Anthropic key and a database URL, and cloning two
    public repositories needs neither; without this fallback, `fetch-corpus`
    would demand secrets it never uses. The values are identical either way,
    because they come from the same field.
    """
    try:
        settings = get_settings()
        return {p: getattr(settings, _SETTINGS_FIELD[p]) for p in corpus_projects()}
    except ValidationError:
        fields = Settings.model_fields
        return {p: fields[_SETTINGS_FIELD[p]].default for p in corpus_projects()}


def _git(*args: str, cwd: Path | None = None) -> str:
    """Run git with an argument list. No shell, no interpolation."""
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell, no user input
        ["git", *args],  # noqa: S607 — git resolved from PATH by design
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"ERROR: git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def extract_project(project: SourceProject, url: str, snapshot: Path) -> CorpusProject:
    """Clone, copy the in-corpus files into the snapshot, delete the clone."""
    destination = snapshot / project
    destination.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"dpr-clone-{project}-") as scratch:
        clone = Path(scratch) / project
        _git("clone", "--depth", "1", "--quiet", url, str(clone))
        commit_sha = _git("rev-parse", "HEAD", cwd=clone)

        files: list[CorpusFile] = []
        for source, source_type in classified_files(clone, project):
            relative = source.relative_to(clone)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            files.append(
                CorpusFile(
                    path=str(relative),
                    sha256=sha256_of(target),
                    source_type=source_type,
                )
            )
    # TemporaryDirectory removed the full clone here, including .git.

    print(f"  {project}  {commit_sha[:8]}  {len(files)} files")
    return CorpusProject(
        project=project,
        repo_url=url,
        commit_sha=commit_sha,
        files=files,
    )


def delete_old_snapshots(keep: Path) -> int:
    """Remove previous snapshots so "newest wins" describes the only one present."""
    removed = 0
    for old in SNAPSHOT_PARENT.glob(SNAPSHOT_GLOB):
        if old.resolve() == keep.resolve() or not old.is_dir():
            continue
        shutil.rmtree(old, ignore_errors=True)
        removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Snapshot root. Defaults to /tmp/dpr-corpus-{timestamp} (canonical).",
    )
    parser.add_argument(
        "--keep-old",
        action="store_true",
        help="Do not delete previous /tmp/dpr-corpus-* snapshots.",
    )
    args = parser.parse_args()

    created_at = datetime.now(UTC)
    snapshot = args.out_dir or (
        SNAPSHOT_PARENT / f"dpr-corpus-{created_at.strftime('%Y%m%d-%H%M%S')}"
    )
    snapshot.mkdir(parents=True, exist_ok=True)

    urls = repo_urls()
    print(f"Extracting corpus into {snapshot}")
    projects = [extract_project(p, urls[p], snapshot) for p in corpus_projects()]

    manifest = CorpusManifest(created_at=created_at, projects=projects)
    (snapshot / MANIFEST_NAME).write_text(manifest.model_dump_json(indent=2) + "\n")

    if not args.keep_old:
        removed = delete_old_snapshots(keep=snapshot)
        if removed:
            print(f"  removed {removed} older snapshot(s)")

    total = sum(len(p.files) for p in manifest.projects)
    print(f"✓ {len(manifest.projects)} project(s), {total} files, manifest written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
