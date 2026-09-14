"""Chunker — splits RawDocument into embeddable chunks per strategy.

Strategy per source_type (per ADR-007, planned):
- adr: full document as one chunk (usually <2000 tokens, coherent decision unit)
- readme: split by top-level heading (## sections)
- contract: whole YAML as one chunk
- macro: whole SQL file as one chunk
"""

from __future__ import annotations

from dataclasses import dataclass

from .loader import RawDocument


@dataclass(frozen=True)
class Chunk:
    """A chunk ready for embedding + storage."""

    source_project: str
    source_type: str
    source_path: str
    source_anchor: str | None
    content: str
    chunk_index: int
    token_count: int
    adr_id: str | None
    topic: str | None
    status: str | None
    collection: str


def chunk_document(doc: RawDocument) -> list[Chunk]:
    """Apply the chunking strategy appropriate to doc.source_type.

    TODO(BUILD): Implement per ADR-007 (chunking strategy per source type).
    """
    raise NotImplementedError("Implement in BUILD phase for feature: chunking-strategies")
