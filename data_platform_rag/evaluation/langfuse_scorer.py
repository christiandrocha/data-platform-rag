"""RAGAS scores to Langfuse, on the trace that produced the answer (ADR-008).

AGENTS.md: one score system for evaluation and production, and never block on
Langfuse. Every call here catches, logs one warning and reports `False`, as
`observability/tracing.py` does for traces. A missing value is not pushed: there
is no number to send, and sending 0 would invent one.
"""

from __future__ import annotations

import logging
from typing import Protocol

from data_platform_rag.contracts import RAGASReport

logger = logging.getLogger(__name__)

SCORE_PREFIX = "ragas_"


class _ScoringClient(Protocol):
    def score(self, **kwargs: object) -> object: ...


class ScorePusher:
    """Pushes one question's scores. Never raises."""

    def __init__(self, client: _ScoringClient, run_id: str) -> None:
        self._client = client
        self._run_id = run_id

    def push(self, report: RAGASReport) -> bool:
        """True when the question has a trace and every score was accepted."""
        if report.trace_id is None:
            return False
        ok = True
        for name, metric in (report.metrics or {}).items():
            if metric.value is None:
                continue
            ok &= self._score(report, SCORE_PREFIX + name, metric.value, "NUMERIC")
        if report.fallback_correct is not None:
            ok &= self._score(
                report, "fallback_correct", 1.0 if report.fallback_correct else 0.0, "BOOLEAN"
            )
        return ok

    def _score(self, report: RAGASReport, name: str, value: float, data_type: str) -> bool:
        try:
            self._client.score(
                trace_id=report.trace_id,
                name=name,
                value=value,
                data_type=data_type,
                comment=f"{self._run_id} {report.question_id}",
            )
            return True
        except Exception as exc:  # noqa: BLE001 - never block on Langfuse
            logger.warning("langfuse score %s on %s failed: %s", name, report.question_id, exc)
            return False


def get_pusher(run_id: str) -> ScorePusher:
    from data_platform_rag.observability.langfuse_client import get_client

    return ScorePusher(get_client(), run_id)
