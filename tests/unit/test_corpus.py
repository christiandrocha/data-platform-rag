"""The in-corpus rule set, the manifest contract, and snapshot resolution.

These cover the ADR-012 decisions that are easy to regress silently: which files
are corpus, and whether an unusable snapshot raises instead of passing vacuously.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from data_platform_rag.contracts import CorpusFile, CorpusManifest, CorpusProject
from data_platform_rag.indexer.corpus import (
    MANIFEST_NAME,
    classified_files,
    corpus_projects,
    in_corpus_files,
    read_manifest,
    resolve_snapshot,
)

SHA = "a" * 64
COMMIT = "b" * 40


def build_snowflake(root):
    """A minimal snowflake-shaped project, including the disputed files."""
    project = root / "sdd-kafka-snowflake-2"
    (project / "docs/adr").mkdir(parents=True)
    (project / "dbt/macros").mkdir(parents=True)
    (project / "connectors").mkdir(parents=True)
    (project / "docs/adr/0018_dedicated_postgres.md").write_text("# ADR 0018\n")
    (project / "docs/adr/README.md").write_text("# Architecture Decision Records\n")
    (project / "README.md").write_text("# Snowflake\n")
    (project / "dbt/macros/resolve_cdc.sql").write_text("select 1\n")
    (project / "connectors/debezium.json").write_text("{}\n")
    return project


def build_databricks(root):
    project = root / "sdd-kafka-databricks"
    (project / "docs/adr").mkdir(parents=True)
    (project / "contracts").mkdir(parents=True)
    (project / "docs/adr/004_liquid_clustering.md").write_text("# ADR 004\n")
    (project / "README.md").write_text("# Databricks\n")
    (project / "contracts/orders.yml").write_text("table: orders\n")
    (project / "contracts/loader.py").write_text("import yaml\n")
    (project / "contracts/__init__.py").write_text("")
    return project


def test_projects_come_from_the_contract_not_from_disk():
    assert corpus_projects() == ["sdd-kafka-databricks", "sdd-kafka-snowflake-2"]


def test_adr_index_is_excluded_but_adrs_are_not(tmp_path):
    project = build_snowflake(tmp_path)
    names = {p.name for p in in_corpus_files(project, "sdd-kafka-snowflake-2")}
    assert "0018_dedicated_postgres.md" in names
    # An index of links, dense in ADR titles, answering nothing (ADR-012).
    assert "docs/adr/README.md" not in {
        str(p.relative_to(project)) for p in in_corpus_files(project, "sdd-kafka-snowflake-2")
    }
    assert "README.md" in names  # the repo root README still is corpus


def test_python_under_contracts_is_excluded_while_yaml_beside_it_is_not(tmp_path):
    project = build_databricks(tmp_path)
    files = in_corpus_files(project, "sdd-kafka-databricks")
    relative = {str(p.relative_to(project)) for p in files}
    assert "contracts/orders.yml" in relative
    assert "contracts/loader.py" not in relative
    assert "contracts/__init__.py" not in relative


def test_connector_config_is_not_corpus(tmp_path):
    project = build_snowflake(tmp_path)
    files = in_corpus_files(project, "sdd-kafka-snowflake-2")
    relative = {str(p.relative_to(project)) for p in files}
    assert not any(r.startswith("connectors/") for r in relative)


def test_source_types_are_assigned_at_extraction(tmp_path):
    project = build_snowflake(tmp_path)
    by_name = {p.name: t for p, t in classified_files(project, "sdd-kafka-snowflake-2")}
    assert by_name["0018_dedicated_postgres.md"] == "adr"
    assert by_name["README.md"] == "readme"
    assert by_name["resolve_cdc.sql"] == "macro"


def test_a_rule_matching_nothing_raises_rather_than_covering_zero_files(tmp_path):
    """The IN_CORPUS_SUBPATHS defect (dev-log #13): a wrong path reported green."""
    project = tmp_path / "sdd-kafka-snowflake-2"
    (project / "docs/adr").mkdir(parents=True)
    (project / "README.md").write_text("# x\n")
    with pytest.raises(FileNotFoundError, match="dbt/macros"):
        in_corpus_files(project, "sdd-kafka-snowflake-2")


def test_extraction_order_is_deterministic(tmp_path):
    project = build_databricks(tmp_path)
    assert in_corpus_files(project, "sdd-kafka-databricks") == in_corpus_files(
        project, "sdd-kafka-databricks"
    )


# ─── Manifest contract ───────────────────────────────────────────────────────


def _manifest() -> CorpusManifest:
    return CorpusManifest(
        created_at="2026-09-17T10:00:00Z",
        projects=[
            CorpusProject(
                project="sdd-kafka-databricks",
                repo_url="https://github.com/christiandrocha/sdd-kafka-databricks",
                commit_sha=COMMIT,
                files=[CorpusFile(path="README.md", sha256=SHA, source_type="readme")],
            )
        ],
    )


def test_manifest_round_trips():
    original = _manifest()
    assert CorpusManifest.model_validate_json(original.model_dump_json()) == original


def test_short_commit_sha_is_rejected():
    with pytest.raises(ValidationError):
        CorpusProject(
            project="sdd-kafka-databricks",
            repo_url="https://example.com/x",
            commit_sha="b" * 39,
            files=[CorpusFile(path="README.md", sha256=SHA, source_type="readme")],
        )


def test_non_hex_sha256_is_rejected():
    with pytest.raises(ValidationError):
        CorpusFile(path="README.md", sha256="z" * 64, source_type="readme")


def test_a_project_with_no_files_is_rejected():
    with pytest.raises(ValidationError):
        CorpusProject(
            project="sdd-kafka-databricks",
            repo_url="https://example.com/x",
            commit_sha=COMMIT,
            files=[],
        )


# ─── Snapshot resolution: every failure mode raises ──────────────────────────


def test_missing_snapshot_raises(tmp_path):
    with pytest.raises(SystemExit, match="does not exist"):
        resolve_snapshot(tmp_path / "absent")


def test_empty_snapshot_raises_rather_than_producing_a_false_green(tmp_path):
    empty = tmp_path / "snapshot"
    empty.mkdir()
    with pytest.raises(SystemExit, match="FALSE GREEN"):
        resolve_snapshot(empty)


def test_snapshot_without_a_manifest_has_no_provenance(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "sdd-kafka-databricks").mkdir()
    with pytest.raises(SystemExit, match="no recorded provenance"):
        read_manifest(snapshot)


def test_manifest_is_read_back_from_the_snapshot(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / MANIFEST_NAME).write_text(_manifest().model_dump_json())
    assert read_manifest(snapshot).projects[0].commit_sha == COMMIT


def test_a_corrupt_manifest_raises(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / MANIFEST_NAME).write_text(json.dumps({"schema_version": 1}))
    with pytest.raises(ValidationError):
        read_manifest(snapshot)
