"""Corpus loader — reads a snapshot and yields raw source materials.

Sources:
- sdd-kafka-snowflake-2 → 12 ADRs + README + 3 dbt macros
- sdd-kafka-databricks → 9 ADRs + README + 21 YAML contracts

It does not clone: `make fetch-corpus` produces the snapshot, this reads it
(ADR-012). Nor does it decide what is in corpus — that set is owned by
`indexer/corpus.py` and imported. A loader with its own path list would be the
fourth declaration of a set that already disagreed with itself in three places.

This repo is NOT a corpus source. Self-indexing was explicitly rejected
(AGENTS.md boundary; PRE_BUILD_VALIDATION.md Section 2).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from data_platform_rag.contracts import Collection, SourceProject, SourceType

from .corpus import classified_files, corpus_projects


@dataclass(frozen=True)
class RawDocument:
    """A source document before chunking."""

    source_project: SourceProject
    source_type: SourceType
    source_path: str  # e.g. docs/adr/ADR-0019.md
    content: str
    collection: Collection


def load_corpus(snapshot_dir: Path) -> Iterator[RawDocument]:
    """Yield one RawDocument per in-corpus file in the snapshot.

    Order is deterministic — projects sorted, then files sorted within each —
    so two runs over the same snapshot produce the same sequence, which
    `chunk_index` determinism depends on.
    """
    for project in corpus_projects():
        project_root = snapshot_dir / project
        if not project_root.is_dir():
            raise FileNotFoundError(
                f"corpus project {project!r} not found under {snapshot_dir}. "
                f"Run `make fetch-corpus`."
            )
        for path, source_type in classified_files(project_root, project):
            yield RawDocument(
                source_project=project,
                source_type=source_type,
                source_path=str(path.relative_to(project_root)),
                content=path.read_text(encoding="utf-8", errors="replace"),
                collection="decisions" if source_type == "adr" else "architecture",
            )
