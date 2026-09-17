"""The single owner of the in-corpus file set and of snapshot resolution.

Per ADR-012. Before this module the set was defined three times — in
`verify_adversarials.py` as `IN_CORPUS_SUBPATHS`, in `corpus_inventory.yml` by
hand, and implicitly in the loader — and the definitions disagreed on six files.
A gate whose scope is *wider* than the index over-blocks: a contamination probe
matching Python source the system can never retrieve rejects a valid adversarial
question.

AGENTS.md now forbids re-declaring this set anywhere else. Import from here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from data_platform_rag.contracts import CorpusManifest, SourceProject, SourceType

MANIFEST_NAME = "MANIFEST.json"
SNAPSHOT_GLOB = "dpr-corpus-*"
SNAPSHOT_PARENT = Path("/tmp")  # noqa: S108 — canonical per AGENTS.md, see ADR-012


@dataclass(frozen=True)
class CorpusRule:
    """One inclusion rule: a glob under a subpath, mapped to a source type.

    `exclude` holds basenames that match the glob but are not corpus. It exists
    for exactly one file today (the snowflake ADR index), and naming it here
    keeps that exclusion in the same place as the rule it qualifies.
    """

    subpath: str
    pattern: str
    source_type: SourceType
    exclude: frozenset[str] = frozenset()


# The v1 in-corpus set, per ADR-012 Decision 4.
#
# Excluded deliberately, and argued in the ADR: docs/adr/README.md (an index of
# links, dense in ADR titles, answering nothing); contracts/*.py (source code,
# already excluded by PRE_BUILD_VALIDATION Section 2); connectors/*.json
# (runtime config); and every other tree in both repos.
#
# The `schema` source type has no rule because it has no producer: no .avsc or
# registry-subject file exists in either corpus. The subjects live in a running
# Schema Registry. See ADR-012 Decision 5.
IN_CORPUS: dict[SourceProject, tuple[CorpusRule, ...]] = {
    "sdd-kafka-snowflake-2": (
        CorpusRule("docs/adr", "*.md", "adr", frozenset({"README.md"})),
        CorpusRule(".", "README.md", "readme"),
        CorpusRule("dbt/macros", "*.sql", "macro"),
    ),
    "sdd-kafka-databricks": (
        CorpusRule("docs/adr", "*.md", "adr"),
        CorpusRule(".", "README.md", "readme"),
        CorpusRule("contracts", "*.yml", "contract"),
    ),
}


def corpus_projects() -> list[SourceProject]:
    """The corpus repo names, from the contract — never inferred from disk.

    Walking whatever sits beside the clones would eventually grep this
    repository, which AGENTS.md forbids treating as a corpus source.
    """
    return sorted(get_args(SourceProject))


def classified_files(project_root: Path, project: SourceProject) -> list[tuple[Path, SourceType]]:
    """Every in-corpus file under one corpus repo, with its source type.

    Rules are applied in declaration order and a file is yielded once. Results
    are sorted so a manifest is byte-identical across runs on the same commit.
    """
    seen: dict[Path, SourceType] = {}
    for rule in IN_CORPUS[project]:
        base = (project_root / rule.subpath).resolve()
        if not base.is_dir():
            # A rule pointing at nothing is the IN_CORPUS_SUBPATHS defect
            # (dev-log #13): it covers zero files and reports success.
            raise FileNotFoundError(
                f"in-corpus rule {rule.subpath!r}/{rule.pattern!r} for {project} "
                f"resolves to {base}, which is not a directory. A rule that matches "
                f"nothing is skipped in silence and the gate reports green."
            )
        for path in sorted(base.glob(rule.pattern)):
            if not path.is_file() or path.name in rule.exclude:
                continue
            seen.setdefault(path, rule.source_type)
    return sorted(seen.items())


def in_corpus_files(project_root: Path, project: SourceProject) -> list[Path]:
    """Paths only, for consumers that do not care what kind of file it is."""
    return [path for path, _ in classified_files(project_root, project)]


def resolve_snapshot(explicit: Path | None = None) -> Path:
    """Locate the corpus snapshot. Raises rather than returning an unusable path.

    The canonical location is the newest /tmp/dpr-corpus-*, created by
    `make fetch-corpus`. CI has no ~/Documents, so /tmp is the only path that
    works in both environments; a local override buys iteration speed at the
    cost of reproducibility, which is acceptable for dev and not for CI.

    Every failure mode raises. An absent or empty snapshot produces a FALSE
    GREEN in the adversarial gate: every probe finds nothing and the gate
    reports success while the contamination it exists to catch sails through
    (dev-log #16). ADR-012 extends that invariant to a snapshot with no manifest,
    which cannot be provenance-checked and so cannot be trusted either.
    """
    if explicit is not None:
        snapshot = explicit.expanduser()
        if not snapshot.is_dir():
            raise SystemExit(
                f"ERROR: --corpus-dir {snapshot} does not exist.\n"
                "  An absent corpus directory would make every probe pass vacuously.\n"
                "  Pass a real path, or run `make fetch-corpus` and drop the override."
            )
    else:
        matches = sorted(SNAPSHOT_PARENT.glob(SNAPSHOT_GLOB))
        if not matches:
            raise SystemExit(
                f"ERROR: no {SNAPSHOT_PARENT / SNAPSHOT_GLOB} found.\n"
                "  Run `make fetch-corpus`, or pass --corpus-dir for local dev."
            )
        snapshot = matches[-1]

    if not any(snapshot.iterdir()):
        raise SystemExit(
            f"ERROR: corpus snapshot {snapshot} is empty.\n"
            "  An empty corpus directory produces a FALSE GREEN: every probe finds\n"
            "  nothing and the gate reports success. Refusing to run."
        )
    return snapshot


def read_manifest(snapshot: Path) -> CorpusManifest:
    """Load and validate MANIFEST.json from a snapshot root."""
    path = snapshot / MANIFEST_NAME
    if not path.is_file():
        raise SystemExit(
            f"ERROR: {path} not found.\n"
            "  A snapshot without a manifest has no recorded provenance: nothing\n"
            "  says which corpus commit it holds. Re-run `make fetch-corpus`."
        )
    return CorpusManifest.model_validate(json.loads(path.read_text()))
