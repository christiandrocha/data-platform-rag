"""Ask the corpus a question and print what retrieval returns. No LLM involved.

A development instrument, not a product surface. It exists because the curator
has 45 golden-set questions left to write and no way to check whether a question
retrieves the ADR it was anchored to -- the feedback loop this feature is for.

Two views. The default is one line per chunk: rank, the dense distance
and its similarity, and the citation with its section anchor, which
answers "did my anchor come back, and where". `--full` adds the chunk text,
which answers "why did this rank".
"""

from __future__ import annotations

import argparse
import sys

from data_platform_rag.contracts import Collection, RetrievedChunk
from data_platform_rag.retrieval.pipeline import retrieve

PREVIEW_CHARS = 96


def render(chunks: list[RetrievedChunk], *, full: bool) -> str:
    if not chunks:
        return "no chunks retrieved."

    # Dense-only (ADR-018). `sim` is 1 - dense distance: the number ADR-019
    # measured and found unable to separate out-of-scope questions.
    lines = [f"{'#':>2}  {'dense':>6}  {'sim':>6}  source"]
    for position, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        anchor = meta.source_anchor or "—"
        lines.append(
            f"{position:>2}  "
            f"{chunk.dense_distance:>6.3f}  "
            f"{1.0 - chunk.dense_distance:>6.3f}  "
            f"{meta.source_project}/{meta.source_path} [{anchor}]"
        )
        if full:
            lines.append("")
            lines.append("      " + chunk.content.replace("\n", "\n      "))
            lines.append("")
        elif chunk.content:
            preview = " ".join(chunk.content.split())[:PREVIEW_CHARS]
            lines.append(f"      {preview}…")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="*", help="The question to ask.")
    parser.add_argument(
        "--collections",
        default=None,
        help=(
            "Comma-separated collections to search. Default: both. "
            "Use this to test whether an intent classifier would earn its keep."
        ),
    )
    parser.add_argument("--top-k", type=int, default=None, help="Default: settings.hybrid_top_k")
    parser.add_argument("--full", action="store_true", help="Print whole chunk text.")
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        parser.error('a question is required, e.g. make ask q="why Snowpipe Streaming?"')

    collections: list[Collection] | None = None
    if args.collections:
        collections = [c.strip() for c in args.collections.split(",") if c.strip()]  # type: ignore[misc]

    try:
        chunks = retrieve(question, collections=collections, top_k=args.top_k)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Q: {question}")
    searched = ", ".join(collections) if collections else "both collections"
    print(f"   ({searched})\n")
    print(render(chunks, full=args.full))
    if not chunks:
        print("\n  Nothing matched. Is the index populated? `make index-corpus`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
