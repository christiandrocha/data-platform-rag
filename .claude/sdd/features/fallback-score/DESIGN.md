# DESIGN: Does cosine similarity separate in scope from out of scope?

> Implements [DEFINE.md](DEFINE.md). Decision recorded in
> [ADR-019](../../../../docs/adr/ADR-019-similarity-separability-decides-the-fallback-gate.md).

## Metadata

| Field | Value |
|-------|-------|
| Feature | fallback-score |
| Depends on | [DEFINE.md](DEFINE.md), Clarity Score 14/15, Ready for Design |
| Status | Draft |
| ADR needed | **Yes**: [ADR-019](../../../../docs/adr/ADR-019-similarity-separability-decides-the-fallback-gate.md), Status Planned, and Accepted either way. The Outcome records the branch. The fork was checked byte-identical to DEFINE at DESIGN time |

## Architecture overview

Reporting only. Retrieval, the contract and the schema are untouched.

```
Commit 1, the instrument (measured once)
  scripts/retrieval_recall.py
    evaluate()        each ranked chunk gains "dense_distance"
                      each result gains "top_similarity" = 1 − ranking[0].dense_distance
    separability()    NEW, pure: the four numbers, from results + intent
    summarise()       summary gains "separability"
    main()            prints the four numbers, plus the out-of-scope questions sorted by
                      top similarity and the lowest in-scope ones (COULD)
  scripts/ask.py      a "sim" column (1 − dense distance) next to "dense" (SHOULD)
  tests               see Test plan

Commit 2, after the Outcome (docs)
  ADR-019 Outcome + Status Accepted, index
  separable      → ADR-006 gets a note: "0.35 uncalibrated; calibration set pending (next ADR)"
  not separable  → ADR-006 superseded in part (score gate), AGENTS.md RAG-discipline line,
                   README Known Gaps, KB dense-retrieval "What the score cannot do".
                   settings.fallback_threshold is removed in the ADR-019 follow-up
                   (DEFINE), a separate feature, since config is an interface
```

**Q3 (field, property, or report-only): report-only.** `dense_distance` is already
in `RetrievedChunk`, and the similarity is `1 − dense_distance`, one subtraction.
A field or property would change the contract in a feature whose rule says
nothing moves. It would also pre-empt the next ADR, which will redo the contract
anyway when `rrf_score` leaves (DEFINE Q2). So the recall script and `make ask`
compute it where they print it.

**The four numbers** (`separability(results)`):

| key | meaning |
|---|---|
| `min_in_scope` / `min_in_scope_id` | lowest top similarity among questions whose intent is not `out-of-scope` and that declare paths, which is the same filter `summarise` uses for recall |
| `max_out_of_scope` / `max_out_of_scope_id` | highest top similarity among `intent: out-of-scope` |
| `in_scope_at_or_below_max_oos` | count of in-scope questions with `top_similarity <= max_out_of_scope` |
| `oos_at_or_above_min_in_scope` | count of out-of-scope questions with `top_similarity >= min_in_scope` |

Separable ⇔ both counts are 0 (equivalently `min_in_scope > max_out_of_scope`).
The script prints the numbers. The fork in ADR-019 maps them to a branch.
Comparisons use full float precision, and printing uses 4 decimals, so the
artifact keeps the full value.

**Which questions count as in scope.** The 45 questions whose intent is not
`out-of-scope` all declare paths (`questions_in_scope` = 45 in the ADR-018
artifact), so the recall filter and "not out-of-scope" are the same set today. If
they ever diverge, the recall filter wins, so the two numbers are computed over one
population.

## Data contracts

No pydantic change. The recall artifact (gitignored JSON) gains:

```jsonc
"results": [{
  "top_similarity": 0.8123,            // 1 − ranking[0].dense_distance; null if no ranking
  "ranking": [{ "dense_distance": 0.1877, ... }]
}],
"summary": {
  "separability": {
    "min_in_scope": 0.71, "min_in_scope_id": "q0xx",
    "max_out_of_scope": 0.69, "max_out_of_scope_id": "q0xx",
    "in_scope_at_or_below_max_oos": 0,
    "oos_at_or_above_min_in_scope": 0
  }
}
```

(Values are illustrative placeholders, not measurements.)

## Interfaces

| Where | Change |
|---|---|
| `scripts/retrieval_recall.py` | Fields above. A new printed block, "Separability of top-1 cosine similarity (ADR-019)". `--baseline` is unchanged and still compares rankings and recall |
| `scripts/ask.py` | Header `#  rrf  dense  sim  source`. `sim` = `1 − dense_distance`, 3 decimals |
| `config.py`, `contracts.py`, retrieval, SQL | Nothing |

## Retrieval and RAG-specific concerns

- [x] **Chunking, HNSW, schema:** not affected.
- [x] **Query pattern:** unchanged. `sql/99_verify.sql` is untouched.
- [x] **Rankings:** must not move. Verified with
      `make retrieval-recall baseline=<ADR-018 post-rename artifact>`: A1–A3 equal and
      identical rankings 50/50.
- [x] **RAGAS:** cannot run. **Regression risk: none for retrieval** (read-only
      additions). The decision this feeds, the fallback, is exactly what RAGAS will
      measure once it exists (`fallback_accuracy` in `RAGASAggregate`).
- [x] **KB:** `rag/dense-retrieval.md` "What the score cannot do" is updated in
      commit 2 to whichever branch holds.

## Alternatives considered

The decision's alternatives are in ADR-019. The design-level ones:

- **A `similarity` field or property on `RetrievedChunk`.** Deferred (Q3 above): a
  contract change in a feature that must not move anything.
- **A separate script** (`make separability`). Rejected. The number belongs next to
  the snapshot, the golden set and the rankings it came from, which is the recall
  artifact. A second script would re-run 50 retrievals and could drift.
- **Print the branch** ("SEPARABLE" / "NOT SEPARABLE"). Rejected for the same reason
  as ADR-017's A1–A4 printout: the rule lives in the ADR. The two counts being zero
  or not is as readable as a verdict and cannot drift from it.
- **Similarity over the top-k mean instead of top-1.** Rejected. ADR-006's gate is
  about "the top-ranked retrieved chunk", and a mean is a different, uncalibrated
  statistic.

## Test plan

**Unit** (`tests/unit/test_retrieval_recall.py`):

- `separability` on a hand-built separable set: both counts 0, and min/max and ids
  correct
- one in-scope question below the highest out-of-scope one: the counts are 1 and
  ≥ 1
- **exact tie** between the lowest in-scope and the highest out-of-scope: both
  counts ≥ 1 (a tie is overlap, DEFINE Q1)
- the population is decided by `intent`, not an id list: a result with intent
  `out-of-scope` and id `q999` counts as out of scope
- no out-of-scope questions, or no in-scope ones: the corresponding values are
  `None`, and there is no crash
- `top_similarity` equals `1 − ranking[0].dense_distance`, and is `None` for an
  empty ranking

**Integration:** none new. The recall script is exercised end to end by the
manual run. Retrieval is unchanged, and its tests stay green.

**Manual, on the local index** (BUILD, in this order):

1. Check that ADR-019's fork is byte-identical to DEFINE's. Done at DESIGN time;
   repeat it right before step 4
2. `make lint`, `make test`
3. Confirm the index is still `f1295df9` / `82a2e269` / `BAAI/bge-small-en-v1.5`.
   `--baseline` refuses otherwise
4. `make retrieval-recall baseline=.claude/dev/reports/retrieval-recall-20260930-182208.json`,
   twice. Check: A1–A3 unchanged, identical rankings 50/50, and the two runs'
   similarities equal. **This is the measurement:** the first run prints the four
   numbers
5. Read the branch off the two counts, write ADR-019's Outcome, then commit 2
6. `make ask q="why Snowpipe Streaming?"` shows the `sim` column (SHOULD)

## Rollout plan

- **Migration / feature flag:** none. Read-only reporting.
- **Order:** ADR-019 (Planned) is committed before code. Then commit 1, the
  measurement, the Outcome, and commit 2.
- **Rollback:** revert commit 1. Nothing depends on the new artifact fields.
  ADR-019's Outcome stays, because a measurement once taken is history.
- **Follow-ups by branch** (each its own feature and ADR):
  - separable: write the out-of-scope calibration set, then an ADR that picks the
    threshold on it and verifies on the golden set. The gate is built with
    generation
  - not separable: remove `settings.fallback_threshold`, drop `rrf_score` from the
    contract, and specify rule 3 as the only out-of-scope path, measured by
    `make eval`

## Open questions

- [x] **Q1, Q2 (DEFINE):** settled by the author on 2026-09-30.
- [x] **Q3:** report-only, no contract change (Architecture overview).
- [ ] **Deferred to the branch's ADR:** the calibration set's size and authorship
      (separable), or rule 3's measurement design (not separable).
