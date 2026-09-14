"""Corpus loader — clones target repos and yields raw source materials.

Sources (as of ADR-001):
- sdd-kafka-snowflake-2 → 12 ADRs + README + macros
- sdd-kafka-databricks → 9 ADRs + README + 21 YAML contracts

This repo is NOT a corpus source. Self-indexing was explicitly rejected
(AGENTS.md boundary; PRE_BUILD_VALIDATION.md Section 2).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from data_platform_rag.contracts import Collection, SourceProject, SourceType


@dataclass(frozen=True)
class RawDocument:
    """A source document before chunking."""

    source_project: SourceProject
    source_type: SourceType
    source_path: str  # e.g. docs/adr/ADR-0019.md
    content: str
    collection: Collection


def load_corpus(clone_dir: Path) -> Iterator[RawDocument]:
    """Walk the clone directory, yield RawDocument per source file.

    TODO(BUILD): Implement traversal rules per source_project.
    """
    raise NotImplementedError("Implement in BUILD phase for feature: corpus-indexing")
