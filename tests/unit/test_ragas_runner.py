"""Stage 2 against RAGAS 0.4's own metric code, with a fake judge (DESIGN D3).

RAGAS's judge interface is `agenerate(prompt, response_model) -> response_model`.
`FakeJudge` answers each response model with a prepared instance, so every score
below is computed by RAGAS itself: the statement split and NLI verdicts of
faithfulness, the cosine of answer relevancy, the average precision of context
precision, the attribution ratio of context recall. Nothing calls an API.

The expected numbers follow from the prepared verdicts:
- faithfulness: 2 statements, verdicts [1, 0] -> 0.5
- answer relevancy: every embedding is the same vector -> cosine 1.0
- context precision: verdicts [1, 0, 1] -> (1/1 + 2/3) / 2 = 0.8333...
- context recall: attributions [1, 1, 0] -> 2/3
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from ragas.embeddings.base import BaseRagasEmbedding
from ragas.llms.base import InstructorBaseRagasLLM
from ragas.metrics.collections.answer_relevancy.util import AnswerRelevanceOutput
from ragas.metrics.collections.context_precision.util import ContextPrecisionOutput
from ragas.metrics.collections.context_recall.util import (
    ContextRecallClassification,
    ContextRecallOutput,
)
from ragas.metrics.collections.faithfulness.util import (
    NLIStatementOutput,
    StatementFaithfulnessAnswer,
    StatementGeneratorOutput,
)

from data_platform_rag.config import get_settings
from data_platform_rag.contracts import (
    METRIC_NAMES,
    AnswerResult,
    EvalProvenance,
    EvalRecord,
    EvalRun,
    GenerationResult,
    GoldenQuestion,
    RetrievedSource,
)
from data_platform_rag.evaluation import ragas_runner
from data_platform_rag.evaluation.langfuse_scorer import ScorePusher
from data_platform_rag.generation.answer import FAILED_MESSAGE
from data_platform_rag.generation.prompt import (
    CONTEXT_FORMAT_VERSION,
    FALLBACK_MESSAGE,
    SYSTEM_PROMPT_VERSION,
)

BREAKS = "BREAK-THIS-ONE"


class FakeJudge(InstructorBaseRagasLLM):
    """Prepared answers per response model. Raises on a prompt containing BREAKS
    for the response model named in `break_on`, and returns no statements when
    the prompt contains "NO-STATEMENTS"."""

    def __init__(self, break_on: type | None = None):
        self.break_on = break_on
        self.calls: list[str] = []

    def generate(self, prompt, response_model):
        raise AssertionError("RAGAS 0.4 metrics call agenerate")

    async def agenerate(self, prompt, response_model):
        self.calls.append(response_model.__name__)
        if response_model is self.break_on and BREAKS in prompt:
            raise RuntimeError("judge reply failed validation")
        if response_model is StatementGeneratorOutput:
            if "NO-STATEMENTS" in prompt:
                return StatementGeneratorOutput(statements=[])
            return StatementGeneratorOutput(statements=["A is chosen.", "B is rejected."])
        if response_model is NLIStatementOutput:
            return NLIStatementOutput(
                statements=[
                    StatementFaithfulnessAnswer(statement="A is chosen.", reason="r", verdict=1),
                    StatementFaithfulnessAnswer(statement="B is rejected.", reason="r", verdict=0),
                ]
            )
        if response_model is AnswerRelevanceOutput:
            return AnswerRelevanceOutput(question="Why was A chosen?", noncommittal=0)
        if response_model is ContextPrecisionOutput:
            verdict = 0 if "chunk B" in prompt else 1
            return ContextPrecisionOutput(reason="r", verdict=verdict)
        if response_model is ContextRecallOutput:
            return ContextRecallOutput(
                classifications=[
                    ContextRecallClassification(statement=s, reason="r", attributed=a)
                    for s, a in (("s1", 1), ("s2", 1), ("s3", 0))
                ]
            )
        raise AssertionError(f"unexpected response model {response_model}")


class SameVector(BaseRagasEmbedding):
    def embed_text(self, text, **kwargs):
        return [1.0, 0.0, 0.0]

    async def aembed_text(self, text, **kwargs):
        return self.embed_text(text)


class RecordingLangfuse:
    def __init__(self, raises: bool = False):
        self.raises, self.scores = raises, []

    def score(self, **kwargs):
        if self.raises:
            raise ConnectionError("langfuse down")
        self.scores.append(kwargs)


def source(rank: int) -> RetrievedSource:
    return RetrievedSource(
        chunk_id=rank,
        source_project="sdd-kafka-databricks",
        source_path=f"docs/adr/{rank}.md",
        source_anchor="Decision",
        adr_id="ADR-001",
        dense_distance=0.1 * rank,
    )


def record(
    qid: str,
    *,
    in_scope: bool = True,
    output_class="answer",
    failed: bool = False,
    question: str = "Why A?",
) -> EvalRecord:
    shown = {
        "answer": "A is chosen [databricks ADR-001]. B is rejected.",
        "fallback": FALLBACK_MESSAGE,
    }.get(output_class, FAILED_MESSAGE)
    result = AnswerResult(
        question=question,
        failed=failed,
        output_class=None if failed else output_class,
        shown_text=FAILED_MESSAGE if failed else shown,
        sources=[] if failed else [source(1), source(2), source(3)],
        generation=None
        if failed
        else GenerationResult(
            text=shown,
            model="claude-sonnet-4-6",
            stop_reason="end_turn",
            input_tokens=900,
            output_tokens=40,
        ),
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        context_format_version=CONTEXT_FORMAT_VERSION,
        latency_ms=1000,
        trace_id=f"trace-{qid}",
        logged=True,
    )
    return EvalRecord(
        question=GoldenQuestion(
            id=qid,
            intent="decision" if in_scope else "out-of-scope",
            question=question,
            expected_answer="A is chosen because of X." if in_scope else None,
        ),
        result=result,
        contexts=[] if failed else ["chunk A", "chunk B", "chunk C"],
    )


def provenance() -> EvalProvenance:
    return EvalProvenance(
        created_at=datetime(2026, 10, 5, tzinfo=UTC),
        golden_set_sha="a" * 40,
        golden_set_dirty=False,
        corpus_commits=["sdd-kafka-databricks@" + "f" * 40],
        embedding_model="BAAI/bge-small-en-v1.5",
        generation_model="claude-sonnet-4-6",
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        context_format_version=CONTEXT_FORMAT_VERSION,
        rerank_top_k=3,
    )


def run_of(*records: EvalRecord) -> EvalRun:
    return EvalRun(run_id="eval-run-test", provenance=provenance(), records=list(records))


def score(*records, judge=None, langfuse=None, existing=None, metrics=None):
    judge = judge or FakeJudge()
    written = []
    metrics = metrics or ragas_runner.build_metrics(judge, SameVector(), strictness=3)
    report = ragas_runner.score_run(
        run_of(*records),
        "run.json",
        metrics,
        ragas_runner.judge_config(get_settings()),
        ScorePusher(langfuse or RecordingLangfuse(), "eval-run-test"),
        write=written.append,
        existing=existing,
    )
    return report, written, judge


# ─── The metrics, computed by RAGAS ──────────────────────────────────────────


def test_an_in_scope_answer_gets_four_scores_from_ragas_itself():
    report, _, _ = score(record("q1"))
    metrics = report.reports[0].metrics
    assert metrics["faithfulness"].value == pytest.approx(0.5)
    assert metrics["answer_relevancy"].value == pytest.approx(1.0)
    assert metrics["context_precision"].value == pytest.approx((1 + 2 / 3) / 2)
    assert metrics["context_recall"].value == pytest.approx(2 / 3)
    assert report.reports[0].fallback_correct is None


def test_answer_relevancy_asks_the_judge_strictness_times():
    _, _, judge = score(record("q1"))
    assert judge.calls.count("AnswerRelevanceOutput") == 3


def test_an_out_of_scope_record_gets_fallback_correct_only_and_no_judge_call():
    report, _, judge = score(record("oos1", in_scope=False, output_class="fallback"))
    only = report.reports[0]
    assert only.metrics is None
    assert only.fallback_correct is True
    assert judge.calls == []


def test_an_out_of_scope_answer_is_not_a_correct_fallback():
    report, _, _ = score(record("oos1", in_scope=False, output_class="answer"))
    assert report.reports[0].fallback_correct is False


# ─── Missing, never zero (ADR-008, Decision 5) ───────────────────────────────


def test_a_judge_failure_on_one_metric_of_one_question_is_one_missing_value():
    broken = record("q2", question=f"Why A? {BREAKS}")
    report, _, _ = score(record("q1"), broken, judge=FakeJudge(break_on=ContextRecallOutput))
    recall = report.reports[1].metrics["context_recall"]
    assert recall.value is None
    assert "judge reply failed validation" in recall.error
    assert report.reports[1].metrics["faithfulness"].value == pytest.approx(0.5)
    agg = report.aggregate.metrics["context_recall"]
    assert (agg.n_scored, agg.n_expected) == (1, 2)
    assert agg.mean == pytest.approx(2 / 3)


def test_nan_from_ragas_is_a_missing_value_not_a_zero():
    report, _, _ = score(record("q1", question="Why A? NO-STATEMENTS"))
    faithfulness = report.reports[0].metrics["faithfulness"]
    assert faithfulness.value is None
    assert faithfulness.error == "RAGAS returned NaN"


def test_a_failed_generation_has_four_missing_values_and_no_judge_call():
    report, _, judge = score(record("q1", failed=True))
    assert {m.error for m in report.reports[0].metrics.values()} == {"generation failed"}
    assert judge.calls == []
    assert all(a.mean is None for a in report.aggregate.metrics.values())


def test_a_value_outside_0_1_is_a_missing_value():
    class Negative:
        async def ascore(self, **kwargs):
            return type("R", (), {"value": -0.2})()

    real = ragas_runner.build_metrics(FakeJudge(), SameVector(), strictness=3)
    metrics = ragas_runner.Metrics(
        faithfulness=real.faithfulness,
        answer_relevancy=Negative(),
        context_precision=real.context_precision,
        context_recall=real.context_recall,
    )
    report, _, _ = score(record("q1"), metrics=metrics)
    assert "outside [0, 1]" in report.reports[0].metrics["answer_relevancy"].error


# ─── In-scope fallbacks are scored and counted (DESIGN D8) ────────────────────


def test_an_in_scope_fallback_is_scored_and_counted():
    report, _, judge = score(record("q1"), record("q2", output_class="fallback"))
    assert report.reports[1].metrics is not None
    assert report.reports[1].fallback_fired is True
    assert report.aggregate.in_scope_fallbacks == 1
    assert report.aggregate.n_in_scope == 2


# ─── Writing, resuming, Langfuse ─────────────────────────────────────────────


def test_the_report_is_written_after_every_question():
    _, written, _ = score(record("q1"), record("q2"), record("oos1", in_scope=False))
    assert [len(r.reports) for r in written] == [1, 2, 3, 3]


def test_resume_keeps_scored_records_and_scores_only_the_rest():
    first, _, _ = score(record("q1"))
    report, _, judge = score(record("q1"), record("q2"), existing=first)
    assert report.reports[0] == first.reports[0]
    assert judge.calls.count("StatementGeneratorOutput") == 1  # q2 only


def test_resume_refuses_a_report_from_another_judge():
    first, _, _ = score(record("q1"))
    other = first.model_copy(
        update={"judge": first.judge.model_copy(update={"model": "claude-haiku-4-5"})}
    )
    with pytest.raises(ValueError, match="different judge"):
        score(record("q1"), existing=other)


def test_scores_go_to_the_records_trace():
    langfuse = RecordingLangfuse()
    report, _, _ = score(
        record("q1"), record("oos1", in_scope=False, output_class="fallback"), langfuse=langfuse
    )
    names = [(s["trace_id"], s["name"]) for s in langfuse.scores]
    assert names == [("trace-q1", f"ragas_{m}") for m in METRIC_NAMES] + [
        ("trace-oos1", "fallback_correct")
    ]
    assert all(r.pushed_to_langfuse for r in report.reports)


def test_langfuse_down_changes_nothing_but_the_pushed_flag():
    up, _, _ = score(record("q1"))
    down, _, _ = score(record("q1"), langfuse=RecordingLangfuse(raises=True))
    assert down.reports[0].metrics == up.reports[0].metrics
    assert down.reports[0].pushed_to_langfuse is False


# ─── Telemetry, judge, embeddings ────────────────────────────────────────────


def test_telemetry_is_off_unless_explicitly_opted_in(monkeypatch):
    monkeypatch.delenv("RAGAS_DO_NOT_TRACK", raising=False)
    ragas_runner.disable_ragas_telemetry()
    import os

    assert os.environ["RAGAS_DO_NOT_TRACK"] == "true"
    monkeypatch.setenv("RAGAS_DO_NOT_TRACK", "false")
    ragas_runner.disable_ragas_telemetry()
    assert os.environ["RAGAS_DO_NOT_TRACK"] == "false"


def test_the_judge_is_async_at_temperature_0_without_top_p():
    judge = ragas_runner.build_judge(get_settings(), "test-not-a-real-key")
    assert judge.is_async
    assert judge.model == get_settings().judge_model == "claude-opus-5-5"
    assert judge.model_args["temperature"] == 0.0
    assert judge.model_args["max_tokens"] == get_settings().judge_max_tokens
    assert "top_p" not in judge.model_args


def test_the_embeddings_are_the_retrieval_query_embedding(monkeypatch):
    monkeypatch.setattr("data_platform_rag.retrieval.pipeline.embed_query", lambda text: (0.6, 0.8))
    embeddings = ragas_runner.build_embeddings()
    assert embeddings.embed_text("Why A?") == [0.6, 0.8]
    assert not math.isnan(sum(embeddings.embed_texts(["a", "b"])[1]))
