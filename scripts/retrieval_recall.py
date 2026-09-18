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
from datetime import UTC, datetime
from pathlib import Path

import yaml

from data_platform_rag.retrieval.pipeline import retrieve

GOLDEN_SET = Path("docs/golden-set/evaluation_questions.yml")
REPORT_DIR = Path(".claude/dev/reports")
K_VALUES = (3, 10, 20)
OUT_OF_SCOPE = "out-of-scope"


def load_questions() -> list[dict]:
    questions = yaml.safe_load(GOLDEN_SET.read_text())
    if not isinstance(questions, list):
        raise SystemExit(f"ERROR: {GOLDEN_SET} did not parse as a list of questions.")
    return questions


def evaluate(question: dict, max_k: int) -> dict:
    """Retrieve once at max_k and read every k off the same ranking.

    One retrieval per question, not one per k: the top 3 is a prefix of the top
    20, so retrieving three times would cost three model calls to produce the
    same answer -- and would not even be guaranteed identical if anything about
    retrieval were non-deterministic.
    """
    chunks = retrieve(question["question"], top_k=max_k)
    ranking = [
        {
            "rank": position,
            "project": chunk.metadata.source_project,
            "path": chunk.metadata.source_path,
            "anchor": chunk.metadata.source_anchor,
            "rrf_score": chunk.rrf_score,
            "dense_rank": chunk.dense_rank,
            "sparse_rank": chunk.sparse_rank,
        }
        for position, chunk in enumerate(chunks, start=1)
    ]

    declared = [
        (entry["project"], entry["path"]) for entry in question.get("expected_source_paths") or []
    ]
    def rank_of(project: str, path: str, k: int) -> int | None:
        """The position this declared path was found at, or None within top k."""
        for row in ranking[:k]:
            if (row["project"], row["path"]) == (project, path):
                return row["rank"]
        return None

    hits: dict[str, dict[str, int | None]] = {
        str(k): {f"{project}/{path}": rank_of(project, path, k) for project, path in declared}
        for k in K_VALUES
    }

    return {
        "id": question["id"],
        "intent": question["intent"],
        "question": question["question"],
        "declared_paths": [f"{p}/{q}" for p, q in declared],
        "top_rrf_score": ranking[0]["rrf_score"] if ranking else None,
        "retrieved_at_k": hits,
        "ranking": ranking,
    }


def summarise(results: list[dict]) -> dict:
    """Recall summed over declared paths, per ADR-014."""
    in_scope = [
        r for r in results if r["intent"] != OUT_OF_SCOPE and r["declared_paths"]
    ]
    denominator = sum(len(r["declared_paths"]) for r in in_scope)
    recall = {}
    for k in K_VALUES:
        found = sum(
            1
            for r in in_scope
            for rank in r["retrieved_at_k"][str(k)].values()
            if rank is not None
        )
        recall[str(k)] = {
            "found": found,
            "declared": denominator,
            "recall": round(found / denominator, 4) if denominator else None,
        }
    return {
        "questions_in_scope": len(in_scope),
        "declared_paths": denominator,
        "source_recall_at_k": recall,
        "top_rrf_scores": {r["id"]: r["top_rrf_score"] for r in results},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="Print only; write no artifact.")
    args = parser.parse_args()

    questions = load_questions()
    max_k = max(K_VALUES)
    results = [evaluate(q, max_k) for q in questions]
    summary = summarise(results)

    print(f"Source recall at k (ADR-014) — {summary['questions_in_scope']} in-scope question(s), "
          f"{summary['declared_paths']} declared path(s)\n")
    for k in K_VALUES:
        row = summary["source_recall_at_k"][str(k)]
        pct = f"{row['recall']:.0%}" if row["recall"] is not None else "n/a"
        print(f"  k={k:<3} {row['found']}/{row['declared']}  ({pct})")

    print("\nPer question:")
    for result in results:
        if not result["declared_paths"]:
            print(
                f"  {result['id']}  [{result['intent']}]  "
                f"no declared paths — excluded from recall"
            )
            continue
        for path in result["declared_paths"]:
            ranks = [result["retrieved_at_k"][str(k)][path] for k in K_VALUES]
            rank = next((r for r in ranks if r is not None), None)
            verdict = f"rank {rank}" if rank is not None else "NOT retrieved in top 20"
            print(f"  {result['id']}  [{result['intent']:<12}] {path} — {verdict}")

    print("\nTop RRF score per question (ADR-006 threshold evidence):")
    for qid, score in summary["top_rrf_scores"].items():
        shown = f"{score:.5f}" if score is not None else "no chunks"
        print(f"  {qid}  {shown}")

    if args.no_write:
        return 0

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = REPORT_DIR / f"retrieval-recall-{stamp}.json"
    out.write_text(
        json.dumps(
            {"generated_at": datetime.now(UTC).isoformat(), "summary": summary, "results": results},
            indent=2,
        )
    )
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
