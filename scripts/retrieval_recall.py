"""Source recall at k over the golden set. Implements ADR-014.

The project has no RAGAS score and cannot have one yet: RAGAS grades generated
answers, generation does not exist, and the golden set is 5 of 50. ADR-004
(embedding model, HNSW tuning) and ADR-005 (reranking) are both blocked on having
*some* comparable retrieval number.

The golden set already carries one. Every question declares
`expected_source_paths` -- the documents that should ground its answer. That is a
labelled retrieval set, and this script reads it.

A declared path counts as retrieved at k if any chunk in the top k carries that
exact (source_project, source_path). Recall is summed across questions rather
than averaged per question, so a question declaring two paths contributes twice:
it has twice as much to find.

Out-of-scope questions declare no paths and are excluded from the denominator --
correctly retrieving nothing is not a recall event. Their top fused score is
recorded anyway, because ADR-006's `fallback_threshold` is currently an
undefended 0.35 and this is the evidence it needs.

Writes a timestamped JSON artifact. Deliberately not a CI gate: see ADR-014 s4.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from data_platform_rag.config import get_settings, get_settings_without_llm
from data_platform_rag.contracts import RerankedChunk
from data_platform_rag.indexer.writer import connect, current_snapshots
from data_platform_rag.retrieval.pipeline import retrieve
from data_platform_rag.retrieval.reranker import get_model, rerank

GOLDEN_SET = Path("docs/golden-set/evaluation_questions.yml")
REPORT_DIR = Path(".claude/dev/reports")
K_VALUES = (3, 10, 20)
OUT_OF_SCOPE = "out-of-scope"


def load_questions() -> list[dict]:
    questions = yaml.safe_load(GOLDEN_SET.read_text())
    if not isinstance(questions, list):
        raise SystemExit(f"ERROR: {GOLDEN_SET} did not parse as a list of questions.")
    return questions


def ranking_rows(chunks) -> list[dict]:
    """One row per chunk, in order. Reranked chunks also carry their score and flag."""
    rows = []
    for position, chunk in enumerate(chunks, start=1):
        row = {
            "rank": position,
            "project": chunk.metadata.source_project,
            "path": chunk.metadata.source_path,
            "anchor": chunk.metadata.source_anchor,
            "rrf_score": chunk.rrf_score,
            "dense_rank": chunk.dense_rank,
            "sparse_rank": chunk.sparse_rank,
        }
        if isinstance(chunk, RerankedChunk):
            row["rerank_score"] = chunk.rerank_score
            row["truncated"] = chunk.truncated
        rows.append(row)
    return rows


def evaluate(question: dict, max_k: int) -> dict:
    """Retrieve once at max_k, rerank all of it, and read every k off both orderings.

    One retrieval per question, not one per k: the top 3 is a prefix of the top
    20, so retrieving three times would cost three model calls to produce the
    same answer -- and would not even be guaranteed identical if anything about
    retrieval were non-deterministic.

    The reranked ordering is a permutation of the same candidates (ADR-005), so
    recall at max_k is equal before and after by construction. If it is not, the
    stage is wrong.
    """
    chunks = retrieve(question["question"], top_k=max_k)
    started = time.perf_counter()
    reranked = rerank(question["question"], chunks, top_k=len(chunks))
    latency = time.perf_counter() - started
    ranking = ranking_rows(chunks)
    reranked_ranking = ranking_rows(reranked)

    declared = [
        (entry["project"], entry["path"]) for entry in question.get("expected_source_paths") or []
    ]

    def rank_of(rows: list[dict], project: str, path: str, k: int) -> int | None:
        """The position this declared path was found at, or None within top k."""
        for row in rows[:k]:
            if (row["project"], row["path"]) == (project, path):
                return row["rank"]
        return None

    def hits(rows: list[dict]) -> dict[str, dict[str, int | None]]:
        return {
            str(k): {f"{p}/{q}": rank_of(rows, p, q, k) for p, q in declared}
            for k in K_VALUES
        }

    return {
        "id": question["id"],
        "intent": question["intent"],
        "question": question["question"],
        "declared_paths": [f"{p}/{q}" for p, q in declared],
        "top_rrf_score": ranking[0]["rrf_score"] if ranking else None,
        "top_rerank_score": reranked_ranking[0]["rerank_score"] if reranked_ranking else None,
        "retrieved_at_k": hits(ranking),
        "reranked_at_k": hits(reranked_ranking),
        "truncated_pairs": sum(row["truncated"] for row in reranked_ranking),
        "rerank_latency_s": round(latency, 3),
        "ranking": ranking,
        "reranked_ranking": reranked_ranking,
    }


def recall_at(in_scope: list[dict], key: str, denominator: int) -> dict:
    """Recall at each k over one of the two orderings (`retrieved_at_k` or `reranked_at_k`)."""
    recall = {}
    for k in K_VALUES:
        found = sum(
            1 for r in in_scope for rank in r[key][str(k)].values() if rank is not None
        )
        recall[str(k)] = {
            "found": found,
            "declared": denominator,
            "recall": round(found / denominator, 4) if denominator else None,
        }
    return recall


def summarise(results: list[dict]) -> dict:
    """Recall summed over declared paths, per ADR-014, before and after reranking."""
    in_scope = [
        r for r in results if r["intent"] != OUT_OF_SCOPE and r["declared_paths"]
    ]
    denominator = sum(len(r["declared_paths"]) for r in in_scope)
    return {
        "questions_in_scope": len(in_scope),
        "declared_paths": denominator,
        "source_recall_at_k": recall_at(in_scope, "retrieved_at_k", denominator),
        "reranked_recall_at_k": recall_at(in_scope, "reranked_at_k", denominator),
        "top_rrf_scores": {r["id"]: r["top_rrf_score"] for r in results},
        "top_rerank_scores": {r["id"]: r["top_rerank_score"] for r in results},
    }


def indexed_snapshot() -> dict[str, dict[str, str]]:
    """The commit each project's chunks came from (ADR-013).

    Recorded so two artifacts can be shown to measure the same corpus: a recall
    number that cannot name its commit cannot be compared with another one.
    """
    with connect(str(get_settings().database_url)) as conn:
        snapshots = current_snapshots(conn)
    return {
        project: {"commit_sha": s.commit_sha, "embedding_model": s.embedding_model}
        for project, s in sorted(snapshots.items())
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="Print only; write no artifact.")
    args = parser.parse_args()

    questions = load_questions()
    max_k = max(K_VALUES)
    settings = get_settings_without_llm()
    started = time.perf_counter()
    model = get_model()  # loaded before the loop, so no question's latency carries the load
    load_s = time.perf_counter() - started
    results = [evaluate(q, max_k) for q in questions]
    summary = summarise(results)
    snapshot = indexed_snapshot()
    reranker = {
        "model": settings.reranker_model,
        "activation": type(model.activation_fn).__name__,
        "load_s": round(load_s, 3),
        "truncated_pairs": sum(r["truncated_pairs"] for r in results),
    }

    print("Indexed snapshot (ADR-013):")
    for project, row in snapshot.items():
        print(f"  {project}@{row['commit_sha'][:8]}  {row['embedding_model']}")
    print(
        f"Reranker (ADR-005): {reranker['model']}  activation={reranker['activation']}  "
        f"load {reranker['load_s']:.1f} s  truncated pairs {reranker['truncated_pairs']}"
    )
    print()

    print(f"Source recall at k (ADR-014) — {summary['questions_in_scope']} in-scope question(s), "
          f"{summary['declared_paths']} declared path(s)\n")
    print(f"  {'':<6} {'RRF':>10}   {'reranked':>10}")
    for k in K_VALUES:
        cells = []
        for key in ("source_recall_at_k", "reranked_recall_at_k"):
            row = summary[key][str(k)]
            pct = f"{row['recall']:.0%}" if row["recall"] is not None else "n/a"
            cells.append(f"{row['found']}/{row['declared']} ({pct})")
        print(f"  k={k:<3}  {cells[0]:>10}   {cells[1]:>10}")

    print("\nPer question:")
    for result in results:
        if not result["declared_paths"]:
            print(
                f"  {result['id']}  [{result['intent']}]  "
                f"no declared paths — excluded from recall"
            )
            continue
        for path in result["declared_paths"]:
            before = result["retrieved_at_k"][str(max_k)][path]
            after = result["reranked_at_k"][str(max_k)][path]
            if before is None:
                verdict = f"NOT retrieved in top {max_k}"
            else:
                verdict = f"rank {before} → rank {after}"
            print(f"  {result['id']}  [{result['intent']:<12}] {path} — {verdict}")

    print("\nTop score per question, RRF and rerank (ADR-006 threshold evidence):")
    for result in results:
        rrf, rr = result["top_rrf_score"], result["top_rerank_score"]
        shown = f"{rrf:.5f}   {rr:.4f}" if rrf is not None else "no chunks"
        print(f"  {result['id']}  {shown}   ({result['rerank_latency_s']:.2f} s)")

    if args.no_write:
        return 0

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = REPORT_DIR / f"retrieval-recall-{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "snapshot": snapshot,
                "reranker": reranker,
                "summary": summary,
                "results": results,
            },
            indent=2,
        )
    )
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
