"""Stage 2 of `make eval`: score a run file with RAGAS (ADR-008).

The one module that imports `ragas`, lazily, after `RAGAS_DO_NOT_TRACK` is set:
RAGAS reports usage to its maintainers by default (ADR-008, Decision 10).

- **In-scope questions** get four metrics from RAGAS 0.4's own code:
  faithfulness, answer relevancy, context precision with reference, context recall.
- **Out-of-scope questions** get `fallback_correct` only. Two of the four metrics
  need a reference answer they do not have.
- **No invented score** (Decision 5): a metric that raises, returns NaN or
  leaves [0, 1], or a question whose generation failed, is a `MetricValue` with
  the reason, never a 0.

The judge is Claude (`settings.judge_model`) on an async client, through RAGAS's
`llm_factory`. The embeddings are the retrieval model's, via `embed_query`.
Metrics run one question at a time, all in **one** event loop: the async client's
connection pool belongs to the loop that opened it, so a loop per question would
fail from the second question on. The report is written after each question, so
a failure keeps every score already paid for and a rerun resumes.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from data_platform_rag.config import Settings
from data_platform_rag.contracts import (
    METRIC_NAMES,
    EvalRecord,
    EvalReport,
    EvalRun,
    JudgeConfig,
    MetricName,
    MetricValue,
    RAGASReport,
)
from data_platform_rag.evaluation.langfuse_scorer import ScorePusher
from data_platform_rag.evaluation.report import aggregate

logger = logging.getLogger(__name__)

# Bounds what one failure writes into the report.
ERROR_MAX_CHARS = 300

# The judge runs deterministic-leaning, like the generator (settings.llm_temperature).
# RAGAS's own default also sends top_p, and recent Claude models refuse a request
# that sets both; dropping top_p avoids that whatever the model does (BUILD_REPORT).
JUDGE_TEMPERATURE = 0.0


def disable_ragas_telemetry() -> None:
    """The one place `RAGAS_DO_NOT_TRACK` is written. An explicit opt-in is kept."""
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")


def ragas_version() -> str:
    disable_ragas_telemetry()
    import ragas

    return ragas.__version__


def judge_config(settings: Settings) -> JudgeConfig:
    return JudgeConfig(
        model=settings.judge_model,
        max_tokens=settings.judge_max_tokens,
        temperature=JUDGE_TEMPERATURE,
        ragas_version=ragas_version(),
        answer_relevancy_strictness=settings.answer_relevancy_strictness,
    )


def build_judge(settings: Settings, api_key: str) -> Any:  # noqa: ANN401 - a RAGAS LLM
    """Claude as RAGAS's judge, on `AsyncAnthropic` (DESIGN D5)."""
    disable_ragas_telemetry()
    from ragas.llms import llm_factory

    from data_platform_rag.generation.sdk import build_async_client

    llm = llm_factory(
        settings.judge_model,
        provider="anthropic",
        client=build_async_client(api_key),
        max_tokens=settings.judge_max_tokens,
        temperature=JUDGE_TEMPERATURE,
    )
    llm.model_args.pop("top_p", None)
    return llm


def build_embeddings() -> Any:  # noqa: ANN401 - a RAGAS embedding
    """The retrieval model's query embedding, as RAGAS's embedding (DESIGN D6).

    Answer relevancy compares the question with questions generated from the
    answer, so the query-side embedding is the right one for both. The class is
    built here because its base class lives in `ragas`, imported lazily.
    """
    disable_ragas_telemetry()
    from ragas.embeddings.base import BaseRagasEmbedding

    from data_platform_rag.retrieval.pipeline import embed_query

    class QueryEmbeddings(BaseRagasEmbedding):
        def embed_text(self, text: str, **kwargs: Any) -> list[float]:  # noqa: ANN401
            return list(embed_query(text))

        async def aembed_text(self, text: str, **kwargs: Any) -> list[float]:  # noqa: ANN401
            return self.embed_text(text)

    return QueryEmbeddings()


@dataclass(frozen=True)
class Metrics:
    """The four RAGAS metric objects, built once per run."""

    faithfulness: Any
    answer_relevancy: Any
    context_precision: Any
    context_recall: Any


def build_metrics(judge: Any, embeddings: Any, strictness: int) -> Metrics:  # noqa: ANN401
    disable_ragas_telemetry()
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    return Metrics(
        faithfulness=Faithfulness(llm=judge),
        answer_relevancy=AnswerRelevancy(llm=judge, embeddings=embeddings, strictness=strictness),
        context_precision=ContextPrecisionWithReference(llm=judge),
        context_recall=ContextRecall(llm=judge),
    )


def _bounded(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:ERROR_MAX_CHARS]


async def _one(metric: Any, **inputs: Any) -> MetricValue:  # noqa: ANN401
    """One metric on one question: a value in [0, 1], or the reason there is none."""
    try:
        result = await metric.ascore(**inputs)
        value = float(result.value)
    except Exception as exc:  # noqa: BLE001 - a failed metric is a missing value
        return MetricValue(error=_bounded(exc))
    if math.isnan(value):
        return MetricValue(error="RAGAS returned NaN")
    if not 0.0 <= value <= 1.0:
        return MetricValue(error=f"RAGAS returned {value}, outside [0, 1]")
    return MetricValue(value=value)


async def _score_in_scope(record: EvalRecord, metrics: Metrics) -> dict[MetricName, MetricValue]:
    result = record.result
    if result.failed:
        missing = MetricValue(error="generation failed")
        return dict.fromkeys(METRIC_NAMES, missing)
    question = record.question.question
    reference = record.question.expected_answer
    response = result.shown_text
    contexts = record.contexts
    return {
        "faithfulness": await _one(
            metrics.faithfulness,
            user_input=question,
            response=response,
            retrieved_contexts=contexts,
        ),
        "answer_relevancy": await _one(
            metrics.answer_relevancy, user_input=question, response=response
        ),
        "context_precision": await _one(
            metrics.context_precision,
            user_input=question,
            reference=reference,
            retrieved_contexts=contexts,
        ),
        "context_recall": await _one(
            metrics.context_recall,
            user_input=question,
            retrieved_contexts=contexts,
            reference=reference,
        ),
    }


async def score_record(record: EvalRecord, metrics: Metrics) -> RAGASReport:
    """One question's report, before the Langfuse push."""
    result = record.result
    in_scope = record.question.in_scope
    return RAGASReport(
        question_id=record.question.id,
        intent=record.question.intent,
        trace_id=result.trace_id,
        metrics=await _score_in_scope(record, metrics) if in_scope else None,
        fallback_fired=result.fallback_fired,
        fallback_correct=None if in_scope else result.fallback_fired,
        pushed_to_langfuse=False,
    )


def score_run(
    run: EvalRun,
    run_file: str,
    metrics: Metrics,
    judge: JudgeConfig,
    pusher: ScorePusher,
    *,
    write: Callable[[EvalReport], None],
    existing: EvalReport | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> EvalReport:
    """Score every record, resuming from `existing`, and write after each one.

    A record already scored in `existing` is kept as it is, unless `existing` was
    scored by a different judge, which makes it not comparable: then it refuses.
    """
    if existing is not None and existing.judge != judge:
        raise ValueError(
            "the existing report was scored by a different judge "
            f"({existing.judge.model}, ragas {existing.judge.ragas_version}); "
            "rescore it from the start"
        )
    done = {r.question_id: r for r in existing.reports} if existing else {}

    async def score_all() -> list[RAGASReport]:
        reports: list[RAGASReport] = []
        for number, record in enumerate(run.records, start=1):
            qid = record.question.id
            if qid in done:
                reports.append(done[qid])
                continue
            scored = await score_record(record, metrics)
            scored = scored.model_copy(update={"pushed_to_langfuse": pusher.push(scored)})
            reports.append(scored)
            write(_report(run, run_file, judge, reports, now()))
            logger.info("%d/%d %s scored", number, len(run.records), qid)
        return reports

    report = _report(run, run_file, judge, asyncio.run(score_all()), now())
    write(report)
    return report


def _report(
    run: EvalRun, run_file: str, judge: JudgeConfig, reports: list[RAGASReport], at: datetime
) -> EvalReport:
    return EvalReport(
        run_id=run.run_id,
        run_file=run_file,
        provenance=run.provenance,
        judge=judge,
        scored_at=at,
        reports=reports,
        aggregate=aggregate(reports),
    )
