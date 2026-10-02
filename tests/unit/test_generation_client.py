"""generation.client with a stub: what is sent, and what comes back. No network."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from data_platform_rag.config import get_settings
from data_platform_rag.contracts import ChunkMetadata, RetrievedChunk
from data_platform_rag.generation.client import build_user_message, generate
from data_platform_rag.generation.prompt import SYSTEM_PROMPT


def chunk(
    rank: int,
    content: str,
    *,
    adr_id="ADR-007",
    anchor="Decision",
    project="sdd-kafka-databricks",
    path="docs/adr/ADR-007.md",
) -> RetrievedChunk:
    return RetrievedChunk(
        id=rank,
        content=content,
        metadata=ChunkMetadata(
            source_project=project,
            source_type="adr",
            source_path=path,
            source_anchor=anchor,
            adr_id=adr_id,
            chunk_index=0,
            token_count=10,
        ),
        dense_distance=0.2,
        dense_rank=rank,
    )


class StubClient:
    """Records the kwargs of each call and returns a canned response."""

    def __init__(self, blocks=None, stop_reason="end_turn"):
        self.calls: list[dict] = []
        self.blocks = blocks if blocks is not None else [SimpleNamespace(type="text", text="ok")]
        self.stop_reason = stop_reason
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=self.blocks,
            model="claude-sonnet-4-6",
            stop_reason=self.stop_reason,
            usage=SimpleNamespace(input_tokens=1234, output_tokens=56),
        )


def test_the_call_uses_the_system_prompt_and_settings() -> None:
    stub = StubClient()
    generate("Why?", [chunk(1, "body")], stub)
    (call,) = stub.calls
    settings = get_settings()
    assert call["system"] == SYSTEM_PROMPT
    assert call["model"] == settings.llm_model
    assert call["temperature"] == settings.llm_temperature == 0.0
    assert call["max_tokens"] == settings.llm_max_tokens == 1024
    assert "thinking" not in call


def test_the_user_message_carries_chunks_in_rank_order_then_the_question() -> None:
    stub = StubClient()
    chunks = [
        chunk(1, "first body", adr_id="ADR-0029", project="sdd-kafka-snowflake-2"),
        chunk(2, "second body", adr_id="ADR-007"),
    ]
    generate("Why Snowpipe?", chunks, stub)
    (message,) = stub.calls[0]["messages"]
    assert message["role"] == "user"
    text = message["content"]
    assert text == build_user_message("Why Snowpipe?", chunks)
    first, second = text.index("first body"), text.index("second body")
    assert first < second < text.index("Question: Why Snowpipe?")
    assert text.endswith("Question: Why Snowpipe?")
    # Rule 2 cites these verbatim: never padded or normalized.
    assert 'adr="ADR-0029"' in text and 'adr="ADR-007"' in text
    assert 'project="sdd-kafka-snowflake-2"' in text


def test_a_chunk_without_adr_or_anchor_omits_those_attributes() -> None:
    text = build_user_message("Q", [chunk(1, "readme body", adr_id=None, anchor=None)])
    assert "adr=" not in text
    assert "section=" not in text
    assert 'project="sdd-kafka-databricks"' in text


def test_attribute_values_are_escaped() -> None:
    text = build_user_message("Q", [chunk(1, "b", anchor='A "quoted" <section>')])
    assert 'section="A &quot;quoted&quot; &lt;section&gt;"' in text


def test_text_blocks_are_joined_and_others_skipped() -> None:
    stub = StubClient(
        blocks=[
            SimpleNamespace(type="text", text="Part one. "),
            SimpleNamespace(type="thinking", thinking="hidden"),
            SimpleNamespace(type="text", text="Part two."),
        ]
    )
    assert generate("Q", [chunk(1, "b")], stub).text == "Part one. Part two."


def test_usage_stop_reason_and_model_are_recorded() -> None:
    result = generate("Q", [chunk(1, "b")], StubClient(stop_reason="max_tokens"))
    assert result.input_tokens == 1234
    assert result.output_tokens == 56
    assert result.stop_reason == "max_tokens"
    assert result.model == "claude-sonnet-4-6"


def test_no_content_blocks_gives_empty_text() -> None:
    assert generate("Q", [chunk(1, "b")], StubClient(blocks=[])).text == ""


def test_empty_chunks_raise_before_any_call() -> None:
    stub = StubClient()
    with pytest.raises(ValueError):
        generate("Q", [], stub)
    assert stub.calls == []


def test_explicit_parameters_override_settings() -> None:
    stub = StubClient()
    generate("Q", [chunk(1, "b")], stub, model="m", temperature=0.5, max_tokens=10)
    call = stub.calls[0]
    assert (call["model"], call["temperature"], call["max_tokens"]) == ("m", 0.5, 10)
