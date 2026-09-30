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
