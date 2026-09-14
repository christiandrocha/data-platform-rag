"""Tests for the system prompt."""

from data_platform_rag.generation.prompt import (
    FALLBACK_MESSAGE,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_VERSION,
)


def test_prompt_is_versioned():
    assert SYSTEM_PROMPT_VERSION.startswith("v")


def test_prompt_requires_citations():
    assert "cite each claim" in SYSTEM_PROMPT.lower()


def test_prompt_forbids_general_knowledge_fallback():
    assert "general knowledge" in SYSTEM_PROMPT.lower()


def test_fallback_message_points_to_linkedin():
    assert "linkedin.com/in/christiandrocha" in FALLBACK_MESSAGE
