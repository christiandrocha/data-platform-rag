"""Index the corpus into pgvector.

Slice 1 implements `--dry-run` only: read the snapshot, check it against the
inventory, chunk it per ADR-007, and report the token distribution. Nothing is
embedded and nothing is written.

The dry run exists because ADR-007's 480-token budget may not hold for this
corpus, and finding that out costs far less before an embedder and a writer are
built on top of it. Ten of the 21 corpus ADRs exceed 480 whitespace-separated
words. Whether any atomic block exceeds 480 *tokens* is what this measures.

Embedding and upsert are slice 2 (DESIGN.md of feature: corpus-indexing).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from data_platform_rag.config import Settings, get_settings
from data_platform_rag.contracts import CorpusManifest
from data_platform_rag.indexer.chunker import (
    BODY_BUDGET_TOKENS,
    HARD_LIMIT_TOKENS,
    OversizeAtomicBlock,
    chunk_document,
)
from data_platform_rag.indexer.corpus import read_manifest, resolve_snapshot
from data_platform_rag.indexer.loader import load_corpus
from data_platform_rag.indexer.tokenizer import get_token_counter

INVENTORY = Path("docs/golden-set/corpus_inventory.yml")
_NON_PROJECT_KEYS = {"seed", "verified_against_clone"}


def check_inventory(manifest: CorpusManifest) -> list[str]:
    """Set difference between the snapshot's ADRs and the hand-kept inventory.

    ADR-011 Consequences assigns this check to this feature's BUILD. The
    inventory is hand-maintained and the corpora are live repos, so it goes stale
    silently — and a stale inventory means golden-set coverage is measured
    against the wrong denominator.

    Reported in both directions: an ADR in the corpus but not the inventory is an
    uncovered unit nobody knows about; one in the inventory but not the corpus is
    a question anchored to a file that no longer exists (dev-log #19).
    """
    inventory = yaml.safe_load(INVENTORY.read_text())
    problems: list[str] = []

    for project in manifest.projects:
        declared = set(inventory.get(project.project, {}).get("adrs", []))
        present = {f.path for f in project.files if f.source_type == "adr"}
        for missing in sorted(present - declared):
            problems.append(f"{project.project}: {missing} is in the corpus, not the inventory")
        for stale in sorted(declared - present):
            problems.append(f"{project.project}: {stale} is in the inventory, not the corpus")

    known = set(inventory) - _NON_PROJECT_KEYS
    for extra in sorted(known - {p.project for p in manifest.projects}):
        problems.append(f"{extra}: in the inventory, absent from the snapshot")
    return problems


def embedding_model_name() -> str:
    """The configured embedding model, without requiring secrets to read it."""
    try:
        return get_settings().embedding_model
    except Exception:
        return Settings.model_fields["embedding_model"].default


def dry_run(snapshot: Path, model_name: str) -> int:
    manifest = read_manifest(snapshot)
    print(f"Snapshot {snapshot}")
    for project in manifest.projects:
        print(f"  {project.project}  {project.commit_sha[:8]}  {len(project.files)} files")

    problems = check_inventory(manifest)
    if problems:
        print(f"\n✗ inventory drift, {len(problems)} difference(s):")
        for problem in problems:
            print(f"    {problem}")
    else:
        print("\n✓ inventory matches the snapshot")

    count = get_token_counter(model_name)
    print(f"\nChunking per ADR-007, counting with {model_name}")

    total_units = 0
    over_budget: list[tuple[str, str | None, int]] = []
    failures: list[str] = []
    largest: list[tuple[int, str, str | None]] = []

    for doc in load_corpus(snapshot):
        try:
            chunks = chunk_document(doc, count)
        except OversizeAtomicBlock as exc:
            failures.append(f"{doc.source_project}/{exc}")
            continue
        total_units += len(chunks)
        for chunk in chunks:
            tokens = chunk.metadata.token_count
            anchor = chunk.metadata.source_anchor
            largest.append((tokens, f"{doc.source_project}/{doc.source_path}", anchor))
            if tokens > BODY_BUDGET_TOKENS:
                over_budget.append((f"{doc.source_project}/{doc.source_path}", anchor, tokens))

    # Explicit key: an anchor may be None, and two split halves of one table tie
    # on both token count and path, so the default tuple compare reaches it.
    largest.sort(key=lambda row: (-row[0], row[1], row[2] or ""))
    print(f"\n{total_units} chunk(s) from {len(manifest.projects)} project(s)")
    print(f"\nLargest 10 assembled chunks (hard limit {HARD_LIMIT_TOKENS}):")
    for tokens, path, anchor in largest[:10]:
        print(f"  {tokens:>4}  {path}  [{anchor or '—'}]")

    if over_budget:
        print(
            f"\n{len(over_budget)} assembled chunk(s) over the "
            f"{BODY_BUDGET_TOKENS}-token body budget but within {HARD_LIMIT_TOKENS} "
            f"(preamble headroom, expected):"
        )
        for path, anchor, tokens in over_budget:
            print(f"  {tokens:>4}  {path}  [{anchor or '—'}]")

    if failures:
        print(f"\n✗ ADR-007 rule 4 fired on {len(failures)} document(s):\n")
        for failure in failures:
            print(f"{failure}\n")
        print(
            "Resolution is a human decision, not code: reformat the source, or record\n"
            "an explicit exception in ADR-007. The feature pauses here by design."
        )
        return 1

    if problems:
        print("\nInventory drift above is blocking: coverage is measured against it.")
        return 1

    print("\n✓ dry run clean — every chunk fits the window. Nothing was written.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chunk and report token counts. Write nothing. The only mode in slice 1.",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help="Snapshot root. Defaults to the newest /tmp/dpr-corpus-* (canonical).",
    )
    parser.add_argument(
        "--tokenizer",
        default=None,
        help="Override the tokenizer. Defaults to the configured embedding model.",
    )
    args = parser.parse_args()

    if not args.dry_run:
        print(
            "scripts/index_corpus.py: embedding and upsert are slice 2, not yet built.\n"
            "  Run `make index-corpus-dry` to chunk the snapshot and report token counts.\n"
            "  See .claude/sdd/features/corpus-indexing/DESIGN.md."
        )
        return 1

    return dry_run(resolve_snapshot(args.corpus_dir), args.tokenizer or embedding_model_name())


if __name__ == "__main__":
    sys.exit(main())
