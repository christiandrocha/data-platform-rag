"""Tests for the golden-set validator.

The validator was untested through Phase 0; a schema change is the right moment
to fix that. Each check is a pure function over parsed YAML, so these are plain
unit tests with no fixtures on disk.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from validate_golden_set import (  # noqa: E402
    check_adversarial_fields,
    check_coherence,
    check_comparison_sources,
    check_distribution,
    check_grounding,
    check_sources,
    check_voice,
    high_risk_tokens,
    should_fallback,
)


def in_scope(**over):
    q = {
        "id": "q001",
        "intent": "decision",
        "question": "Why X?",
        "expected_answer": "Because Y.",
        "expected_source_paths": [
            {"project": "sdd-kafka-snowflake-2", "path": "docs/adr/ADR-0029.md"}
        ],
    }
    q.update(over)
    return q


def adversarial(**over):
    q = {
        "id": "q005",
        "intent": "out-of-scope",
        "question": "Opinion on X?",
        "expected_answer": None,
        "expected_source_paths": [],
        "contamination_probes": ["Apache Flink", "Kafka Streams"],
        "grep_verified": "2026-09-14",
    }
    q.update(over)
    return q


# ─── should_fallback ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "intent,expected",
    [("out-of-scope", True), ("decision", False), ("architecture", False), ("comparison", False)],
)
def test_should_fallback_is_derived_from_intent(intent, expected):
    assert should_fallback({"intent": intent}) is expected


# ─── check_sources ───────────────────────────────────────────────────────────


def test_sources_accepts_project_path_mapping():
    errors = []
    check_sources(0, in_scope(), errors)
    assert errors == []


def test_sources_rejects_bare_string():
    errors = []
    check_sources(0, in_scope(expected_source_paths=["docs/adr/ADR-0029.md"]), errors)
    assert len(errors) == 1 and "mapping" in errors[0]


def test_sources_rejects_missing_project():
    errors = []
    check_sources(0, in_scope(expected_source_paths=[{"path": "README.md"}]), errors)
    assert any("missing" in e and "project" in e for e in errors)


def test_sources_rejects_unknown_project():
    errors = []
    check_sources(0, in_scope(expected_source_paths=[
        {"project": "data-platform-rag", "path": "README.md"}
    ]), errors)
    assert any("invalid project" in e for e in errors)


def test_sources_rejects_unknown_keys():
    errors = []
    check_sources(0, in_scope(expected_source_paths=[
        {"project": "sdd-kafka-databricks", "path": "README.md", "anchor": "x"}
    ]), errors)
    assert any("unknown keys" in e for e in errors)


# ─── check_coherence ─────────────────────────────────────────────────────────


def test_coherence_accepts_aligned_in_scope():
    errors = []
    check_coherence(0, in_scope(), errors)
    assert errors == []


def test_coherence_accepts_aligned_adversarial():
    errors = []
    check_coherence(0, adversarial(), errors)
    assert errors == []


def test_coherence_rejects_adversarial_with_answer():
    errors = []
    check_coherence(0, adversarial(expected_answer="Something."), errors)
    assert any("expected_answer: null" in e for e in errors)


def test_coherence_rejects_adversarial_with_sources():
    errors = []
    check_coherence(0, adversarial(expected_source_paths=[
        {"project": "sdd-kafka-databricks", "path": "README.md"}
    ]), errors)
    assert any("no expected_source_paths" in e for e in errors)


def test_coherence_rejects_in_scope_without_answer():
    errors = []
    check_coherence(0, in_scope(expected_answer="   "), errors)
    assert any("non-empty expected_answer" in e for e in errors)


def test_coherence_rejects_in_scope_without_sources():
    errors = []
    check_coherence(0, in_scope(expected_source_paths=[]), errors)
    assert any("at least one expected_source_paths" in e for e in errors)


# ─── check_adversarial_fields ────────────────────────────────────────────────


def test_adversarial_fields_accepted_on_out_of_scope():
    errors = []
    check_adversarial_fields(0, adversarial(), errors)
    assert errors == []


def test_adversarial_fields_rejected_on_in_scope():
    errors = []
    check_adversarial_fields(0, in_scope(contamination_probes=["X"]), errors)
    assert any("allowed only on out-of-scope" in e for e in errors)


def test_adversarial_requires_probes():
    q = adversarial()
    del q["contamination_probes"]
    errors = []
    check_adversarial_fields(0, q, errors)
    assert any("missing" in e and "contamination_probes" in e for e in errors)


def test_adversarial_requires_grep_verified():
    q = adversarial()
    del q["grep_verified"]
    errors = []
    check_adversarial_fields(0, q, errors)
    assert any("missing" in e and "grep_verified" in e for e in errors)


def test_adversarial_rejects_empty_probe_list():
    errors = []
    check_adversarial_fields(0, adversarial(contamination_probes=[]), errors)
    assert any("at least" in e for e in errors)


def test_adversarial_rejects_blank_probe():
    errors = []
    check_adversarial_fields(0, adversarial(contamination_probes=["  "]), errors)
    assert any("non-empty string" in e for e in errors)


# ─── check_distribution ──────────────────────────────────────────────────────


def _set(**counts):
    out = []
    for intent, n in counts.items():
        out.extend({"intent": intent.replace("_", "-")} for _ in range(n))
    return out


def test_distribution_warns_below_fifty_without_erroring():
    errors, warnings = [], []
    check_distribution(_set(decision=2), errors, warnings)
    assert errors == []
    assert any("curation incomplete" in w for w in warnings)


def test_distribution_passes_at_exact_target():
    errors, warnings = [], []
    check_distribution(
        _set(decision=22, architecture=18, comparison=5, out_of_scope=5), errors, warnings
    )
    assert errors == []


def test_distribution_errors_on_wrong_split_at_fifty():
    errors, warnings = [], []
    check_distribution(
        _set(decision=23, architecture=17, comparison=5, out_of_scope=5), errors, warnings
    )
    assert any("decision is 23" in e for e in errors)


def test_distribution_errors_above_fifty():
    errors, warnings = [], []
    check_distribution(_set(decision=51), errors, warnings)
    assert any("exactly 50" in e for e in errors)


# ─── check_voice ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("voice", ["recruiter", "technical"])
def test_voice_accepts_both_audiences(voice):
    errors = []
    check_voice(0, in_scope(voice=voice), errors)
    assert errors == []


def test_voice_rejects_unknown_value():
    errors = []
    check_voice(0, in_scope(voice="manager"), errors)
    assert any("invalid voice" in e for e in errors)


def test_voice_rejects_missing_field():
    errors = []
    check_voice(0, in_scope(), errors)
    assert any("invalid voice" in e for e in errors)


# ─── check_grounding ─────────────────────────────────────────────────────────

SRC = {"project": "sdd-kafka-snowflake-2", "path": "docs/adr/ADR-0029.md"}


def quote(claim, **over):
    entry = {"claim": claim, "project": SRC["project"], "path": SRC["path"], "quote": "q"}
    entry.update(over)
    return entry


def test_high_risk_tokens_catch_digits_versions_and_adr_ids():
    assert high_risk_tokens("Twenty runs, v4 and ADR-0030. See 128k.") == ["v4", "ADR-0030", "128k"]


def test_grounding_rejected_on_out_of_scope():
    errors, warnings = [], []
    check_grounding(0, adversarial(grounding_verified=True), errors, warnings, full=False)
    assert any("not allowed on out-of-scope" in e for e in errors)


def test_missing_attestation_warns_below_fifty():
    errors, warnings = [], []
    check_grounding(0, in_scope(), errors, warnings, full=False)
    assert errors == []
    assert any("grounding_verified must be true" in w for w in warnings)


def test_missing_attestation_errors_at_fifty():
    errors, warnings = [], []
    check_grounding(0, in_scope(grounding_verified=False), errors, warnings, full=True)
    assert any("grounding_verified must be true" in e for e in errors)


def test_attested_prose_answer_is_clean():
    errors, warnings = [], []
    check_grounding(0, in_scope(grounding_verified=True), errors, warnings, full=True)
    assert errors == [] and warnings == []


def test_digit_without_quote_warns_below_fifty_and_errors_at_fifty():
    q = in_scope(expected_answer="The v4 connector.", grounding_verified=True)
    errors, warnings = [], []
    check_grounding(0, q, errors, warnings, full=False)
    assert errors == [] and any("'v4'" in w for w in warnings)
    errors, warnings = [], []
    check_grounding(0, q, errors, warnings, full=True)
    assert any("'v4'" in e for e in errors)


def test_digit_covered_by_a_quoted_claim_is_clean():
    q = in_scope(expected_answer="ADR-007 supersedes ADR-003.", grounding_verified=True,
                 grounding=[quote("ADR-007 supersedes ADR-003")])
    errors, warnings = [], []
    check_grounding(0, q, errors, warnings, full=True)
    assert errors == [] and warnings == []


def test_quote_from_uncited_source_errors():
    q = in_scope(expected_answer="The v4 connector.", grounding_verified=True,
                 grounding=[quote("The v4 connector", path="README.md")])
    errors, warnings = [], []
    check_grounding(0, q, errors, warnings, full=False)
    assert any("does not cite" in e for e in errors)


def test_claim_not_in_answer_errors():
    q = in_scope(expected_answer="The v4 connector.", grounding_verified=True,
                 grounding=[quote("The v5 connector")])
    errors, warnings = [], []
    check_grounding(0, q, errors, warnings, full=False)
    assert any("not a span of expected_answer" in e for e in errors)


def test_grounding_entry_missing_quote_errors():
    entry = quote("The v4 connector")
    del entry["quote"]
    q = in_scope(expected_answer="The v4 connector.", grounding=[entry])
    errors, warnings = [], []
    check_grounding(0, q, errors, warnings, full=False)
    assert any("missing: ['quote']" in e for e in errors)


def test_grounding_entry_blank_quote_errors():
    q = in_scope(expected_answer="The v4 connector.",
                 grounding=[quote("The v4 connector", quote="  ")])
    errors, warnings = [], []
    check_grounding(0, q, errors, warnings, full=False)
    assert any("non-empty strings: ['quote']" in e for e in errors)


def test_grounding_must_be_a_list():
    errors, warnings = [], []
    check_grounding(0, in_scope(grounding="x"), errors, warnings, full=False)
    assert any("grounding must be a list" in e for e in errors)


# ─── check_comparison_sources ────────────────────────────────────────────────

BOTH = [
    {"project": "sdd-kafka-snowflake-2", "path": "docs/adr/ADR-0030.md"},
    {"project": "sdd-kafka-databricks", "path": "README.md"},
]


def test_comparison_citing_both_projects_is_clean():
    errors = []
    check_comparison_sources(0, in_scope(intent="comparison", expected_source_paths=BOTH), errors)
    assert errors == []


def test_comparison_citing_one_project_errors():
    errors = []
    check_comparison_sources(0, in_scope(intent="comparison"), errors)
    assert any("cites no source from: ['sdd-kafka-databricks']" in e for e in errors)


def test_single_project_rule_applies_only_to_comparison():
    errors = []
    check_comparison_sources(0, in_scope(intent="decision"), errors)
    assert errors == []
