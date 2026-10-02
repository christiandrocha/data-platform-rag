"""Generation: retrieved chunks and a question in, one Claude call, text out.

The smallest real generation step, built for ADR-020's measurement of rule 3. It
is the evaluation path: it writes no `query_log` row and no Langfuse trace. The
product path wraps it when the UI is built.

The client is injected. Nothing here constructs an `anthropic.Anthropic` or
imports the SDK, so the package stays importable without `anthropic` installed,
and every test runs on a stub. The one caller that talks to the API,
`scripts/fallback_eval.py`, builds the client after checking for a key.

No `thinking` parameter is sent. On claude-sonnet-4-6, omitting it means no
extended thinking, which is the setting ADR-020 measures.
"""

from __future__ import annotations

from html import escape
from typing import Protocol

from data_platform_rag.config import get_settings
from data_platform_rag.contracts import GenerationResult, RetrievedChunk
from data_platform_rag.generation.prompt import SYSTEM_PROMPT


class MessagesAPI(Protocol):
    def create(self, **kwargs: object) -> object: ...


class LLMClient(Protocol):
    """The part of `anthropic.Anthropic` this module uses. A stub satisfies it."""

    messages: MessagesAPI


def _attr(name: str, value: str | None) -> str:
    """One tag attribute, escaped, or nothing when the value is absent."""
    if value is None:
        return ""
    return f' {name}="{escape(value, quote=True)}"'


def build_user_message(question: str, chunks: list[RetrievedChunk]) -> str:
    """The user message, in `CONTEXT_FORMAT_VERSION` v1.0.0.

    Chunks in retrieval-rank order, each tagged with what rule 2 cites: the
    project, and the ADR id exactly as the chunk carries it (rule 2: never pad
    or normalize). Attributes are escaped so a path or anchor cannot break the
    tag. Chunk content is corpus text and goes in verbatim.
    """
    blocks = []
    for index, chunk in enumerate(chunks, start=1):
        meta = chunk.metadata
        open_tag = (
            f'<chunk index="{index}"'
            f"{_attr('project', meta.source_project)}"
            f"{_attr('source', meta.source_path)}"
            f"{_attr('adr', meta.adr_id)}"
            f"{_attr('section', meta.source_anchor)}>"
        )
        blocks.append(f"{open_tag}\n{chunk.content}\n</chunk>")
    context = "\n".join(blocks)
    return f"<context>\n{context}\n</context>\n\nQuestion: {question}"


def generate(
    question: str,
    chunks: list[RetrievedChunk],
    client: LLMClient,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> GenerationResult:
    """One Claude call under `SYSTEM_PROMPT`. SDK errors propagate.

    Empty `chunks` raises: retrieval never returns nothing from a populated
    index, so empty means a broken one, and a call on no context would measure
    nothing.
    """
    if not chunks:
        raise ValueError("generate needs at least one retrieved chunk")

    settings = get_settings()
    response = client.messages.create(
        model=model or settings.llm_model,
        max_tokens=max_tokens if max_tokens is not None else settings.llm_max_tokens,
        temperature=temperature if temperature is not None else settings.llm_temperature,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_message(question, chunks)}],
    )
    text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    return GenerationResult(
        text=text,
        model=response.model,
        stop_reason=response.stop_reason,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
