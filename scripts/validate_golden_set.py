"""Validate docs/golden-set/evaluation_questions.yml against schema."""

import sys
from collections import Counter
from pathlib import Path

import yaml

REQUIRED_FIELDS = {"id", "intent", "question", "expected_answer",
                   "expected_source_paths", "should_fallback"}
VALID_INTENTS = {"decision", "architecture", "comparison", "out-of-scope"}

# Mirrors data_platform_rag.contracts.SourceProject.
# This repo is never a corpus source (AGENTS.md boundary).
VALID_PROJECTS = {"sdd-kafka-snowflake-2", "sdd-kafka-databricks"}
SOURCE_FIELDS = {"project", "path"}

TARGET_TOTAL = 50
TARGET_DISTRIBUTION = {
    "decision": 22,
    "architecture": 18,
    "comparison": 5,
    "out-of-scope": 5,
}


def check_sources(i: int, q: dict, errors: list[str]) -> None:
    """Each expected_source_paths entry must be a {project, path} mapping.

    The project is mandatory because the two corpus repos share file names —
    a bare 'README.md' identifies two different documents.
    """
    srcs = q.get("expected_source_paths")
    if not isinstance(srcs, list):
        errors.append(f"[{i}] expected_source_paths must be a list")
        return
    for j, src in enumerate(srcs):
        where = f"[{i}].expected_source_paths[{j}]"
        if not isinstance(src, dict):
            errors.append(f"{where} must be a mapping with 'project' and 'path'")
            continue
        missing = SOURCE_FIELDS - set(src.keys())
        if missing:
            errors.append(f"{where} missing: {sorted(missing)}")
        unknown = set(src.keys()) - SOURCE_FIELDS
        if unknown:
            errors.append(f"{where} unknown keys: {sorted(unknown)}")
        if "project" in src and src["project"] not in VALID_PROJECTS:
            errors.append(f"{where} invalid project: {src['project']!r}")
        if "path" in src and not isinstance(src["path"], str):
            errors.append(f"{where} path must be a string")


def check_distribution(data: list, errors: list[str], warnings: list[str]) -> None:
    """Enforce 22/18/5/5 once the set is full; report progress until then."""
    counts = Counter(q.get("intent") for q in data if isinstance(q, dict))
    total = len(data)
    if total < TARGET_TOTAL:
        warnings.append(f"{total}/{TARGET_TOTAL} questions — curation incomplete.")
        for intent, target in sorted(TARGET_DISTRIBUTION.items()):
            warnings.append(f"    {intent:<14} {counts.get(intent, 0):>2}/{target}")
        warnings.append("  Distribution is not enforced until the set reaches 50.")
    elif total > TARGET_TOTAL:
        errors.append(f"{total} questions — the target is exactly {TARGET_TOTAL}")
    else:
        for intent, target in sorted(TARGET_DISTRIBUTION.items()):
            got = counts.get(intent, 0)
            if got != target:
                errors.append(f"distribution: {intent} is {got}, target {target}")


def main() -> int:
    path = Path("docs/golden-set/evaluation_questions.yml")
    if not path.exists():
        print(f"ERROR: {path} not found")
        return 1

    data = yaml.safe_load(path.read_text())
    if not isinstance(data, list):
        print("ERROR: YAML must be a list of question objects")
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    seen_ids = set()
    for i, q in enumerate(data):
        if not isinstance(q, dict):
            errors.append(f"[{i}] not a dict")
            continue
        missing = REQUIRED_FIELDS - set(q.keys())
        if missing:
            errors.append(f"[{i}] missing fields: {missing}")
        if q.get("intent") not in VALID_INTENTS:
            errors.append(f"[{i}] invalid intent: {q.get('intent')!r}")
        if q.get("id") in seen_ids:
            errors.append(f"[{i}] duplicate id: {q['id']!r}")
        seen_ids.add(q.get("id"))
        check_sources(i, q, errors)

    check_distribution(data, errors, warnings)

    for w in warnings:
        print(f"  ! {w}")
    if errors:
        for e in errors:
            print(f"  {e}")
        return 1

    print(f"✓ {len(data)} questions valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
