"""Ask the corpus a question and print what retrieval returns. No LLM involved.

A development instrument, not a product surface. It exists because the curator
has 45 golden-set questions left to write and no way to check whether a question
retrieves the ADR it was anchored to -- the feedback loop this feature is for.

By default the RRF candidates are reranked (ADR-005) and the first
`settings.rerank_top_k` are shown: what generation will receive. `--no-rerank`
shows the RRF list itself, which answers "was the right chunk a candidate at all".

One line per chunk: rank, the scores, and the citation with its section anchor.
`--full` adds the chunk text, which answers "why did this rank".
"""

from __future__ import annotations

import argparse
import sys

from data_platform_rag.contracts import Collection, RerankedChunk, RetrievedChunk
from data_platform_rag.retrieval.pipeline import retrieve, retrieve_and_rerank

PREVIEW_CHARS = 96


def _score(value: float | None, rank: int | None, fmt: str) -> str:
    """A score is only shown when its side actually ranked the chunk.

    An em dash means "this side did not rank it", which a 0.0 would disguise as
    "this side scored it zero". The two are different: a chunk can carry a real
    sparse score and still fall outside the sparse top-k.
    """
    if rank is None:
        return "     —"
    return format(value, fmt)


def render(chunks: list[RetrievedChunk], *, full: bool) -> str:
    if not chunks:
        return "no chunks retrieved."

    # A rerank score is not on a common scale across models (logits for
    # MiniLM-L-6, a sigmoid for bge-reranker-base), so it is printed, never judged.
    reranked = isinstance(chunks[0], RerankedChunk)
    rerank_head = f"{'rerank':>9}  " if reranked else ""
    lines = [f"{'#':>2}  {rerank_head}{'rrf':>7}  {'dense':>6}  {'sparse':>6}  source"]
    for position, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        anchor = meta.source_anchor or "—"
        rerank_col = ""
        if isinstance(chunk, RerankedChunk):
            marker = "*" if chunk.truncated else " "
            rerank_col = f"{chunk.rerank_score:>8.4f}{marker}  "
        lines.append(
            f"{position:>2}  {rerank_col}{chunk.rrf_score:>7.5f}  "
            f"{_score(chunk.dense_distance, chunk.dense_rank, '>6.3f')}  "
            f"{_score(chunk.sparse_score, chunk.sparse_rank, '>6.4f')}  "
            f"{meta.source_project}/{meta.source_path} [{anchor}]"
        )
        if full:
            lines.append("")
            lines.append("      " + chunk.content.replace("\n", "\n      "))
            lines.append("")
        elif chunk.content:
            preview = " ".join(chunk.content.split())[:PREVIEW_CHARS]
            lines.append(f"      {preview}…")
    if reranked and any(c.truncated for c in chunks):
        lines.append(
            "\n  * scored on a truncated (question, chunk) pair — the chunk's tail was not read"
        )
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
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Size of the RRF list shown with --no-rerank. Default: settings.hybrid_top_k",
    )
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="Show the RRF candidates instead of the reranked top (ADR-005).",
    )
    parser.add_argument("--full", action="store_true", help="Print whole chunk text.")
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        parser.error('a question is required, e.g. make ask q="why Snowpipe Streaming?"')

    collections: list[Collection] | None = None
    if args.collections:
        collections = [c.strip() for c in args.collections.split(",") if c.strip()]  # type: ignore[misc]

    if args.top_k is not None and not args.no_rerank:
        parser.error("--top-k sizes the RRF list; use it with --no-rerank")

    try:
        if args.no_rerank:
            chunks = retrieve(question, collections=collections, top_k=args.top_k)
        else:
            chunks = retrieve_and_rerank(question, collections=collections)
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
