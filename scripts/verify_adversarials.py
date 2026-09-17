"""Layer 1 of adversarial verification (ADR-011): literal contamination probes.

For every `intent: out-of-scope` question, grep each declared contamination probe
against the indexed file set of both corpus repos. A literal match on any probe
means the question has lost its adversarial status, and the run fails.

This is a blocking precondition of `make eval` and `make eval-ci`. It is not a
warning: a contaminated adversarial does not degrade fallback_accuracy, it makes
it objectively wrong while leaving it looking healthy — the `error` criterion of
the severity convention in sdd-kafka-snowflake-2 ADR-0027.

Two properties decided on evidence, both load-bearing:

* **Scoped** to the in-corpus file set, never the snapshot root. Probe "Flink"
  matches 5 files in the sdd-kafka-databricks clone and 0 in-corpus; all five are
  .claude/ internals that are never indexed. That set is owned by
  `data_platform_rag.indexer.corpus` and imported, never re-declared here: a gate
  wider than the index over-blocks valid adversarials (ADR-012).
* **Case-sensitive.** sdd-kafka-databricks/README.md:31 reads "Kafka streams,
  MongoDB documents" — generic lowercase prose that a case-insensitive probe for
  "Kafka Streams" would match, failing a valid adversarial.

Layer 1 is literal and therefore semantically short-sighted by design. Paraphrase
is Layer 2's job (scripts/audit_questions.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from data_platform_rag.indexer.corpus import (
    corpus_projects,
    in_corpus_files,
    resolve_snapshot,
)

GOLDEN_SET = Path("docs/golden-set/evaluation_questions.yml")


def probe_matches(probe: str, files: list[Path]) -> list[tuple[Path, int, str]]:
    """Case-sensitive fixed-string search. Returns (path, lineno, line) hits."""
    hits: list[tuple[Path, int, str]] = []
    for path in files:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if probe in line:
                hits.append((path, lineno, line.strip()))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help="Corpus clones root. Defaults to the newest /tmp/dpr-corpus-* (canonical); "
             "pass a path to override for local dev.",
    )
    args = parser.parse_args()

    snapshot = resolve_snapshot(args.corpus_dir)

    repos: list[tuple[Path, str]] = []
    for name in corpus_projects():
        repo = snapshot / name
        if not repo.is_dir():
            print(f"ERROR: corpus repo {name!r} not found under {snapshot}")
            return 1
        repos.append((repo, name))

    data = yaml.safe_load(GOLDEN_SET.read_text())
    adversarials = [q for q in data if q.get("intent") == "out-of-scope"]
    if not adversarials:
        print("ERROR: no out-of-scope questions found — nothing to verify")
        return 1

    failures = 0
    checked = 0
    for q in adversarials:
        qid = q.get("id", "<no id>")
        probes = q.get("contamination_probes") or []
        if not probes:
            print(f"  {qid}: no contamination_probes declared (ADR-011 requires >= 1)")
            failures += 1
            continue
        for probe in probes:
            checked += 1
            all_hits: list[tuple[Path, int, str]] = []
            for repo, project in repos:
                all_hits.extend(probe_matches(probe, in_corpus_files(repo, project)))
            if all_hits:
                failures += 1
                print(f"  {qid}: probe {probe!r} MATCHED in-corpus:")
                for path, lineno, line in all_hits[:5]:
                    print(f"      {path}:{lineno}: {line[:100]}")
                if len(all_hits) > 5:
                    print(f"      ... and {len(all_hits) - 5} more")

    if failures:
        print(
            f"\n{failures} contamination failure(s). Per ADR-011 'Recovery workflow':\n"
            "  Scenario A — contamination is real: substitute or re-classify the question.\n"
            "  Scenario B — probe too broad: run `make audit-adversarials q=<id>` (Layer 2)\n"
            "               and attach the Opus output to a dev log entry before changing\n"
            "               any probe. Narrowing a probe is never a unilateral act."
        )
        return 1

    print(
        f"✓ {len(adversarials)} adversarial(s), {checked} probe(s) against "
        f"{len(repos)} corpus repo(s), no in-corpus matches"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
