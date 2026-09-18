"""Unit tests never construct real `Settings`.

This has now bitten twice. `Settings` requires `anthropic_api_key` and
`database_url`, both read from a gitignored `.env`. A unit test that reaches
`get_settings()` therefore passes on a developer machine — where pytest runs from
the repo root and `.env` is present — and fails in CI, which has no `.env` and no
credential. It also fails for anyone running pytest from another directory.

Both times the failure was invisible locally and only appeared in CI, so the fix
belongs here rather than in whichever test file happens to trip next: this
fixture makes the whole unit suite independent of the environment, and any test
that wants specific values still overrides them with its own stub.

Nothing here is a real credential. `data_platform_rag/config.py` is what these
values feed, and no unit test opens a connection or calls an API.
"""

from __future__ import annotations

import pytest

from data_platform_rag.config import get_settings

STUB_ENV = {
    "ANTHROPIC_API_KEY": "test-not-a-real-key",
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
}


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch):
    """Give every unit test a constructible Settings, and no shared cache.

    The cache is cleared on both sides: an integration test running earlier in
    the session would otherwise leave real settings memoised, and this fixture's
    values would leak into whatever runs after it.
    """
    for key, value in STUB_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
