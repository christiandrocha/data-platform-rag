"""Reranker — reorders the RRF candidates with a cross-encoder. ADR-005.

A cross-encoder reads the question and the chunk together, where the embedder
reads them apart. That is what the order at the top of the RRF list lacks: on the
recorded baseline q002's declared ADR sits at rank 7 and q003's `0030` at rank 5,
both below the `settings.rerank_top_k` chunks generation will receive.

Which model does it is ADR-005's decision, made by a rule fixed before the
measurement. The model is `settings.reranker_model`; every candidate runs through
this code, and nothing here names one.

The score is `predict`'s raw output and is not on a common scale across models:
MiniLM-L-6 returns logits, bge-reranker-base a sigmoid. Nothing here compares a
score against a constant, and nothing should until a fallback ADR says how.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from data_platform_rag.config import get_settings_without_llm
from data_platform_rag.contracts import RerankedChunk

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from sentence_transformers import CrossEncoder

    from data_platform_rag.contracts import RetrievedChunk

_INSTALL_HINT = (
    "  pip install sentence-transformers    # the full runtime, per pyproject\n"
    "  A first run needs network access to fetch the model weights; cached after."
)


@lru_cache(maxsize=1)
def get_model() -> CrossEncoder:
    """Load the reranker once per process.

    Measured in ADR-005: 5.0 s from cache for MiniLM-L-6, 6.2 s for
    bge-reranker-base, paid on the first rerank. Not silent about failing, for the
    embedder's reason: a reranker that degraded to "no reranking" would return
    RRF order under a rerank score's name.
    """
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise SystemExit(
            f"ERROR: sentence-transformers is not installed, so nothing can be "
            f"reranked.\n{_INSTALL_HINT}"
        ) from exc

    model_name = get_settings_without_llm().reranker_model
    try:
        return CrossEncoder(model_name)
    except Exception as exc:  # pragma: no cover - network/cache-dependent
        raise SystemExit(
            f"ERROR: could not load the reranker model {model_name!r}: {exc}\n{_INSTALL_HINT}"
        ) from exc


def rerank(
    question: str,
    candidates: Sequence[RetrievedChunk],
    top_k: int | None = None,
) -> list[RerankedChunk]:
    """Score every candidate against the question, reorder, keep the first top_k.

    `top_k=None` means `settings.rerank_top_k`. A caller that needs the whole
    reordering -- the recall script -- passes `len(candidates)`.

    A pair longer than the model's window is scored on its truncated form and
    flagged, not dropped: dropping would shrink the candidate set, and recall
    would then move by removal rather than by ranking. ADR-007 caps chunks under
    the embedder's tokenizer; this is the check that the cap holds under the
    reranker's.

    Ties break by RRF score, then id. The RRF list is already id-tiebroken, but
    this key does not rely on the input arriving in that order.
    """
    if not candidates:
        return []  # before get_model(): an empty retrieval must not cost a model load
    if top_k is None:
        top_k = get_settings_without_llm().rerank_top_k
    if top_k < 1:
        raise ValueError(f"top_k must be >= 1, got {top_k}")

    model = get_model()
    pairs = [(question, chunk.content) for chunk in candidates]
    scores = model.predict(pairs, show_progress_bar=False)
    window = model.max_seq_length
    lengths = [
        len(model.tokenizer(q, text, truncation=False, verbose=False)["input_ids"])
        for q, text in pairs
    ]

    reranked = [
        RerankedChunk(
            **chunk.model_dump(),
            rerank_score=float(score),
            truncated=length > window,
        )
        for chunk, score, length in zip(candidates, scores, lengths, strict=True)
    ]
    reranked.sort(key=lambda c: (-c.rerank_score, -c.rrf_score, c.id))
    return reranked[:top_k]
