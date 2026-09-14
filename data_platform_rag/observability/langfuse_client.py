"""Langfuse client singleton with no-op fallback.

Per ADR-009, when LANGFUSE_ENABLED=false OR credentials are missing,
this returns a no-op client that accepts all calls silently. This keeps
the pipeline code identical across dev/test/prod configurations.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any


class _NoopContext:
    def __enter__(self) -> _NoopContext:
        return self

    def __exit__(self, *args: Any) -> None:  # noqa: ANN401
        return None

    def update(self, **_: Any) -> None:  # noqa: ANN401
        return None

    def score(self, **_: Any) -> None:  # noqa: ANN401
        return None


class NoopLangfuse:
    """Drop-in Langfuse replacement that swallows all calls."""

    def trace(self, **_: Any) -> _NoopContext:  # noqa: ANN401
        return _NoopContext()

    def span(self, **_: Any) -> _NoopContext:  # noqa: ANN401
        return _NoopContext()

    def generation(self, **_: Any) -> _NoopContext:  # noqa: ANN401
        return _NoopContext()

    def score(self, **_: Any) -> None:  # noqa: ANN401
        return None

    def flush(self) -> None:
        return None


@lru_cache(maxsize=1)
def get_client() -> Any:  # noqa: ANN401
    """Return Langfuse client or no-op fallback. Singleton per process.

    TODO(BUILD): swap Any return for a Protocol once the Langfuse SDK API
    surface used is stabilized in DESIGN of feature: langfuse-integration.
    """
    from data_platform_rag.config import get_settings

    settings = get_settings()
    if not settings.langfuse_enabled:
        return NoopLangfuse()
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return NoopLangfuse()

    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            host=settings.langfuse_host,
        )
    except ImportError:
        # langfuse not installed — treat as disabled
        return NoopLangfuse()
