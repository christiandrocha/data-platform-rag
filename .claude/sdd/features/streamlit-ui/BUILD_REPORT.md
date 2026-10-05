# BUILD REPORT: The product query path (PR 1 of 2)

## Metadata

| Field | Value |
|-------|-------|
| Feature | streamlit-ui |
| DEFINE | [DEFINE.md](DEFINE.md) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| ADR | [ADR-021](../../../../docs/adr/ADR-021-product-query-path.md), Planned |
| Start date | 2026-10-05 |
| End date | PR 1: 2026-10-05. PR 2 (the page) pending |
| PR | PR 1: pending |

## What was built (PR 1, the path)

**Code**
- `data_platform_rag/generation/answer.py`: **new.** `answer()`, `shown_text_for()`,
  `validate_question()`, `FAILED_MESSAGE`, and the `query_log` insert.
- `data_platform_rag/observability/tracing.py`: **new.** `QueryTracer` and
  `QueryTrace`. Every method catches and logs, so "never block on Langfuse" lives here once.
- `data_platform_rag/generation/sdk.py`: **new.** `build_client()`, the one SDK
  import. `scripts/fallback_eval.make_client` delegates to it.
- `data_platform_rag/contracts.py`: `AnswerResult` rewritten (ADR-021), with
  `fallback_fired` as a property. `RerankedChunk` is deleted. `RetrievedSource.from_chunk()`
  is shared by ADR-020 and ADR-021, and `fallback_eval.to_sources` uses it.
- `data_platform_rag/observability/langfuse_client.py`: the no-op context gained
  `id = None`, `span`, `generation` and `end`, so the no-op client runs the whole
  trace shape without warnings.
- `data_platform_rag/config.py`: `max_question_chars = 500`, `ge=216`.
- `sql/04_query_log_product.sql`: **new.** 12 columns via `ADD COLUMN IF NOT
  EXISTS`, plus comments on `intent`, `reranker_top_score`, `retrieved_scores`,
  `fallback_fired` and `answer_length`. No `DROP`.
- `Makefile`: `bootstrap` runs `sql/04`, and `deploy` runs the gate first.
- `scripts/check_deploy_gate.py`: **new.**

**Tests:** 343 passed, 0 skipped (Postgres up). Before this build: 296.
- `tests/unit/test_answer.py`: **new**, 25 tests. Display per class,
  `fallback_fired` per class, rejected questions run nothing, the cap's floor,
  each class end to end on a recording connection and tracer, a failed call, a
  failed retrieval, a bounded error, a reconnect for the row, a failed insert,
  and Langfuse down.
- `tests/unit/test_tracing.py`: **new**, 4 tests.
- `tests/unit/test_check_deploy_gate.py`: **new**, 7 tests, one on the real ADR-020.
- `tests/integration/test_answer_postgres.py`: **new**, 9 tests on the `_test`
  database: one row per class, failed call, failed retrieval, Langfuse down,
  rank order, and `sql/04` applied twice on a populated table.
- `tests/unit/test_contracts.py`: the old `RerankedChunk` and `AnswerResult`
  tests are replaced by four tests of the new contract.
- `tests/integration/conftest.py`: the test database is also built with `sql/04`.

**Docs:** ADR-009 gets an in-place amendment note (D8). AGENTS.md: the repo map,
and `sql/00`–`04` in the bootstrap boundary. README roadmap items 3–6. KB:
`langfuse/traces-and-generations.md`, `langfuse/python-sdk.md`,
`pydantic/models.md` and `pydantic/config-pattern.md`. `.env.example` gets
`MAX_QUESTION_CHARS`.

## What deviated from design

1. **The DESIGN said the old `AnswerResult` had no importer "checked with
   `grep`". That was wrong.** The grep excluded every path containing
   `contracts.py`, which also hid `tests/unit/test_contracts.py`. Two tests used
   `RerankedChunk` and the old `AnswerResult`. They are replaced, and no
   application code imported either.
2. **`langfuse` is an optional extra** (`.[observability]`), not a base
   dependency. `pip install -e .` did not install it. It was installed with
   `pip install -e ".[observability]"` (2.60.10), and the five calls were read
   from its source. The suite does not need it: every test uses fakes or the
   no-op.
3. **The trace's generation uses `usage_details={"input", "output"}`**, the
   2.60 argument, rather than the older `usage`.
4. **The row's connection is retried once.** If `connect_fn` fails before
   retrieval, the insert tries a fresh connection, and a failed connection can
   still be recorded. DESIGN D6 named only the insert's failure.
5. **`answer()` closes its connection itself**, after the insert. The page
   therefore opens one connection per query, as DESIGN chose.
6. **CI caught what the local run hid.** The nine tests in
   `tests/integration/test_answer_postgres.py` reach `get_settings()`, which
   requires `anthropic_api_key`. The gitignored `.env` supplied it locally, so
   343 passed here and 9 failed on PR #35. This is the bug class
   `tests/unit/conftest.py` already guards against for the unit suite. The file
   now stubs the key with an autouse fixture. The fixture is scoped to this file
   because the other integration tests read the real `Settings` on purpose.
   Reproduced and verified by running the file from a directory with no `.env`.

## Found during BUILD, not changed: the local `.env` has `RERANK_TOP_K=5`

The default and `.env.example` are **3**. ADR-020 measures "the top
`settings.rerank_top_k`" chunks, and ADR-014 measured recall at k = 3. On this
machine, `make fallback-eval` would send **5** chunks per question, and
`answer()` would too. The artifact records the value, so nothing would be
hidden, but it would not be the configuration the ADRs reason about. `.env` is
the author's file and is gitignored, so it is reported here and not edited. The
integration test now reads the setting instead of assuming 3.

## RAGAS delta

Not measured. No API key exists, so neither RAGAS nor any generation has run.
Retrieval, prompt, model and context format are unchanged: the path records
what ADR-020 measures and changes none of it.

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | pending | pending | — |
| Context Precision | pending | pending | — |
| Answer Relevance | pending | pending | — |
| Context Recall | pending | pending | — |
| Fallback rate | pending (ADR-020) | pending | — |

## Known gaps at merge time

- **No real answer, trace or cost.** Everything ran on stubs. The first real
  query waits for the key (DEFINE's manual acceptance test).
- **No trace sent to a real Langfuse project.** The 2.x call shape was read from
  the SDK source and exercised on fakes only.
- **The page is PR 2.** `ui/app.py` is still the placeholder.

## Verification

- [x] `make lint`: exit 0 (ruff, yamllint, bandit)
- [x] `make test`: 343 passed, 0 skipped, exit 0
- [ ] `make eval`: not run, no key (see RAGAS delta)
- [x] `make verify-indexes`: exit 0. The retrieval query plan is unchanged
      (HNSW index scan, `sql/99_verify.sql` not modified)
- [x] `make bootstrap` twice against the populated local database: exit 0 both
      times, 304 chunks intact, `query_log` at 22 columns
- [x] `make deploy`'s gate on the real ADR-020: refused (Status: Planned), exit 1
