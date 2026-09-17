"""Chunker — splits a RawDocument into embeddable chunks. Implements ADR-007.

The binding constraint is the embedding window: `bge-small-en-v1.5`, and every
ADR-004 candidate, accepts 512 tokens and `sentence-transformers` truncates
silently past that. A 2000-token ADR stored whole would be embedded from its
first quarter, the citation and the text sent to Claude would both be complete,
and nothing would report it. So bodies target 480 tokens and the assembled chunk
is asserted against 512.

Token counting is injected rather than imported. Tests pass a deterministic
counter; the dry run passes a real tokenizer. A word-count proxy is never
acceptable here — ADR-007's assertion is denominated in tokens, and words are not
tokens.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from data_platform_rag.contracts import ADRStatus, Chunk, ChunkMetadata, Collection

from .loader import RawDocument

BODY_BUDGET_TOKENS = 480
HARD_LIMIT_TOKENS = 512

TokenCounter = Callable[[str], int]

_FENCE = re.compile(r"^\s*(```|~~~)")
_H1 = re.compile(r"^#\s+(.*\S)\s*$")
_ADR_ID = re.compile(r"ADR[-\s]?(\d+)", re.IGNORECASE)
_STATUS_LINE = re.compile(r"^\*\*Status\*\*:\s*(.+?)\s*$", re.IGNORECASE)
_DATE_LINE = re.compile(r"^\*\*Date\*\*:\s*(.+?)\s*$", re.IGNORECASE)

_STATUS_WORDS: dict[str, ADRStatus] = {
    "accepted": "accepted",
    "superseded": "superseded",
    "resolved": "resolved",
    "planned": "planned",
}


class OversizeAtomicBlock(RuntimeError):
    """An atomic block exceeds the budget on its own — ADR-007 rule 4.

    Raised, never worked around. Resolution is a human decision: reformat the
    source, or record an explicit exception in ADR-007. Truncating silently is
    the failure this whole rule exists to prevent.
    """


@dataclass(frozen=True)
class _Unit:
    """One candidate chunk body, with the deepest heading that produced it."""

    anchor: str | None
    body: str


def _split_on_headings(text: str, level: int) -> list[_Unit]:
    """Split markdown at `#` * level, ignoring headings inside fenced blocks.

    Fence awareness is load-bearing: both corpus READMEs contain fenced blocks
    holding lines that start with `##`, and splitting on those would cut a code
    block in half — which ADR-007 rule 3 forbids.
    """
    marker = "#" * level + " "
    units: list[_Unit] = []
    anchor: str | None = None
    buffer: list[str] = []
    in_fence = False

    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        if not in_fence and line.startswith(marker):
            if buffer and "".join(buffer).strip():
                units.append(_Unit(anchor, "\n".join(buffer).strip()))
            anchor = line[len(marker) :].strip()
            buffer = [line]
            continue
        buffer.append(line)

    if buffer and "".join(buffer).strip():
        units.append(_Unit(anchor, "\n".join(buffer).strip()))
    return units


def _split_paragraphs(unit: _Unit) -> list[_Unit]:
    """Blank-line split that keeps fenced blocks and tables whole."""
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False

    for line in unit.body.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            current.append(line)
            continue
        if not in_fence and not line.strip():
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())

    return [_Unit(unit.anchor, b) for b in blocks if b]


def _is_atomic(body: str) -> bool:
    """A fenced code block or a markdown table cannot be split further.

    Heading lines are ignored before the test. A section body always opens with
    its own `## …` line, so testing the literal first line would classify a
    section that is nothing but one giant code block as non-atomic, and the run
    would report "no split boundary" instead of naming the block that ADR-007
    rule 4 requires a human to look at.
    """
    lines = [ln for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return False
    if _FENCE.match(lines[0]):
        return True
    return sum(1 for ln in lines if ln.lstrip().startswith("|")) >= len(lines) / 2


def _has_content(body: str) -> bool:
    """True if the body holds anything beyond heading lines."""
    return any(ln.strip() and not ln.lstrip().startswith("#") for ln in body.splitlines())


def _pop_lead(units: list[_Unit]) -> tuple[_Unit | None, list[_Unit]]:
    """Separate the block before the first heading from the sections proper.

    `_split_on_headings` yields whatever precedes the first heading as an
    anchor-less unit. For an ADR that block is the title, status and date, which
    every sub-chunk already carries as its preamble — emitting it again would
    duplicate it as a content-free chunk. For a README it is the title and any
    badges.
    """
    if units and units[0].anchor is None:
        return units[0], units[1:]
    return None, units


def _split_yaml_keys(unit: _Unit) -> list[_Unit]:
    """Split a YAML document at its top-level keys, per ADR-007's oversize note.

    A top-level key is an unindented, non-comment line; everything indented under
    it belongs to it. `contract` files are meant to be one chunk each, and all but
    one are — this is the escape hatch the ADR already specifies for the one that
    is not.
    """
    blocks: list[tuple[str | None, list[str]]] = []
    for line in unit.body.splitlines():
        starts_key = line[:1].isalpha() and ":" in line
        if starts_key or not blocks:
            blocks.append((line.split(":", 1)[0].strip() if starts_key else None, [line]))
        else:
            blocks[-1][1].append(line)
    return [_Unit(key, "\n".join(body).strip()) for key, body in blocks if "".join(body).strip()]


def _split_sql_statements(unit: _Unit) -> list[_Unit]:
    """Split SQL at statement boundaries, per ADR-007's oversize note for macros."""
    statements: list[str] = []
    current: list[str] = []
    for line in unit.body.splitlines():
        current.append(line)
        if line.rstrip().endswith(";"):
            statements.append("\n".join(current).strip())
            current = []
    if current and "\n".join(current).strip():
        statements.append("\n".join(current).strip())
    return [_Unit(unit.anchor, s) for s in statements if s]


def _budget(preamble: str, count: TokenCounter) -> int:
    """Tokens left for a body once its preamble is accounted for.

    ADR-007 estimates the preamble at 25-30 tokens and sets the body budget at
    480, which assumes 512 - 480 = 32 is always enough. It is not: the databricks
    ADR 007 preamble is long enough that a 480-token body assembles to 514. The
    ADR's own answer is that the assertion, not the estimate, is the guarantee —
    so the body budget shrinks to whatever room the real preamble leaves.
    """
    if not preamble:
        return BODY_BUDGET_TOKENS
    # +2 for the blank line joining preamble and body.
    return min(BODY_BUDGET_TOKENS, HARD_LIMIT_TOKENS - count(preamble) - 2)


def _fit(
    units: list[_Unit],
    count: TokenCounter,
    source_path: str,
    budget: int = BODY_BUDGET_TOKENS,
    extra: Callable[[_Unit], list[_Unit]] | None = None,
) -> list[_Unit]:
    """Descend the ADR-007 rule-3 hierarchy until every body is within budget.

    `budget` is passed rather than read from the constant because the assembled
    chunk — preamble included — must fit 512, and a document with a long preamble
    has less than 480 tokens of room for its body. ADR-007 sets 480 as headroom
    "for the preamble", and leaves the assertion as the real guarantee; computing
    the room that is actually left is what honours both.
    """
    out: list[_Unit] = []
    for unit in units:
        if count(unit.body) <= budget:
            out.append(unit)
            continue

        deeper = _split_on_headings(unit.body, 3)
        if len(deeper) > 1:
            # The block before the first `###` is the parent section's own lead.
            # It keeps the parent's anchor rather than becoming anchor-less, and
            # is dropped when it is nothing but the parent heading line.
            if deeper[0].anchor is None:
                lead = _Unit(unit.anchor, deeper[0].body)
                deeper = ([lead] if _has_content(lead.body) else []) + deeper[1:]
            out.extend(_fit(deeper, count, source_path, budget, extra))
            continue

        # The type-specific boundary comes before the generic one: ADR-007 names
        # top-level YAML keys and SQL statements explicitly, and splitting on
        # blank lines first would discard those anchors and report a failure
        # against `<document root>` instead of naming the key that overflowed.
        if extra is not None and len(pieces := extra(unit)) > 1:
            out.extend(_fit(pieces, count, source_path, budget, extra))
            continue

        paragraphs = _split_paragraphs(unit)
        if len(paragraphs) > 1:
            out.extend(_fit(paragraphs, count, source_path, budget, extra))
            continue

        # Nothing left to split on.
        if _is_atomic(unit.body):
            raise OversizeAtomicBlock(
                f"{source_path}: an atomic block is {count(unit.body)} tokens, over the "
                f"{budget}-token budget, and cannot be split without "
                f"corrupting it (ADR-007 rule 4).\n"
                f"  Anchor: {unit.anchor or '<document root>'}\n"
                f"  First line: {unit.body.splitlines()[0][:90]}\n"
                f"  Resolution is a human decision: reformat the source, or record an "
                f"explicit exception in ADR-007. Never truncated, never split mid-block."
            )
        raise OversizeAtomicBlock(
            f"{source_path}: a {count(unit.body)}-token block under "
            f"{unit.anchor or '<document root>'} exceeds the {budget}-token "
            f"budget and has no further split boundary (ADR-007 rule 3 exhausted)."
        )
    return out


def _adr_header(content: str, source_path: str) -> tuple[str | None, ADRStatus | None, str]:
    """Extract (adr_id, normalized status, preamble) from an ADR document.

    The verbatim status line is kept in the preamble, not just its normalized
    form: corpus statuses are free prose ("Accepted **with partial reversion
    2026-07-02**"), and a mid-document chunk retrieved without that qualifier is
    exactly how a superseded decision gets cited as current.
    """
    title = source_path
    status_line = date_line = None
    for line in content.splitlines()[:20]:
        if (m := _H1.match(line)) and title == source_path:
            title = m.group(1)
        elif m := _STATUS_LINE.match(line):
            status_line = m.group(1)
        elif m := _DATE_LINE.match(line):
            date_line = m.group(1)

    adr_id = f"ADR-{m.group(1)}" if (m := _ADR_ID.search(title)) else None

    status: ADRStatus | None = None
    if status_line:
        first = re.sub(r"[^a-z]", "", status_line.split()[0].lower())
        status = _STATUS_WORDS.get(first)

    preamble = f"# {title}"
    if status_line:
        preamble += f"\n**Status**: {status_line}"
    if date_line:
        preamble += f"\n**Date**: {date_line}"
    return adr_id, status, preamble


def _collection_for(source_type: str) -> Collection:
    """ADR-002 defines this by source kind: ADRs are decisions, the rest is not."""
    return "decisions" if source_type == "adr" else "architecture"


def chunk_document(doc: RawDocument, count_tokens: TokenCounter) -> list[Chunk]:
    """Apply the ADR-007 strategy for `doc.source_type`.

    Deterministic: the same input file yields the same `chunk_index` values on
    every run, which `UNIQUE (source_project, source_path, chunk_index)` requires.
    """
    adr_id: str | None = None
    status: ADRStatus | None = None
    preamble = ""

    if doc.source_type == "adr":
        adr_id, status, preamble = _adr_header(doc.content, doc.source_path)
        if count_tokens(doc.content) <= BODY_BUDGET_TOKENS:
            units = [_Unit(None, doc.content.strip())]
            preamble = ""  # whole document already carries its own header
        else:
            _, sections = _pop_lead(_split_on_headings(doc.content, 2))
            units = _fit(sections, count_tokens, doc.source_path, _budget(preamble, count_tokens))
    elif doc.source_type == "readme":
        lead, sections = _pop_lead(_split_on_headings(doc.content, 2))
        if lead is not None:
            # The repo title, so a section retrieved alone says which project it
            # came from — the two READMEs describe different platforms and their
            # section names overlap ("Stack", "Architecture", "The Problem").
            first = lead.body.splitlines()[0].strip()
            preamble = first if first.startswith("# ") else ""
            remainder = "\n".join(lead.body.splitlines()[1:]).strip()
            if count_tokens(remainder) > 5:
                sections.insert(0, _Unit(None, remainder))
        units = _fit(sections, count_tokens, doc.source_path, _budget(preamble, count_tokens))
    else:
        # contract, macro: one unit per file, still subject to the oversize rule.
        # ADR-007 names the fallback boundary for each when the rule does fire.
        extra = _split_yaml_keys if doc.source_type == "contract" else _split_sql_statements
        units = _fit(
            [_Unit(None, doc.content.strip())], count_tokens, doc.source_path, extra=extra
        )

    chunks: list[Chunk] = []
    for index, unit in enumerate(units):
        content = f"{preamble}\n\n{unit.body}" if preamble else unit.body
        assembled = count_tokens(content)
        if assembled > HARD_LIMIT_TOKENS:
            raise OversizeAtomicBlock(
                f"{doc.source_path}: assembled chunk {index} is {assembled} tokens, over "
                f"the hard {HARD_LIMIT_TOKENS}-token embedding window. The body fit the "
                f"{BODY_BUDGET_TOKENS}-token budget, so the preamble headroom is "
                f"insufficient for this document (ADR-007 oversize rule)."
            )
        chunks.append(
            Chunk(
                content=content,
                collection=_collection_for(doc.source_type),
                metadata=ChunkMetadata(
                    source_project=doc.source_project,
                    source_type=doc.source_type,
                    source_path=doc.source_path,
                    source_anchor=unit.anchor,
                    adr_id=adr_id,
                    status=status,
                    chunk_index=index,
                    token_count=assembled,
                ),
            )
        )
    return chunks
