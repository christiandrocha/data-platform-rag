"""ADR-007 chunking, against hand-written fixtures rather than corpus files.

Token counting is injected, so these tests are deterministic and need no model
download. `words` stands in for a tokenizer: the real budget is in tokens, and
the production path never substitutes a word count — but a fixture only needs a
counter that is monotonic and predictable.
"""

from __future__ import annotations

import pytest

from data_platform_rag.indexer.chunker import (
    BODY_BUDGET_TOKENS,
    OversizeAtomicBlock,
    chunk_document,
)
from data_platform_rag.indexer.loader import RawDocument


def words(text: str) -> int:
    return len(text.split())


def doc(content: str, source_type="adr", path="docs/adr/0019_x.md") -> RawDocument:
    return RawDocument(
        source_project="sdd-kafka-snowflake-2",
        source_type=source_type,
        source_path=path,
        content=content,
        collection="decisions" if source_type == "adr" else "architecture",
    )


def filler(n: int) -> str:
    return " ".join(["word"] * n)


def test_small_adr_is_one_chunk():
    chunks = chunk_document(doc("# ADR 0019 — Gate\n\n**Status**: Accepted\n\nShort.\n"), words)
    assert len(chunks) == 1
    assert chunks[0].metadata.chunk_index == 0
    assert chunks[0].metadata.source_anchor is None
    assert chunks[0].collection == "decisions"


def test_adr_metadata_is_extracted():
    chunks = chunk_document(
        doc("# ADR 0019 — The gate\n\n**Status**: Accepted\n**Date**: 2026-01-01\n\nBody.\n"),
        words,
    )
    assert chunks[0].metadata.adr_id == "ADR-0019"
    assert chunks[0].metadata.status == "accepted"


def test_free_prose_status_normalizes_to_its_first_word():
    """Corpus statuses are prose: "Accepted **with partial reversion 2026-07-02**"."""
    chunks = chunk_document(
        doc("# ADR 009 — x\n\n**Status**: Accepted **with partial reversion**\n\nBody.\n"),
        words,
    )
    assert chunks[0].metadata.status == "accepted"


def test_oversize_adr_splits_by_heading_and_every_chunk_carries_the_preamble():
    content = (
        "# ADR 0019 — The gate\n\n**Status**: Superseded\n**Date**: 2026-01-01\n\n"
        f"## Context\n{filler(400)}\n\n## Decision\n{filler(400)}\n"
    )
    chunks = chunk_document(doc(content), words)
    assert len(chunks) >= 2
    assert [c.metadata.chunk_index for c in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        # Status in every sub-chunk: a mid-document chunk retrieved without it is
        # how a superseded decision gets cited as current (ADR-007 rule 2).
        assert "**Status**: Superseded" in chunk.content
        assert chunk.metadata.status == "superseded"
    assert {c.metadata.source_anchor for c in chunks} == {"Context", "Decision"}


def test_split_descends_to_sub_headings_when_a_section_is_still_too_big():
    content = (
        "# ADR 0019 — x\n\n**Status**: Accepted\n\n"
        f"## Context\n### First\n{filler(400)}\n\n### Second\n{filler(400)}\n"
    )
    anchors = {c.metadata.source_anchor for c in chunk_document(doc(content), words)}
    assert anchors == {"First", "Second"}


def test_split_descends_to_paragraphs_as_the_last_level():
    body = "\n\n".join(filler(300) for _ in range(3))
    content = f"# ADR 0019 — x\n\n**Status**: Accepted\n\n## Context\n{body}\n"
    assert len(chunk_document(doc(content), words)) == 3


def test_headings_inside_fenced_blocks_do_not_split():
    """Both corpus READMEs contain fences holding lines that start with `##`."""
    content = "# R\n\n## Usage\n```bash\n## not a heading\necho hi\n```\n\n## Other\ntext\n"
    chunks = chunk_document(doc(content, source_type="readme", path="README.md"), words)
    assert {c.metadata.source_anchor for c in chunks} == {"Usage", "Other"}
    usage = next(c for c in chunks if c.metadata.source_anchor == "Usage")
    assert "## not a heading" in usage.content


def test_an_oversize_atomic_block_fails_loudly_and_names_the_file():
    content = (
        "# ADR 0019 — x\n\n**Status**: Accepted\n\n"
        f"## Context\n```sql\n{filler(600)}\n```\n"
    )
    with pytest.raises(OversizeAtomicBlock) as excinfo:
        chunk_document(doc(content), words)
    assert "docs/adr/0019_x.md" in str(excinfo.value)
    assert "rule 4" in str(excinfo.value)


def test_readme_splits_by_section_with_ordinal_indexes():
    content = "# R\n\n## One\nalpha\n\n## Two\nbeta\n\n## Three\ngamma\n"
    chunks = chunk_document(doc(content, source_type="readme", path="README.md"), words)
    assert [c.metadata.chunk_index for c in chunks] == [0, 1, 2]
    assert [c.metadata.source_anchor for c in chunks] == ["One", "Two", "Three"]
    assert all(c.collection == "architecture" for c in chunks)


@pytest.mark.parametrize(
    "source_type,path",
    [("contract", "contracts/orders.yml"), ("macro", "dbt/macros/x.sql")],
)
def test_contracts_and_macros_are_one_chunk(source_type, path):
    chunks = chunk_document(doc("table: orders\nkey: id\n", source_type, path), words)
    assert len(chunks) == 1
    assert chunks[0].metadata.chunk_index == 0
    assert chunks[0].metadata.adr_id is None


def test_chunking_is_deterministic_across_runs():
    content = (
        f"# ADR 0019 — x\n\n**Status**: Accepted\n\n"
        f"## A\n{filler(400)}\n\n## B\n{filler(400)}\n"
    )
    first = chunk_document(doc(content), words)
    second = chunk_document(doc(content), words)
    assert [c.metadata.chunk_index for c in first] == [c.metadata.chunk_index for c in second]
    assert [c.content for c in first] == [c.content for c in second]


def test_token_count_records_the_assembled_chunk():
    chunks = chunk_document(doc("# ADR 0019 — x\n\n**Status**: Accepted\n\nBody here.\n"), words)
    assert chunks[0].metadata.token_count == words(chunks[0].content)


def test_a_body_within_budget_is_never_split():
    content = (
        f"# ADR 0019 — x\n\n**Status**: Accepted\n\n"
        f"## Only\n{filler(BODY_BUDGET_TOKENS - 20)}\n"
    )
    assert len(chunk_document(doc(content), words)) == 1


# ─── Amendment 1 (2026-09-17) ────────────────────────────────────────────────


def test_a_table_is_split_at_a_row_boundary_with_the_header_repeated():
    """Amendment 1A: a table is not atomic — halves stay valid tables."""
    rows = "\n".join(f"| {filler(60)} | b | c |" for _ in range(10))
    content = f"# R\n\n## Stack\n| Layer | Tech | Decision |\n|---|---|---|\n{rows}\n"
    chunks = chunk_document(doc(content, source_type="readme", path="README.md"), words)
    assert len(chunks) > 1
    for chunk in chunks:
        assert "| Layer | Tech | Decision |" in chunk.content
        assert "|---|---|---|" in chunk.content


def test_a_fenced_block_is_still_atomic():
    """Amendment 1A narrows rule 4 to fences — it does not remove it."""
    content = f"# ADR 0019 — x\n\n**Status**: Accepted\n\n## C\n```sql\n{filler(600)}\n```\n"
    with pytest.raises(OversizeAtomicBlock, match="rule 4"):
        chunk_document(doc(content), words)


def test_an_oversize_contract_key_splits_at_list_items_with_a_table_preamble():
    """Amendment 1B: a half-schema chunk still names its table and merge key."""
    items = "\n".join(f"  - {{ name: col_{i}, {filler(20)} }}" for i in range(20))
    content = f"table:\n  name: payments\n  merge_key: payment_id\n\nschema:\n{items}\n"
    chunks = chunk_document(doc(content, source_type="contract", path="contracts/p.yml"), words)
    assert len(chunks) > 1
    for chunk in chunks:
        assert "name: payments" in chunk.content
        assert "merge_key: payment_id" in chunk.content


def test_a_contract_within_budget_keeps_one_chunk_and_no_preamble():
    chunks = chunk_document(
        doc("table:\n  name: orders\n\nschema:\n  - { name: id }\n", "contract", "contracts/o.yml"),
        words,
    )
    assert len(chunks) == 1
    assert chunks[0].content.count("name: orders") == 1


def test_adjacent_paragraphs_are_packed_back_up_to_the_budget():
    """Amendment 1D: splitting without packing gave 87 chunks under 100 tokens."""
    body = "\n\n".join(filler(40) for _ in range(20))
    content = f"# R\n\n## Long\n{body}\n"
    chunks = chunk_document(doc(content, source_type="readme", path="README.md"), words)
    assert len(chunks) < 5
    assert all(c.metadata.token_count > 100 for c in chunks[:-1])


def test_packing_never_merges_across_an_anchor_change():
    content = "# R\n\n## One\nalpha\n\n## Two\nbeta\n"
    chunks = chunk_document(doc(content, source_type="readme", path="README.md"), words)
    assert [c.metadata.source_anchor for c in chunks] == ["One", "Two"]
