"""Acquisition end to end, against local fixture repos rather than the network.

`fetch_corpus` clones a URL, and a local path is a valid git URL, so the whole
path is exercised — clone, SHA, extraction, manifest, clone deletion — with no
network and no dependence on what the real corpora contain today.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from data_platform_rag.contracts import CorpusManifest
from data_platform_rag.indexer.corpus import MANIFEST_NAME
from scripts.fetch_corpus import extract_project


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """A databricks-shaped repo with one file of every in-corpus kind, plus noise."""
    repo = tmp_path / "origin" / "sdd-kafka-databricks"
    (repo / "docs/adr").mkdir(parents=True)
    (repo / "contracts").mkdir(parents=True)
    (repo / "connectors").mkdir(parents=True)
    (repo / "docs/adr/004_liquid_clustering.md").write_text("# ADR 004 — Clustering\n")
    (repo / "README.md").write_text("# Databricks\n\n## Stack\nDelta Lake\n")
    (repo / "contracts/orders.yml").write_text("table: orders\n")
    (repo / "contracts/loader.py").write_text("import yaml\n")
    (repo / "connectors/debezium.json").write_text("{}\n")

    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "t@example.com", cwd=repo)
    git("config", "user.name", "t", cwd=repo)
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "fixture", cwd=repo)
    return repo


def test_only_in_corpus_files_reach_the_snapshot(tmp_path, fixture_repo):
    snapshot = tmp_path / "snap"
    snapshot.mkdir()
    project = extract_project("sdd-kafka-databricks", fixture_repo.as_uri(), snapshot)

    extracted = {f.path for f in project.files}
    assert extracted == {"docs/adr/004_liquid_clustering.md", "README.md", "contracts/orders.yml"}
    assert "contracts/loader.py" not in extracted
    assert not any(p.startswith("connectors/") for p in extracted)


def test_the_full_clone_does_not_survive(tmp_path, fixture_repo):
    snapshot = tmp_path / "snap"
    snapshot.mkdir()
    project = extract_project("sdd-kafka-databricks", fixture_repo.as_uri(), snapshot)

    on_disk = {
        str(p.relative_to(snapshot / "sdd-kafka-databricks"))
        for p in (snapshot / "sdd-kafka-databricks").rglob("*")
        if p.is_file()
    }
    assert on_disk == {f.path for f in project.files}
    assert list(snapshot.rglob(".git")) == []


def test_the_commit_sha_is_recorded(tmp_path, fixture_repo):
    snapshot = tmp_path / "snap"
    snapshot.mkdir()
    project = extract_project("sdd-kafka-databricks", fixture_repo.as_uri(), snapshot)

    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=fixture_repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert project.commit_sha == expected


def test_two_runs_on_an_unchanged_repo_produce_identical_hashes(tmp_path, fixture_repo):
    first = extract_project("sdd-kafka-databricks", fixture_repo.as_uri(), tmp_path / "a")
    second = extract_project("sdd-kafka-databricks", fixture_repo.as_uri(), tmp_path / "b")
    assert {(f.path, f.sha256) for f in first.files} == {(f.path, f.sha256) for f in second.files}


def test_source_types_land_in_the_manifest(tmp_path, fixture_repo):
    project = extract_project("sdd-kafka-databricks", fixture_repo.as_uri(), tmp_path / "snap")
    by_path = {f.path: f.source_type for f in project.files}
    assert by_path["docs/adr/004_liquid_clustering.md"] == "adr"
    assert by_path["README.md"] == "readme"
    assert by_path["contracts/orders.yml"] == "contract"


def test_a_written_manifest_validates(tmp_path, fixture_repo):
    snapshot = tmp_path / "snap"
    project = extract_project("sdd-kafka-databricks", fixture_repo.as_uri(), snapshot)
    manifest = CorpusManifest(created_at="2026-09-17T00:00:00Z", projects=[project])
    (snapshot / MANIFEST_NAME).write_text(manifest.model_dump_json(indent=2))

    loaded = json.loads((snapshot / MANIFEST_NAME).read_text())
    assert CorpusManifest.model_validate(loaded) == manifest
