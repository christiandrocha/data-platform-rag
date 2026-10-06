"""The real Anthropic client, built in one place.

`generation/client.py` never constructs or imports the SDK, so the package stays
importable without `anthropic` installed and every test runs on a stub. The two
callers that talk to the API, `scripts/fallback_eval.py` (ADR-020), the page
(ADR-021) and the RAGAS judge (ADR-008), build their client here, after checking
for a key.
"""

from __future__ import annotations

from data_platform_rag.generation.client import LLMClient


def build_client(api_key: str) -> LLMClient:
    """An `anthropic.Anthropic`. Raises ImportError when the SDK is not installed."""
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def build_async_client(api_key: str) -> object:
    """An `anthropic.AsyncAnthropic`, for the RAGAS judge (ADR-008 D5).

    RAGAS 0.4's metrics call the judge's `agenerate`, which raises `TypeError` on
    a sync client. Raises ImportError when the SDK is not installed.
    """
    import anthropic

    return anthropic.AsyncAnthropic(api_key=api_key)
