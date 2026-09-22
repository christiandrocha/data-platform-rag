"""Mechanical contamination check (DESIGN property 2, ADR-011 Commitment 1).

For every in-scope question, report any 8-word span the question shares
verbatim with one of its cited sources. A question that repeats its source's
phrasing is found by lexical overlap, not by retrieval, and every metric rises
with nothing looking wrong: the vocabulary contamination ADR-011 exists to
prevent. The same pass checks that each grounding quote really appears in its
cited file, since a quote that is not in the source is the unsupported claim
grounding exists to catch.

Literal and cheap by design. Paraphrase is Layer 2's job
(scripts/audit_questions.py).

The corpus is read only through data_platform_rag.indexer.corpus. Without a
snapshot this script fails, like every corpus consumer (ADR-012): an absent
corpus would pass every question. `--skip-without-snapshot` exists for
`make golden-set-check` alone, and says so loudly when it skips.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml
from validate_golden_set import should_fallback

from data_platform_rag.indexer.corpus import (
    SNAPSHOT_GLOB,
    SNAPSHOT_PARENT,
    corpus_projects,
    in_corpus_files,
    resolve_snapshot,
)

GOLDEN_SET = Path("docs/golden-set/evaluation_questions.yml")
SPAN = 8
_WORD = re.compile(r"\w+")


def words(text: str) -> list[str]:
    """Lowercased word tokens. Punctuation and whitespace carry no signal here."""
    return _WORD.findall(text.lower())


def shared_spans(question: str, source: str, n: int = SPAN) -> list[str]:
    """Every n-word run of the question that also occurs in the source."""
    src = words(source)
    grams = {tuple(src[i:i + n]) for i in range(len(src) - n + 1)}
    q = words(question)
    return [" ".join(q[i:i + n]) for i in range(len(q) - n + 1) if tuple(q[i:i + n]) in grams]


def quote_in_source(quote: str, source: str) -> bool:
    """Verbatim match, modulo whitespace: markdown wraps lines the quote does not."""
    return " ".join(quote.split()) in " ".join(source.split())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=None,
                        help="Corpus snapshot root. Defaults to the newest /tmp/dpr-corpus-*.")
    parser.add_argument("--skip-without-snapshot", action="store_true",
                        help="Exit 0 with a loud SKIPPED line when no snapshot exists.")
    args = parser.parse_args()

    if (args.skip_without_snapshot and args.corpus_dir is None
            and not any(SNAPSHOT_PARENT.glob(SNAPSHOT_GLOB))):
        print("  ! SKIPPED check_contamination: no corpus snapshot. Run `make fetch-corpus`.")
        return 0

    snapshot = resolve_snapshot(args.corpus_dir)
    in_corpus: dict[tuple[str, str], Path] = {}
    for project in corpus_projects():
        root = (snapshot / project).resolve()
        for path in in_corpus_files(root, project):
            in_corpus[(project, path.relative_to(root).as_posix())] = path

    problems: list[str] = []
    for q in yaml.safe_load(GOLDEN_SET.read_text()):
        if should_fallback(q):
            continue
        texts: dict[tuple[str, str], str] = {}
        for src in q.get("expected_source_paths") or []:
            key = (src["project"], src["path"])
            if key not in in_corpus:
                problems.append(f"{q['id']}: cites {key[0]}/{key[1]}, not an in-corpus file")
                continue
            texts[key] = in_corpus[key].read_text(errors="replace")
        for (project, path), text in texts.items():
            spans = shared_spans(q["question"], text)
            if spans:
                problems.append(f"{q['id']}: question shares {len(spans)} {SPAN}-word "
                                f"span(s) with {project}/{path}, first: {spans[0]!r}")
        for g in q.get("grounding") or []:
            text = texts.get((g["project"], g["path"]))
            if text is not None and not quote_in_source(g["quote"], text):
                problems.append(f"{q['id']}: grounding quote not in {g['path']}: {g['quote']!r}")

    print(f"Snapshot: {snapshot}")
    for p in problems:
        print(f"  {p}")
    if problems:
        return 1
    print("✓ no verbatim overlap; every grounding quote found in its source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
