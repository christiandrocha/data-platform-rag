"""Layer 1 of adversarial verification (ADR-011): literal contamination probes.

For every `intent: out-of-scope` question, grep each declared contamination probe
against the indexed file set of both corpus repos. A literal match on any probe
means the question has lost its adversarial status, and the run fails.

This is a blocking precondition of `make eval` and `make eval-ci`. It is not a
warning: a contaminated adversarial does not degrade fallback_accuracy, it makes
it objectively wrong while leaving it looking healthy — the `error` criterion of
the severity convention in sdd-kafka-snowflake-2 ADR-0027.

Two properties decided on evidence, both load-bearing:

* **Scoped** to the indexed paths below, never the clone root. Probe "Flink"
  matches 5 files in the sdd-kafka-databricks clone and 0 in-corpus; all five are
  .claude/ internals that are never indexed.
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

# The indexed file set. Anything outside this is not corpus and must not be
# grepped — see the module docstring.
IN_CORPUS_SUBPATHS = ("docs/adr", "README.md", "contracts", "macros")

GOLDEN_SET = Path("docs/golden-set/evaluation_questions.yml")
INVENTORY = Path("docs/golden-set/corpus_inventory.yml")

# Keys in corpus_inventory.yml that are configuration rather than a project.
_NON_PROJECT_KEYS = {"seed", "verified_against_clone"}


def corpus_projects() -> list[str]:
    """The corpus repo names, read from the inventory — never inferred from disk.

    Iterating every subdirectory of --corpus-dir would grep whatever happens to
    sit beside the clones, including this repository, which AGENTS.md forbids
    treating as a corpus source. The inventory is the allowlist.
    """
    inventory = yaml.safe_load(INVENTORY.read_text())
    return sorted(k for k in inventory if k not in _NON_PROJECT_KEYS)


def in_corpus_files(repo_root: Path) -> list[Path]:
    """Every indexed file under one corpus repo."""
    files: list[Path] = []
    for sub in IN_CORPUS_SUBPATHS:
        target = repo_root / sub
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(p for p in target.rglob("*") if p.is_file())
    return files


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
        required=True,
        type=Path,
        help="Directory containing both corpus repo clones as subdirectories.",
    )
    args = parser.parse_args()

    if not args.corpus_dir.is_dir():
        print(f"ERROR: --corpus-dir {args.corpus_dir} is not a directory")
        return 1

    projects = corpus_projects()
    repos = []
    for name in projects:
        repo = args.corpus_dir / name
        if not repo.is_dir():
            print(f"ERROR: corpus repo {name!r} not found under {args.corpus_dir}")
            return 1
        repos.append(repo)

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
            for repo in repos:
                all_hits.extend(probe_matches(probe, in_corpus_files(repo)))
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
