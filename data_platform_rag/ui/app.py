"""The page a visitor asks on (ADR-021).

All the work is `generation.answer.answer()`: retrieve, generate, classify, one
`query_log` row and one Langfuse trace. The page only draws a form and shows the
`AnswerResult`: `shown_text` for every class, and the sources under an answer.

Without `ANTHROPIC_API_KEY` the page says so and draws no form, so nothing runs.
That is also the deploy gate in practice: the key is not added to Streamlit
Cloud before ADR-020 is Accepted (DESIGN D7).
"""

from __future__ import annotations

import streamlit as st

from data_platform_rag.contracts import AnswerResult, RetrievedSource
from data_platform_rag.generation.client import LLMClient

NOT_CONFIGURED = "Generation is not configured: ANTHROPIC_API_KEY is empty."
LOGGED_NOTICE = "Questions are logged to improve the answers."


def source_lines(sources: list[RetrievedSource]) -> list[str]:
    """One line per cited section, deduplicated in rank order.

    Two chunks of the same section are one citation to the visitor, so the line
    carries what identifies a section: project, path, ADR id and section, each
    only when present.
    """
    lines: list[str] = []
    for source in sources:
        parts = [source.source_project, f"`{source.source_path}`"]
        if source.adr_id:
            parts.append(source.adr_id)
        if source.source_anchor:
            parts.append(source.source_anchor)
        line = " · ".join(parts)
        if line not in lines:
            lines.append(line)
    return lines


@st.cache_resource
def _client(api_key: str) -> LLMClient:
    from data_platform_rag.generation.sdk import build_client

    return build_client(api_key)


def _show(result: AnswerResult) -> None:
    st.markdown(result.shown_text)
    if result.output_class == "answer" and not result.failed:
        st.markdown("**Sources**")
        st.markdown("\n".join(f"- {line}" for line in source_lines(result.sources)))


def main() -> None:
    from data_platform_rag.config import get_settings_without_llm
    from data_platform_rag.generation import answer as product

    st.set_page_config(page_title="data-platform-rag", page_icon="🧭", layout="centered")
    st.title("data-platform-rag")
    st.caption("Ask about the architecture decisions of a two-pipeline data platform.")

    settings = get_settings_without_llm()
    api_key = settings.anthropic_api_key.get_secret_value()
    if not api_key:
        st.info(NOT_CONFIGURED)
        return

    with st.form("ask"):
        question = st.text_area("Your question", max_chars=settings.max_question_chars)
        submitted = st.form_submit_button("Ask")
    st.caption(LOGGED_NOTICE)

    if not submitted:
        return
    try:
        with st.spinner("Thinking..."):
            result = product.answer(question.strip(), _client(api_key))
    except ValueError as error:
        # Only a rejected question raises, before anything runs (DESIGN D5).
        st.warning(str(error))
        return
    _show(result)


if __name__ == "__main__":
    main()
