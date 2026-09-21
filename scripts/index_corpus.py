"""Index the corpus into pgvector.

Two modes. `--dry-run` reads the snapshot, checks it against the inventory,
chunks it per ADR-007 and reports the token distribution, writing nothing. The
default mode does the same work and then embeds and writes, replacing one
project scope at a time inside a transaction (ADR-013).

The dry run exists because ADR-007's 480-token budget may not hold for this
corpus, and finding that out costs far less before an embedder and a writer are
built on top of it. Ten of the 21 corpus ADRs exceed 480 whitespace-separated
words. Whether any atomic block exceeds 480 *tokens* is what this measures.

The dry run's numbers are the regression baseline for the real run: the same
chunker produces both, so a row count that disagrees with the dry run means
something between chunking and writing lost or duplicated a chunk.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import yaml

from data_platform_rag.config import Settings, get_settings, get_settings_without_llm
from data_platform_rag.contracts import (
    Chunk,
    CorpusManifest,
    CorpusProject,
    IndexedSnapshot,
    IndexRunReport,
    SourceProject,
)
from data_platform_rag.indexer.chunker import (
    BODY_BUDGET_TOKENS,
    HARD_LIMIT_TOKENS,
    OversizeAtomicBlock,
    chunk_document,
)
from data_platform_rag.indexer.corpus import read_manifest, resolve_snapshot
from data_platform_rag.indexer.embedder import embed_documents
from data_platform_rag.indexer.loader import load_corpus
from data_platform_rag.indexer.tokenizer import get_token_counter
from data_platform_rag.indexer.writer import connect, current_snapshots, write_project

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


def embedding_dim() -> int:
    """The configured embedding dimension, without requiring secrets to read it.

    Same shape as `embedding_model_name` above: the dimension is a property of
    the embedding model, not of any credential.
    """
    try:
        return get_settings_without_llm().embedding_dim
    except Exception:
        return Settings.model_fields["embedding_dim"].default


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


def chunk_by_project(
    snapshot: Path, count: Callable[[str], int]
) -> dict[SourceProject, list[Chunk]]:
    """Chunk the whole snapshot, grouped by project.

    The same `chunk_document` the dry run calls, so the two modes cannot disagree
    about what a chunk is. Grouping by project is what replace-by-scope needs:
    the transaction boundary is one project.

    ADR-007 rule 4 is not caught here. If an atomic block exceeds the budget the
    exception propagates and nothing is written — a corpus that cannot be chunked
    correctly must not be half-indexed.
    """
    by_project: dict[SourceProject, list[Chunk]] = defaultdict(list)
    for doc in load_corpus(snapshot):
        by_project[doc.source_project].extend(chunk_document(doc, count))
    return dict(by_project)


def snapshot_row(
    project: CorpusProject,
    manifest: CorpusManifest,
    model_name: str,
    dim: int,
    chunk_count: int,
) -> IndexedSnapshot:
    """The provenance row for one project, assembled from the manifest."""
    return IndexedSnapshot(
        source_project=project.project,
        repo_url=project.repo_url,
        commit_sha=project.commit_sha,
        file_count=len(project.files),
        manifest_created_at=manifest.created_at,
        manifest_schema_version=manifest.schema_version,
        embedding_model=model_name,
        embedding_dim=dim,
        chunk_count=chunk_count,
    )


def database_dsn() -> str:
    """The configured database URL, or a loud failure.

    Unlike the embedding model, this has no sensible field default to fall back
    on: a wrong database is worse than no database.

    It reads `get_settings_without_llm()` rather than `get_settings()`, so that an
    absent Anthropic key is not reported as an absent database. It was: the
    `except` below caught the ValidationError for `anthropic_api_key` and told
    the reader to set DATABASE_URL, which `ragas.yml` had set correctly all
    along.
    """
    try:
        return str(get_settings_without_llm().database_url)
    except Exception as exc:
        raise SystemExit(
            f"ERROR: DATABASE_URL is not configured, so the corpus cannot be "
            f"written.\n  {exc}\n"
            f"  Copy .env.example to .env, or export DATABASE_URL.\n"
            f"  `make index-corpus-dry` needs no database and still works."
        ) from exc


def report_verify(snapshot: Path, model_name: str) -> int:
    """Compare what is indexed against what the snapshot says. Write nothing.

    This is ADR-012's purpose reaching the database: the manifest names a commit,
    the snapshot rows name a commit, and until this comparison existed nothing
    checked that they were the same commit.
    """
    manifest = read_manifest(snapshot)
    with connect(database_dsn()) as conn:
        indexed = current_snapshots(conn)

    problems: list[str] = []
    for project in manifest.projects:
        current = indexed.get(project.project)
        if current is None:
            problems.append(f"{project.project}: in the snapshot, not indexed")
            continue
        if current.commit_sha != project.commit_sha:
            problems.append(
                f"{project.project}: indexed at {current.commit_sha[:8]}, "
                f"snapshot is {project.commit_sha[:8]}"
            )
        if current.embedding_model != model_name:
            problems.append(
                f"{project.project}: indexed with {current.embedding_model}, "
                f"configured model is {model_name}"
            )

    for extra in sorted(set(indexed) - {p.project for p in manifest.projects}):
        problems.append(f"{extra}: indexed, absent from the snapshot")

    print(f"Snapshot {snapshot}")
    for project in manifest.projects:
        current = indexed.get(project.project)
        state = (
            f"indexed {current.chunk_count} chunk(s) at {current.commit_sha[:8]}"
            if current
            else "not indexed"
        )
        print(f"  {project.project:<24} {state}")

    if problems:
        print(f"\n\u2717 indexed corpus != verified corpus, {len(problems)} difference(s):")
        for problem in problems:
            print(f"    {problem}")
        return 1

    print("\n\u2713 indexed corpus == verified corpus")
    return 0


def index(snapshot: Path, model_name: str, *, force: bool, batch_size: int | None) -> int:
    """Embed the snapshot and write it, one project scope per transaction."""
    started = time.monotonic()
    manifest = read_manifest(snapshot)
    print(f"Snapshot {snapshot}")
    for project in manifest.projects:
        print(f"  {project.project}  {project.commit_sha[:8]}  {len(project.files)} files")

    problems = check_inventory(manifest)
    if problems:
        print(f"\n\u2717 inventory drift, {len(problems)} difference(s):")
        for problem in problems:
            print(f"    {problem}")
        print("\nInventory drift is blocking: coverage is measured against it.")
        return 1
    print("\n\u2713 inventory matches the snapshot")

    dim = embedding_dim()

    count = get_token_counter(model_name)
    print(f"\nChunking per ADR-007, counting with {model_name}")
    try:
        by_project = chunk_by_project(snapshot, count)
    except OversizeAtomicBlock as exc:
        print(f"\n\u2717 ADR-007 rule 4 fired: {exc}")
        print("Resolution is a human decision, not code. Nothing was written.")
        return 1

    written: list[IndexedSnapshot] = []
    skipped: list[SourceProject] = []

    with connect(database_dsn()) as conn:
        indexed = current_snapshots(conn)

        for project in manifest.projects:
            chunks = by_project.get(project.project, [])
            current = indexed.get(project.project)
            if (
                not force
                and current is not None
                and current.is_current_for(project.commit_sha, model_name)
            ):
                skipped.append(project.project)
                print(
                    f"  {project.project:<24} up to date at {project.commit_sha[:8]}, "
                    f"same model \u2014 skipped"
                )
                continue

            row = snapshot_row(project, manifest, model_name, dim, len(chunks))
            print(
                f"  {project.project:<24} {len(chunks)} chunk(s), embedding\u2026",
                end="",
                flush=True,
            )
            vectors = embed_documents([chunk.content for chunk in chunks], batch_size)
            n = write_project(conn, row, chunks, vectors)
            written.append(row)
            print(f" wrote {n} row(s)")

    report = IndexRunReport(
        snapshot_root=str(snapshot),
        written=written,
        skipped=skipped,
        embedding_model=model_name,
        duration_seconds=time.monotonic() - started,
    )
    print(
        f"\n\u2713 {report.chunks_written} chunk(s) written, "
        f"{len(report.skipped)} project(s) skipped, "
        f"in {report.duration_seconds:.1f}s"
    )
    if report.skipped and not report.written:
        print("  Nothing changed. Use --force to re-embed anyway.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chunk and report token counts. Write nothing, and touch no database.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Compare the indexed corpus against the snapshot manifest. Write nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed and rewrite even when the commit and model already match.",
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
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Embedding batch size. Defaults to settings.embedding_batch_size.",
    )
    args = parser.parse_args()

    if args.dry_run and args.verify:
        parser.error("--dry-run and --verify are both read-only modes; pick one.")
    if args.dry_run and args.force:
        parser.error("--force has no meaning with --dry-run, which never writes.")

    snapshot = resolve_snapshot(args.corpus_dir)
    model_name = args.tokenizer or embedding_model_name()

    if args.dry_run:
        return dry_run(snapshot, model_name)
    if args.verify:
        return report_verify(snapshot, model_name)
    return index(snapshot, model_name, force=args.force, batch_size=args.batch_size)


if __name__ == "__main__":
    sys.exit(main())
