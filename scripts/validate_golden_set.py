"""Validate docs/golden-set/evaluation_questions.yml against schema."""

import sys
from collections import Counter
from pathlib import Path

import yaml

REQUIRED_FIELDS = {"id", "provenance", "voice", "intent", "question", "expected_answer",
                   "expected_source_paths"}

# ADR-011 Commitment 1: all questions are human-authored. `llm` exists only for
# retreat A3, where an LLM proposes architecture questions. The field is
# mandatory either way — without it the two populations are indistinguishable
# after the fact, and the retreat silently becomes the thing the commitment
# exists to prevent.
VALID_PROVENANCE = {"human", "llm"}

# Dev log #23: recruiters ask with job-posting keywords; hiring managers and
# interviewers ask why a decision was taken. Recorded per question so RAGAS can
# be reported per voice — pooled scores would hide a system that serves one
# audience and fails the other.
VALID_VOICES = {"recruiter", "technical"}

# Required on out-of-scope questions only; rejected on any other intent.
ADVERSARIAL_FIELDS = {"contamination_probes", "grep_verified"}
# ADR-011 requires at least one probe. Two or more is the curation
# recommendation, deliberately not enforced here.
MIN_PROBES = 1

# Optional on in-scope questions, rejected on out-of-scope ones (DESIGN, Data
# contracts). `grounding_verified` is the author's attestation that every claim
# in expected_answer was checked against a cited source; `grounding` holds
# verbatim quotes for the high-risk claims (ADR-011 Commitment 3).
GROUNDING_FIELDS = {"grounding_verified", "grounding"}
GROUNDING_ENTRY_FIELDS = {"claim", "project", "path", "quote"}
_EDGE_PUNCT = ".,;:!?()[]\"'"

# `hybrid` is deliberately absent. It is a valid runtime value of
# contracts.Intent — the classifier's semantic fallback when a query resolves to
# no target category — but it is not a category questions are authored against.
# See PRE_BUILD_VALIDATION.md Section 6 change 3 and docs/golden-set/README.md.
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


def should_fallback(q: dict) -> bool:
    """Derived, never stored.

    A question expects the fallback if and only if its intent is out-of-scope.
    Storing this as its own field would encode one fact twice, and the two
    copies would eventually disagree. Any consumer that needs the boolean
    computes it here.
    """
    return q.get("intent") == "out-of-scope"


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


def check_coherence(i: int, q: dict, errors: list[str]) -> None:
    """An out-of-scope question has no answer and no sources; others need both.

    This replaces the old should_fallback pairing check. With the boolean
    derived, the remaining invariant is between intent and the answer fields.
    """
    expects_fallback = should_fallback(q)
    answer = q.get("expected_answer")
    srcs = q.get("expected_source_paths")
    if expects_fallback:
        if answer is not None:
            errors.append(f"[{i}] out-of-scope question must have expected_answer: null")
        if srcs:
            errors.append(f"[{i}] out-of-scope question must have no expected_source_paths")
    else:
        if not isinstance(answer, str) or not answer.strip():
            errors.append(f"[{i}] in-scope question needs a non-empty expected_answer")
        if not srcs:
            errors.append(f"[{i}] in-scope question needs at least one expected_source_paths entry")


def check_adversarial_fields(i: int, q: dict, errors: list[str]) -> None:
    """Out-of-scope questions declare contamination probes; others must not.

    A probe is a phrase that, if it appears in the corpus, costs the question its
    adversarial status. Per ADR-011 these are author-declared rather than derived:
    every heuristic for extracting them either false-positives on common terms or
    needs a non-deterministic model. This check enforces their presence and shape;
    scripts/verify_adversarials.py does the greping.
    """
    where = f"[{i}]"
    present = ADVERSARIAL_FIELDS & set(q.keys())
    if not should_fallback(q):
        if present:
            errors.append(f"{where} {sorted(present)} allowed only on out-of-scope questions")
        return

    missing = ADVERSARIAL_FIELDS - set(q.keys())
    if missing:
        errors.append(f"{where} out-of-scope question missing: {sorted(missing)}")

    probes = q.get("contamination_probes")
    if probes is None:
        return
    if not isinstance(probes, list):
        errors.append(f"{where} contamination_probes must be a list")
        return
    if len(probes) < MIN_PROBES:
        errors.append(f"{where} needs at least {MIN_PROBES} contamination_probe(s)")
    for j, probe in enumerate(probes):
        if not isinstance(probe, str) or not probe.strip():
            errors.append(f"{where}.contamination_probes[{j}] must be a non-empty string")


def check_voice(i: int, q: dict, errors: list[str]) -> None:
    """Every question declares who is asking: recruiter or technical (dev log #23)."""
    if q.get("voice") not in VALID_VOICES:
        errors.append(f"[{i}] invalid voice: {q.get('voice')!r}")


def check_comparison_sources(i: int, q: dict, errors: list[str]) -> None:
    """A comparison question cites at least one source from each project.

    DEFINE MUST. A cross-project question anchored to one project can be
    answered from one side only, and retrieval would then score as complete
    on a comparison it never saw both halves of.
    """
    if q.get("intent") != "comparison":
        return
    cited = {
        s.get("project")
        for s in q.get("expected_source_paths") or []
        if isinstance(s, dict)
    }
    missing = sorted(VALID_PROJECTS - cited)
    if missing:
        errors.append(f"[{i}] comparison question cites no source from: {missing}")


def high_risk_tokens(answer: str) -> list[str]:
    """Words of expected_answer that carry a digit: numbers, versions, ADR IDs.

    ADR-011 Commitment 3's mechanical floor. A number, a version string like
    `v4` and an ID like `ADR-007` are all words containing a digit, so one rule
    covers the three, and the closed set never goes stale.
    """
    words = (w.strip(_EDGE_PUNCT) for w in answer.split())
    return [w for w in words if any(c.isdigit() for c in w)]


def check_grounding(
    i: int, q: dict, errors: list[str], warnings: list[str], full: bool
) -> None:
    """Grounding evidence on in-scope questions (ADR-011 Commitment 3).

    Incomplete evidence (no attestation, a high-risk word without a quote) warns
    until the set reaches 50 and errors after, like the distribution check.
    Wrong evidence (a quote from a source the question does not cite, a claim
    that is not in the answer, a malformed entry) errors at any size.
    """
    where = f"[{i}]"
    if should_fallback(q):
        present = GROUNDING_FIELDS & set(q.keys())
        if present:
            errors.append(f"{where} {sorted(present)} not allowed on out-of-scope questions")
        return

    incomplete = errors if full else warnings
    if q.get("grounding_verified") is not True:
        incomplete.append(f"{where} grounding_verified must be true")

    entries = q.get("grounding", [])
    if not isinstance(entries, list):
        errors.append(f"{where} grounding must be a list")
        return
    cited = {
        (s.get("project"), s.get("path"))
        for s in q.get("expected_source_paths") or []
        if isinstance(s, dict)
    }
    answer = q.get("expected_answer") or ""
    claims: list[str] = []
    for j, entry in enumerate(entries):
        at = f"{where}.grounding[{j}]"
        if not isinstance(entry, dict):
            errors.append(f"{at} must be a mapping with {sorted(GROUNDING_ENTRY_FIELDS)}")
            continue
        missing = GROUNDING_ENTRY_FIELDS - set(entry)
        unknown = set(entry) - GROUNDING_ENTRY_FIELDS
        if missing or unknown:
            errors.append(f"{at} missing: {sorted(missing)}, unknown: {sorted(unknown)}")
            continue
        blank = sorted(k for k in GROUNDING_ENTRY_FIELDS
                       if not isinstance(entry[k], str) or not entry[k].strip())
        if blank:
            errors.append(f"{at} must be non-empty strings: {blank}")
            continue
        if (entry["project"], entry["path"]) not in cited:
            errors.append(f"{at} quotes a source the question does not cite")
        if entry["claim"] not in answer:
            errors.append(f"{at} claim is not a span of expected_answer")
        claims.append(entry["claim"])

    for token in high_risk_tokens(answer):
        if not any(token in claim for claim in claims):
            incomplete.append(f"{where} {token!r} in expected_answer needs a grounding quote")


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
        unknown = set(q.keys()) - REQUIRED_FIELDS - ADVERSARIAL_FIELDS - GROUNDING_FIELDS
        if unknown:
            errors.append(f"[{i}] unknown fields: {sorted(unknown)}")
        if q.get("provenance") not in VALID_PROVENANCE:
            errors.append(f"[{i}] invalid provenance: {q.get('provenance')!r}")
        if q.get("intent") not in VALID_INTENTS:
            errors.append(f"[{i}] invalid intent: {q.get('intent')!r}")
        if q.get("id") in seen_ids:
            errors.append(f"[{i}] duplicate id: {q['id']!r}")
        seen_ids.add(q.get("id"))
        check_sources(i, q, errors)
        check_coherence(i, q, errors)
        check_adversarial_fields(i, q, errors)
        check_voice(i, q, errors)
        check_comparison_sources(i, q, errors)
        check_grounding(i, q, errors, warnings, full=len(data) >= TARGET_TOTAL)

    check_distribution(data, errors, warnings)

    for w in warnings:
        print(f"  ! {w}")
    if errors:
        for e in errors:
            print(f"  {e}")
        return 1

    n_fallback = sum(1 for q in data if should_fallback(q))
    by_prov = Counter(q.get("provenance") for q in data)
    prov = ", ".join(f"{k}={v}" for k, v in sorted(by_prov.items()) if k)
    by_voice = Counter(q.get("voice") for q in data)
    voice = ", ".join(f"{k}={v}" for k, v in sorted(by_voice.items()) if k)
    print(f"✓ {len(data)} questions valid ({n_fallback} expect the fallback) [{prov}] [{voice}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
