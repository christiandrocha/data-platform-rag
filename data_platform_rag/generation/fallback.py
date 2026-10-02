"""Classify one LLM output against the fallback contract (ADR-020).

Rule 3 tells the LLM to return `FALLBACK_MESSAGE` verbatim when the context does
not answer the question. Whether it did is decided here, from the text alone, by
exact match. The four classes and their order were fixed in DEFINE before any
call was made:

- **empty**: nothing but whitespace (DEFINE Amendment 1). Checked first, so an
  empty output can never be mistaken for anything else
- **fallback**: the trimmed output is exactly `FALLBACK_MESSAGE`
- **non_compliant_refusal**: not exact, but it carries the LinkedIn URL. The
  visitor did not get the fixed message, so this never counts as a fallback
- **answer**: anything else

A refusal worded without the URL classifies as an answer. Exact matching cannot
see it, and ADR-020 records that as a known limitation rather than guessing.
"""

from __future__ import annotations

from data_platform_rag.contracts import OutputClass
from data_platform_rag.generation.prompt import FALLBACK_MESSAGE

# The part of the fallback that identifies a refusal, however it is reworded. A
# unit test checks it occurs in FALLBACK_MESSAGE, so the two cannot drift apart.
FALLBACK_URL = "linkedin.com/in/christiandrocha"


def classify_output(text: str) -> OutputClass:
    """Which of ADR-020's four classes one output belongs to."""
    trimmed = text.strip()
    if not trimmed:
        return "empty"
    if trimmed == FALLBACK_MESSAGE:
        return "fallback"
    if FALLBACK_URL in text:
        return "non_compliant_refusal"
    return "answer"
