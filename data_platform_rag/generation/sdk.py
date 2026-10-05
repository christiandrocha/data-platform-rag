"""The real Anthropic client, built in one place.

`generation/client.py` never constructs or imports the SDK, so the package stays
importable without `anthropic` installed and every test runs on a stub. The two
callers that talk to the API, `scripts/fallback_eval.py` (ADR-020) and the page
(ADR-021), build their client here, after checking for a key.
"""

from __future__ import annotations

from data_platform_rag.generation.client import LLMClient


def build_client(api_key: str) -> LLMClient:
    """An `anthropic.Anthropic`. Raises ImportError when the SDK is not installed."""
    import anthropic

    return anthropic.Anthropic(api_key=api_key)
