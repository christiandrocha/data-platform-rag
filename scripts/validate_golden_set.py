"""Validate docs/golden-set/evaluation_questions.yml against schema."""

import sys
from pathlib import Path

import yaml

REQUIRED_FIELDS = {"id", "intent", "question", "expected_answer",
                   "expected_source_paths", "should_fallback"}
VALID_INTENTS = {"decision", "architecture", "hybrid", "out-of-scope"}


def main() -> int:
    path = Path("docs/golden-set/evaluation_questions.yml")
    if not path.exists():
        print(f"ERROR: {path} not found")
        return 1

    data = yaml.safe_load(path.read_text())
    if not isinstance(data, list):
        print("ERROR: YAML must be a list of question objects")
        return 1

    errors = []
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

    if errors:
        for e in errors:
            print(f"  {e}")
        return 1

    print(f"✓ {len(data)} questions valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
