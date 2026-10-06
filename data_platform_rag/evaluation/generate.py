"""Stage 1 of `make eval`: an answer for every golden-set question (ADR-008).

Each question goes through the product path, `answer(..., origin="eval")`, so it
writes a real `query_log` row and a real trace, which its scores attach to in
stage 2. The text of each retrieved chunk is read by id right after its answer
(DESIGN D2): `AnswerResult` carries citations only, and the product contract does
not grow evaluation data.

The run file is rewritten after every question, so a failure late in the run
keeps the answers already paid for.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from data_platform_rag.config import Settings
from data_platform_rag.contracts import (
    AnswerResult,
    EvalProvenance,
    EvalRecord,
    EvalRun,
    GoldenQuestion,
)
from data_platform_rag.generation.client import LLMClient
from data_platform_rag.generation.prompt import CONTEXT_FORMAT_VERSION, SYSTEM_PROMPT_VERSION

if TYPE_CHECKING:  # pragma: no cover - typing only
    import psycopg

logger = logging.getLogger(__name__)

ConnectFn = Callable[[], "psycopg.Connection"]
AnswerFn = Callable[..., AnswerResult]


class StaleIndexError(Exception):
    """A retrieved chunk is gone: the index changed during the run."""


def run_id_for(now: datetime) -> str:
    return f"eval-run-{now:%Y%m%d-%H%M%S}"


def read_provenance(
    conn: psycopg.Connection,
    settings: Settings,
    golden_set_sha: str,
    golden_set_dirty: bool,
    now: datetime,
) -> EvalProvenance:
    """What the run is made from. The corpus side is read from what is indexed."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_project || '@' || commit_sha, embedding_model"
            " FROM corpus_snapshot ORDER BY 1"
        )
        rows = cur.fetchall()
    models = {row[1] for row in rows}
    if not rows:
        raise StaleIndexError("corpus_snapshot is empty: index the corpus before a run.")
    if len(models) != 1:
        raise StaleIndexError(f"the indexed projects disagree on the embedding model: {models}")
    return EvalProvenance(
        created_at=now,
        golden_set_sha=golden_set_sha,
        golden_set_dirty=golden_set_dirty,
        corpus_commits=[row[0] for row in rows],
        embedding_model=models.pop(),
        generation_model=settings.llm_model,
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        context_format_version=CONTEXT_FORMAT_VERSION,
        rerank_top_k=settings.rerank_top_k,
    )


def read_contexts(conn: psycopg.Connection, chunk_ids: list[int]) -> list[str]:
    """The text of each chunk, in the order given. A missing id raises."""
    if not chunk_ids:
        return []
    with conn.cursor() as cur:
        cur.execute("SELECT id, content FROM chunks WHERE id = ANY(%s)", (chunk_ids,))
        content = dict(cur.fetchall())
    missing = [i for i in chunk_ids if i not in content]
    if missing:
        raise StaleIndexError(f"chunks {missing} are no longer indexed: was the corpus reindexed?")
    return [content[i] for i in chunk_ids]


def write_run(run: EvalRun, path: Path) -> None:
    """Replace the file in one rename, so a reader never sees half a run."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def generate_run(
    questions: list[GoldenQuestion],
    client: LLMClient,
    provenance: EvalProvenance,
    *,
    connect_fn: ConnectFn,
    out_path: Path,
    answer_fn: AnswerFn | None = None,
) -> EvalRun:
    """Answer every question and write the run file after each one.

    A failed answer is recorded as failed and the run continues: stage 2 records
    its metrics as missing. A chunk that vanished mid-run stops the run, because
    the answers before and after it were built from different indexes.
    """
    if answer_fn is None:
        from data_platform_rag.generation.answer import answer as answer_fn

    run = EvalRun(run_id=out_path.stem, provenance=provenance, records=[])
    for number, question in enumerate(questions, start=1):
        result = answer_fn(question.question, client, connect_fn=connect_fn, origin="eval")
        conn = connect_fn()
        try:
            contexts = read_contexts(conn, [s.chunk_id for s in result.sources])
        finally:
            conn.close()
        record = EvalRecord(question=question, result=result, contexts=contexts)
        run = run.model_copy(update={"records": [*run.records, record]})
        write_run(run, out_path)
        state = "failed" if result.failed else result.output_class
        logger.info("%d/%d %s: %s", number, len(questions), question.id, state)
    return run


def now_utc() -> datetime:
    return datetime.now(UTC)
