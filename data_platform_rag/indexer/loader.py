"""Corpus loader — clones target repos and yields raw source materials.

Sources (as of ADR-001):
- sdd-kafka-snowflake-2 → 12 ADRs + README + macros
- sdd-kafka-databricks → 9 ADRs + README + 21 YAML contracts
- data-platform-rag (self) → this project's docs/adr/
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal

SourceType = Literal["adr", "readme", "contract", "macro", "schema"]
# Collection type alias lives in data_platform_rag.contracts (per ADR-010)


@dataclass(frozen=True)
class RawDocument:
    """A source document before chunking."""

    source_project: str
    source_type: SourceType
    source_path: str  # e.g. docs/adr/ADR-0019.md
    content: str
    collection: Collection


def load_corpus(clone_dir: Path) -> Iterator[RawDocument]:
    """Walk the clone directory, yield RawDocument per source file.

    TODO(BUILD): Implement traversal rules per source_project.
    """
    raise NotImplementedError("Implement in BUILD phase for feature: corpus-indexing")
