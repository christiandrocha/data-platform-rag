"""Settings after ADR-019 Amendment 1 removed `fallback_threshold`."""

from __future__ import annotations

import pytest

from data_platform_rag.config import get_settings


def test_a_deployment_that_still_sets_fallback_threshold_keeps_starting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`extra="ignore"`: the removed variable is ignored, not an error."""
    monkeypatch.setenv("FALLBACK_THRESHOLD", "0.35")
    get_settings.cache_clear()
    settings = get_settings()
    assert not hasattr(settings, "fallback_threshold")


def test_generation_defaults_are_the_values_adr_020_measures() -> None:
    settings = get_settings()
    assert settings.llm_model == "claude-sonnet-4-6"
    assert settings.llm_max_tokens == 1024
    assert settings.llm_temperature == 0.0


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("LLM_MAX_TOKENS", "0"),
        ("LLM_MAX_TOKENS", "16001"),
        ("LLM_TEMPERATURE", "-0.1"),
        ("LLM_TEMPERATURE", "1.1"),
    ],
)
def test_generation_settings_are_bounded(
    monkeypatch: pytest.MonkeyPatch, var: str, value: str
) -> None:
    from pydantic import ValidationError

    monkeypatch.setenv(var, value)
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
