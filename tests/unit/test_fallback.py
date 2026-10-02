"""classify_output: the four classes ADR-020 reads, fixed before any call."""

from __future__ import annotations

from data_platform_rag.generation.fallback import FALLBACK_URL, classify_output
from data_platform_rag.generation.prompt import FALLBACK_MESSAGE


def test_the_exact_message_is_a_fallback() -> None:
    assert classify_output(FALLBACK_MESSAGE) == "fallback"


def test_surrounding_whitespace_is_trimmed() -> None:
    assert classify_output(f"\n  {FALLBACK_MESSAGE}\n\n") == "fallback"


def test_a_paraphrase_with_the_url_is_non_compliant() -> None:
    paraphrase = (
        "I can't answer that from the ADRs. Please ask Christian on LinkedIn: "
        "https://linkedin.com/in/christiandrocha"
    )
    assert classify_output(paraphrase) == "non_compliant_refusal"


def test_the_message_with_extra_text_is_non_compliant() -> None:
    """Rule 3 says verbatim. A fallback plus commentary is not the fixed message."""
    assert classify_output(f"{FALLBACK_MESSAGE} Sorry!") == "non_compliant_refusal"


def test_an_answer_is_an_answer() -> None:
    answer = "Snowpipe Streaming was chosen for latency (ADR-0029, sdd-kafka-snowflake-2)."
    assert classify_output(answer) == "answer"


def test_mentioning_linkedin_without_the_url_is_an_answer() -> None:
    assert classify_output("Christian is on LinkedIn, ask him there.") == "answer"


def test_empty_and_whitespace_only_are_empty() -> None:
    """DEFINE Amendment 1: a class of its own, checked first."""
    assert classify_output("") == "empty"
    assert classify_output(" \n\t ") == "empty"


def test_the_url_constant_is_in_the_fallback_message() -> None:
    assert FALLBACK_URL in FALLBACK_MESSAGE
