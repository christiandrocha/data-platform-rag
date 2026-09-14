"""Golden-set coverage against the corpus inventory (ADR-011).

Answers two questions:

* Which inventory ADRs have no question yet? (`--report`, the default)
* Which ADR should be authored next? (`--next`)

Coverage is computed, never asserted. A checked-in matrix would be a second
source of truth that drifts from the YAML, and a stale matrix reports full
coverage for an ADR nobody asked about.

The walk order is a seeded shuffle interleaving the two projects, per ADR-011.
Authoring in inventory order produces two systematic biases: the last ADRs
receive the most fatigued questions, and writing one project fully before the
other lets a per-project voice drift into the phrasing. The seed is immutable for
the life of a golden set generation.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import defaultdict
from itertools import zip_longest
from pathlib import Path

import yaml

GOLDEN_SET = Path("docs/golden-set/evaluation_questions.yml")
INVENTORY = Path("docs/golden-set/corpus_inventory.yml")
_NON_PROJECT_KEYS = {"seed", "verified_against_clone"}


def load_inventory() -> tuple[int, dict[str, list[str]]]:
    raw = yaml.safe_load(INVENTORY.read_text())
    seed = raw["seed"]
    projects = {k: v["adrs"] for k, v in raw.items() if k not in _NON_PROJECT_KEYS}
    return seed, projects


def walk_order(seed: int, projects: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Seeded shuffle per project, then interleaved.

    Deterministic for a given seed and project ordering. New ADRs appended to the
    inventory land at the end of their project's list before shuffling, so a
    growing inventory reshuffles — which is why ADR-011 requires appending to the
    *walk order*, not the inventory, mid-curation. Until curation starts, this is
    the canonical order.
    """
    rng = random.Random(seed)
    shuffled: dict[str, list[str]] = {}
    for name in sorted(projects):
        adrs = list(projects[name])
        rng.shuffle(adrs)
        shuffled[name] = adrs
    interleaved: list[tuple[str, str]] = []
    for row in zip_longest(*(shuffled[n] for n in sorted(shuffled))):
        for name, adr in zip(sorted(shuffled), row, strict=True):
            if adr is not None:
                interleaved.append((name, adr))
    return interleaved


def cited(golden_set: list[dict]) -> dict[tuple[str, str], list[str]]:
    """Map (project, path) -> the intents of the questions citing it."""
    out: dict[tuple[str, str], list[str]] = defaultdict(list)
    for q in golden_set:
        for src in q.get("expected_source_paths") or []:
            if isinstance(src, dict) and "project" in src and "path" in src:
                out[(src["project"], src["path"])].append(q.get("intent", "?"))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--next", action="store_true", help="Print the next uncovered ADR and exit 0"
    )
    args = parser.parse_args()

    seed, projects = load_inventory()
    order = walk_order(seed, projects)
    coverage = cited(yaml.safe_load(GOLDEN_SET.read_text()))

    uncovered = [(p, a) for (p, a) in order if not coverage.get((p, a))]

    if args.next:
        if not uncovered:
            print("✓ every inventory ADR is covered — nothing left to author")
            return 0
        project, adr = uncovered[0]
        position = len(order) - len(uncovered) + 1
        print(f"next [{position}/{len(order)}]  {project}  {adr}")
        return 0

    print(f"Walk order seed: {seed}\n")
    print(f"{'#':>3}  {'project':<24} {'ADR':<52} intents")
    print("-" * 100)
    for i, (project, adr) in enumerate(order, start=1):
        intents = coverage.get((project, adr), [])
        marker = ", ".join(sorted(intents)) if intents else "— none —"
        print(f"{i:>3}  {project:<24} {Path(adr).name:<52} {marker}")

    print(f"\n{len(order) - len(uncovered)}/{len(order)} inventory ADRs covered")
    if uncovered:
        print(f"{len(uncovered)} uncovered. Next: {uncovered[0][0]} {uncovered[0][1]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
