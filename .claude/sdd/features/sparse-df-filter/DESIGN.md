# DESIGN: A sparse side that votes only on distinctive terms

> Implements [DEFINE.md](DEFINE.md). Decision recorded in
> [ADR-017](../../../../docs/adr/ADR-017-df-filtered-or-for-the-sparse-side.md).

## Metadata

| Field | Value |
|-------|-------|
| Feature | sparse-df-filter |
| Depends on | [DEFINE.md](DEFINE.md), Clarity Score 14/15, Ready for Design |
| Status | Draft |
| ADR needed | **Yes**: [ADR-017](../../../../docs/adr/ADR-017-df-filtered-or-for-the-sparse-side.md), Status Planned. BUILD's first reading decides it through the rule copied from DEFINE |

## Architecture overview

The change is one SQL constant and the tooling that reads its effect. The fusion,
the dense side, the schema and the index stay as they are.

```
retrieval/hybrid_search.py
  SPARSE_TERMS_CTES           NEW. One fragment, used by both queries below
    query_terms               plainto_tsquery output, split on ' & ', distinct
    df_cutoff                 max chunks in any one (source_project, source_path)
    term_df                   per term: count of chunks with content_tsv @@ term
  HYBRID_QUERY
    sparse_query              NEW CTE: OR of the terms with df <= cutoff
    candidates                sparse_score = COALESCE(ts_rank_cd(content_tsv, tsq), 0)
    dense_ranked / sparse_ranked / fusion   unchanged
  SPARSE_TERMS_QUERY          NEW: the same CTEs, returning term, df, kept, cutoff
  sparse_terms(conn, text)    NEW: runs it, returns SparseTerms

scripts/retrieval_recall.py   records sparse terms and A4; --baseline prints A1–A4
scripts/ask.py                prints kept and dropped terms (COULD)
Makefile                      retrieval-recall passes baseline=
```

**Q3 (where the frequencies live): per query, computed in SQL.** The query does
one GIN-backed `count(*)` per distinct query lexeme, plus one `GROUP BY` over the
chunks. Measured on 2026-09-30 on a non-golden 10-lexeme text: 0.66 ms execution.
`chunks` holds one live snapshot per project (ADR-013). The counts are taken in
the same statement that searches, so they cannot describe a different snapshot.
A table refreshed at index time was considered (ADR-017 Alternative 4) and adds a
way to disagree with `chunks` to save under a millisecond.

**Q4 (building the tsquery without user text): yes, in SQL.**
`plainto_tsquery('english', text)::text` is Postgres' own output, with every
lexeme already quoted (`'snowpip' & 'stream'`). Split on `' & '`, each fragment is
a valid single-lexeme tsquery and is cast back with `::tsquery`. The kept ones are
rejoined with `' | '`. Verified on 2026-09-30:
- a quote, a backslash, `&`, `:` and quoted text (`O'Reilly back\slash x&y a:b 'quoted'`)
  all round-trip through the cast
- a stopword-only text produces an empty tsquery, and the `WHERE term <> ''` drops it
- `ts_rank_cd(…, NULL)` under `COALESCE` gives 0

Postgres' parser never produces a lexeme containing a space, so `' & '` cannot
occur inside one.

**The cutoff is computed over the whole index, not over the collection filter.**
DEFINE defines the rule on the corpus's structure. No intent classifier exists
today, so every query searches both collections, and the two scopes are the same
set of rows. Recorded as deferred for the classifier's ADR (Open questions).

**Only the sparse ranking and its RRF contribution change.** `dense_rank`,
`dense_distance`, `RRF_K`, both tiebreaks and the final `ORDER BY` are untouched.

## Data contracts

No table, column or index changes. Two pydantic models are added to
`data_platform_rag/contracts.py`:

```python
class SparseTerm(BaseModel):
    """One lexeme of the query, with its document frequency in the live index."""
    model_config = ConfigDict(frozen=True)
    term: str             # as Postgres quotes it in tsquery text, e.g. "'snowpip'"
    df: int = Field(ge=0) # chunks whose content_tsv matches the term
    kept: bool            # df <= cutoff

class SparseTerms(BaseModel):
    """What the ADR-017 filter did to one query."""
    model_config = ConfigDict(frozen=True)
    cutoff: int | None = Field(default=None, ge=0)  # None only when the index is empty
    terms: list[SparseTerm]                          # ordered by df desc, then term
```

The term keeps Postgres' quoting (`'snowpip'`). Unquoting would be a
second, hand-written escaper, and this field exists to be traced, not parsed.

The recall report (`retrieval-recall-*.json`, gitignored) gains:

- per question: `"sparse_terms": {"cutoff": 68, "kept": [[term, df], …], "dropped": [[term, df], …]}`
- in the summary: `"questions_with_sparse_rows": N`. A question counts when any
  chunk in its top-20 ranking has a `sparse_rank`. This is how the 7/50
  before-reading was counted (rechecked on 2026-09-30), and it stays that way so
  the two readings count alike. It matches "the sparse side returned rows"
  except in one corner case. Sparse rank 1 alone scores `1/61`, which beats every
  dense-only chunk except dense rank 1, so it misses the fused top 20 only if
  19 chunks ranked on both sides also outscore it. In that case the question
  would be undercounted, which makes A4 harder to pass, never easier

## Interfaces

| Where | Change |
|---|---|
| `hybrid_search.HYBRID_QUERY` | Filtered sparse tsquery. `search()` and `build_hybrid_query()` keep their signatures |
| `hybrid_search.sparse_terms(conn, query_text: str) -> SparseTerms` | New. Same CTE fragment as the search, so the report cannot describe a different filter from the one that ranked |
| `scripts/retrieval_recall.py` | Opens one connection and passes it to `retrieve(conn=…)` and `sparse_terms`. Prints `questions with sparse rows: N/50`. New `--baseline FILE` |
| `--baseline FILE` | Refuses unless the baseline's snapshot SHAs, embedding model and per-question declared paths equal today's. Then prints four lines, one per A1–A4 input: k=3 found (and the delta), the baseline top-3 paths no longer in the top 3, k=10/k=20 found, and questions with sparse rows. **It prints the numbers, not a verdict.** The rule lives in ADR-017, and code that re-implements it could drift from it |
| `Makefile` | `retrieval-recall: … $(if $(baseline),--baseline $(baseline))` |
| `scripts/ask.py` (COULD) | One line under the question: `sparse terms (cutoff 68): kept 'snowpip'(19) 'load'(21) … · dropped 'stream'(72) …` |
| `config.py` | **Nothing.** The cutoff is a rule, not a setting. A setting would invite the sweep that DEFINE rules out |

## Retrieval and RAG-specific concerns

- [x] **Chunking:** not affected.
- [x] **HNSW index:** not touched, no reindex. The dense side of the query is
      byte-identical.
- [x] **Query pattern:** changes on the sparse side only. `sql/99_verify.sql`'s
      hybrid query section gets the new CTEs and a fresh `EXPLAIN ANALYZE` baseline
      in BUILD, on a question already in that file, not a new golden-set read.
- [x] **RAGAS:** cannot run (no API key, generation blocked). **Regression risk:
      yes.** Ranking changes for every question with kept lexemes. Source recall
      stands in for RAGAS (ADR-014), with A2 guarding every path the LLM sees today
      and A3 guarding k=10/k=20.
- [x] **Out-of-scope scores** rise (ADR-017 Consequences, P2). Reported, not gated.
- [x] **KB:** `.claude/kb/rag/hybrid-retrieval.md` describes the sparse side as
      `plainto_tsquery`. It is updated in the same pass as the Outcome, to whichever
      state the rule leaves (KB drift rule).

## Alternatives considered

The decision's alternatives are in ADR-017 (unfiltered OR, largest-ADR cutoff,
swept cutoff, DF table, `ts_stat`, RRF weight, dense-only). The design-level ones:

- **Build the OR tsquery in Python from the lexemes.** Rejected. It moves quoting
  into application code, which is the property ADR-015 kept in SQL and DEFINE
  requires to stay there.
- **Derive the lexemes from `unnest(to_tsvector(text))`.** It gives the same set
  for ordinary text, but DEFINE names `plainto_tsquery`'s lexemes. Two
  normalisation paths that usually agree are a gap waiting for a case where they
  do not.
- **Compute the A1–A4 verdict in the script.** Rejected, see Interfaces. The
  numbers are printed, and ADR-017's table maps them to an outcome.
- **A setting to switch the filter off.** Rejected. It is a way to run two
  retrievers under one name. ADR-015 Alternative 3 rejected that for the same
  reason (ADR-014). Rollback is a revert.

## Test plan

**Unit** (`tests/unit/test_hybrid_search_query.py`, `test_contracts.py`):

- `plainto_tsquery(` appears exactly once in `HYBRID_QUERY`, before
  `candidates` ends. The existing `test_sparse_tsquery_is_built_once_inside_candidates`
  keeps its intent, and its partition is updated if the CTE order moves the text
- `HYBRID_QUERY` and `SPARSE_TERMS_QUERY` both contain `SPARSE_TERMS_CTES`
  verbatim, so the report and the ranking share one filter
- the cutoff compares with `<=` (keep at equality: "more chunks than" drops)
- the dense side of the query is unchanged: the `dense_ranked` CTE text is
  byte-identical to today's
- `SparseTerm` / `SparseTerms` validate and are frozen, and `df` rejects negatives
- recall script: `questions_with_sparse_rows` counted from a hand-built ranking;
  `--baseline` refuses on a mismatched SHA, model or declared-path set, and
  lists a path that left the top 3

**Integration** (`tests/integration/test_hybrid_search_postgres.py`, real Postgres):

- **all lexemes above the cutoff:** a fixture where the query's only lexemes are
  in more chunks than the largest file. Zero sparse rows, a full dense list, no
  error (DEFINE acceptance test)
- **mixed:** a generic lexeme above the cutoff and a specific one below. Only the
  specific one's chunk gets a `sparse_rank`, and `sparse_terms` reports one kept
  and one dropped with their counts
- **the cutoff follows the corpus:** rewrite the fixture so the largest file
  gains a chunk. A lexeme previously dropped is now kept, with no code change
  (DEFINE acceptance test)
- **sanitising:** `test_a_query_with_no_lexemes_returns_dense_only_without_error`
  and `test_tsquery_syntax_in_the_input_is_inert` pass **unchanged**. Add the
  round-trip text above (`O'Reilly back\slash …`) and `:*`, `(`, `!` to the noisy
  list
- **determinism:** the existing test, still passing
- **existing fixtures:** each row is its own file, so the cutoff is 1. `FIXTURE`
  and `SANITISING_FIXTURE` still pass, because their matching lexeme
  (`debezium`) is in one chunk. `test_a_sparse_tie_breaks_by_id_not_by_heap_order`
  would fail for a reason unrelated to tiebreaks. Its two identical chunks are in
  two files, so every lexeme (df 2) exceeds cutoff 1. Its fixture moves both
  chunks into one file (`chunk_index` 0 and 1, cutoff 2). The assertion is
  unchanged. Recorded in ADR-017 Consequences, so the change is not a silent test
  edit

**Manual, on the local index** (BUILD, in this order):

1. Check ADR-017's rule is byte-identical to DEFINE's (`awk` range extract from
   both files, then `diff`). Done at DESIGN time. Repeat it right before step 4
2. `make lint`, `make test`
3. Confirm the index is still `f1295df9` / `82a2e269` / `BAAI/bge-small-en-v1.5`.
   The `--baseline` check refuses otherwise. If it has changed, the before-reading
   is retaken first, never quoted across states
4. `make retrieval-recall baseline=.claude/dev/reports/retrieval-recall-20260929-190639.json`,
   twice. The two runs must match in rankings and scores
5. Read A1–A4 off the printout, apply ADR-017's table, write the Outcome
6. `make ask q="why Snowpipe Streaming?"` shows the kept/dropped line (COULD)

## Rollout plan

- **Migration:** none. No schema, no index, no reindex.
- **Feature flag:** none (see Alternatives).
- **Order:** ADR-017 (Planned) is committed before any code. Then code and tests,
  then the measurement, then the Outcome.
- **If Accepted:** ADR-017 → Accepted with the Outcome. ADR-003 gets an amendment
  pointing §B to ADR-017. The README's hybrid claim and Known Gaps say what the
  sparse side now does. `sql/99_verify.sql` keeps the new baseline, and the KB is
  updated. The per-project comparison ADR retakes its before-reading on this state.
- **If Rejected (rollback):** `HYBRID_QUERY` reverts to `plainto_tsquery`, and
  `sparse_terms`, its models and the `ask` line are removed with it, since they
  would describe a filter not in use. What stays: the A4 count, `--baseline`, and
  the new sanitising and fixture tests, because they guard properties any sparse
  query must keep (ADR-015's precedent). ADR-017 → Rejected in place with the
  numbers. The dense-only ADR opens as the next feature, as the author
  pre-agreed.
- **What breaks on revert:** nothing downstream. `RetrievedChunk` is unchanged,
  and the recall report's new fields are additive.

## Open questions

- [x] **Q1, Q2 (DEFINE):** settled by the author on 2026-09-30.
- [x] **Q3:** per query, in SQL (Architecture overview).
- [x] **Q4:** yes, from `plainto_tsquery`'s own quoted output (Architecture overview).
- [ ] **Deferred to the intent-classifier / per-project ADR:** once a query can
      search one collection, should the cutoff and frequencies be computed over that
      collection instead of the whole index? Not today: both scopes are the same
      rows.
