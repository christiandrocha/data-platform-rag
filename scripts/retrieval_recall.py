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

Per question, the artifact also records whether the sparse side ranked
anything, so a change in recall can be traced to the sparse side rather than
inferred.

`--baseline FILE` prints the four numbers ADR-017's decision rule reads (A1-A4)
against an earlier artifact. It prints numbers, not a verdict: the rule lives in
the ADR, and code that re-implemented it could drift from it. It refuses to
compare artifacts measured on a different snapshot, model or golden set.

Writes a timestamped JSON artifact. Deliberately not a CI gate: see ADR-014 s4.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from data_platform_rag.config import get_settings
from data_platform_rag.indexer.writer import connect, current_snapshots
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


def has_sparse_rows(ranking: list[dict]) -> bool:
    """Whether the sparse side ranked any chunk that reached the fused top k.

    The same test the 2026-09-29 before-reading was counted with (7/50), kept so
    the two readings count alike. It misses a non-empty sparse list only if its
    rank-1 chunk is pushed out of the fused top 20, which undercounts: A4 gets
    harder to pass, never easier.
    """
    return any(row["sparse_rank"] is not None for row in ranking)


def evaluate(question: dict, max_k: int, conn=None) -> dict:
    """Retrieve once at max_k and read every k off the same ranking.

    One retrieval per question, not one per k: the top 3 is a prefix of the top
    20, so retrieving three times would cost three model calls to produce the
    same answer -- and would not even be guaranteed identical if anything about
    retrieval were non-deterministic.
    """
    chunks = retrieve(question["question"], top_k=max_k, conn=conn)
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
        "has_sparse_rows": has_sparse_rows(ranking),
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
        "questions": len(results),
        "questions_with_sparse_rows": sum(1 for r in results if has_sparse_rows(r["ranking"])),
        "questions_in_scope": len(in_scope),
        "declared_paths": denominator,
        "source_recall_at_k": recall,
        "top_rrf_scores": {r["id"]: r["top_rrf_score"] for r in results},
    }


def comparability_problems(baseline: dict, snapshot: dict, results: list[dict]) -> list[str]:
    """Why two artifacts cannot be compared; empty when they can.

    A before-reading is never quoted across states (DEFINE): a different commit,
    embedding model or golden set makes the delta measure the change of state,
    not the change of retrieval.
    """
    problems = []
    if baseline.get("snapshot") != snapshot:
        problems.append(
            f"snapshot differs: baseline {baseline.get('snapshot')} vs now {snapshot}"
        )
    before = {r["id"]: r["declared_paths"] for r in baseline.get("results", [])}
    now = {r["id"]: r["declared_paths"] for r in results}
    if before != now:
        changed = sorted(
            qid for qid in before.keys() | now.keys() if before.get(qid) != now.get(qid)
        )
        problems.append(f"golden set differs (question ids or declared paths): {changed}")
    return problems


def top3_paths(results: list[dict]) -> set[tuple[str, str]]:
    """Every (question, declared path) found in the top 3."""
    return {
        (r["id"], path)
        for r in results
        for path, rank in r["retrieved_at_k"]["3"].items()
        if rank is not None
    }


def baseline_deltas(baseline: dict, results: list[dict], summary: dict) -> dict:
    """The four inputs of ADR-017's decision rule, before and after. No verdict.

    Kept after ADR-017's rejection: any change to the sparse side is judged on
    the same four inputs, and the comparability check guards every one of them.
    """
    before_recall = baseline["summary"]["source_recall_at_k"]
    now_recall = summary["source_recall_at_k"]
    return {
        "declared": now_recall["3"]["declared"],
        "k3": (before_recall["3"]["found"], now_recall["3"]["found"]),
        "lost_top3": sorted(top3_paths(baseline["results"]) - top3_paths(results)),
        "k10": (before_recall["10"]["found"], now_recall["10"]["found"]),
        "k20": (before_recall["20"]["found"], now_recall["20"]["found"]),
        "sparse_rows": (
            sum(1 for r in baseline["results"] if has_sparse_rows(r["ranking"])),
            summary["questions_with_sparse_rows"],
        ),
        "questions": summary["questions"],
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
    parser.add_argument(
        "--baseline",
        type=Path,
        help="An earlier artifact: print the A1-A4 inputs of ADR-017's rule against it.",
    )
    args = parser.parse_args()

    questions = load_questions()
    max_k = max(K_VALUES)
    with connect(str(get_settings().database_url)) as conn:
        results = [evaluate(q, max_k, conn) for q in questions]
    summary = summarise(results)
    snapshot = indexed_snapshot()

    baseline = None
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        problems = comparability_problems(baseline, snapshot, results)
        if problems:
            for problem in problems:
                print(f"ERROR: {problem}", file=sys.stderr)
            print(
                f"ERROR: {args.baseline} is not comparable. Retake the before-reading "
                "on the current state instead of quoting it across states.",
                file=sys.stderr,
            )
            return 1

    print("Indexed snapshot (ADR-013):")
    for project, row in snapshot.items():
        print(f"  {project}@{row['commit_sha'][:8]}  {row['embedding_model']}")
    print()

    print(f"Source recall at k (ADR-014) — {summary['questions_in_scope']} in-scope question(s), "
          f"{summary['declared_paths']} declared path(s)\n")
    for k in K_VALUES:
        row = summary["source_recall_at_k"][str(k)]
        pct = f"{row['recall']:.0%}" if row["recall"] is not None else "n/a"
        print(f"  k={k:<3} {row['found']}/{row['declared']}  ({pct})")

    print(
        f"\n  questions with sparse rows: "
        f"{summary['questions_with_sparse_rows']}/{summary['questions']}"
    )

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

    if baseline is not None:
        d = baseline_deltas(baseline, results, summary)
        print(f"\nAgainst {args.baseline} (ADR-017 decision-rule inputs, no verdict):")
        print(f"  A1  k=3 found:   {d['k3'][0]} -> {d['k3'][1]} /{d['declared']}  "
              f"({d['k3'][1] - d['k3'][0]:+d})")
        print(f"  A2  top-3 paths lost: {len(d['lost_top3'])}")
        for qid, path in d["lost_top3"]:
            print(f"        {qid}  {path}")
        print(f"  A3  k=10 found:  {d['k10'][0]} -> {d['k10'][1]} /{d['declared']}")
        print(f"      k=20 found:  {d['k20'][0]} -> {d['k20'][1]} /{d['declared']}")
        print(f"  A4  questions with sparse rows: {d['sparse_rows'][0]} -> "
              f"{d['sparse_rows'][1]} /{d['questions']}")

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
                "baseline": str(args.baseline) if args.baseline else None,
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
