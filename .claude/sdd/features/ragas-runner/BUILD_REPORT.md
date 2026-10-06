# BUILD REPORT: The RAGAS runner

## Metadata

| Field | Value |
|-------|-------|
| Feature | ragas-runner |
| DEFINE | [DEFINE.md](DEFINE.md) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| ADR | [ADR-008](../../../../docs/adr/ADR-008-ragas-evaluation-runner.md), Planned |
| Start date | 2026-10-05 |
| End date | 2026-10-05 |
| PR | pending |

## What was built

**Code**
- `data_platform_rag/evaluation/golden_set_loader.py`: **new.** `load()` returns 50
  `GoldenQuestion`s. `version()` returns the file's last commit SHA and whether
  the file is modified, and it refuses a shallow clone.
- `data_platform_rag/evaluation/generate.py`: **new.** Stage 1:
  - `read_provenance()` reads the corpus commits and the embedding model from
    `corpus_snapshot`;
  - `generate_run()` calls `answer(..., origin="eval")` and reads each answer's
    chunk text by id;
  - the run file is rewritten atomically after every question.
- `data_platform_rag/evaluation/ragas_runner.py`: **new.** Stage 2. It is the one
  module that imports RAGAS, and only after `RAGAS_DO_NOT_TRACK` is set.
  - The judge: `llm_factory(provider="anthropic")` on `AsyncAnthropic`.
  - Embeddings: an adapter over `embed_query`.
  - The four metrics come from `ragas.metrics.collections`. A missing value
    records its reason and never becomes a 0.
  - Scoring resumes from an existing report, writes after every question, and
    runs in one event loop.
- `data_platform_rag/evaluation/report.py`: **new.** `aggregate()`, `table()`,
  `compare()`, `comparison_table()`, and `copy_baseline()`, which copies the
  report together with its run file.
- `data_platform_rag/evaluation/langfuse_scorer.py`: **new.** `ScorePusher`: one
  score per metric on the record's trace, never raises, and pushes nothing for a
  missing value.
- `data_platform_rag/contracts.py`:
  - **new:** `Origin`, `GoldenQuestion`, `EvalProvenance`, `EvalRecord`, `EvalRun`,
    `MetricValue`, `MetricAggregate`, `JudgeConfig`, `EvalReport`,
    `ReportComparison`;
  - **rewritten:** `RAGASReport` and `RAGASAggregate`.
- `data_platform_rag/generation/answer.py`: the `origin` keyword (default
  `"visitor"`), written to the row and to the trace's metadata.
  `observability/tracing.py`: `finish(origin=...)`.
- `data_platform_rag/generation/sdk.py`: `build_async_client()`.
- `data_platform_rag/config.py`: `judge_model = "claude-opus-5-5"`,
  `judge_max_tokens = 4096`, `answer_relevancy_strictness = 3`. `.env.example`
  documents all three.
- `sql/05_query_log_origin.sql`: **new.** `ADD COLUMN IF NOT EXISTS origin TEXT NOT
  NULL DEFAULT 'visitor'`. No `DROP`.
- `scripts/run_evaluation.py`: the stub is replaced. Subcommands: `generate`,
  `score`, `all`, `compare`, `baseline`. A preflight failure exits 2, and an
  incomparable `compare` exits 1.
- `Makefile`:
  - `bootstrap` runs `sql/05`;
  - `eval` and `eval-ci` depend on `verify-adversarials`;
  - new targets `eval-score`, `eval-compare` and `eval-baseline`, for 32 targets.
- `pyproject.toml`: the `eval` extra pins `ragas>=0.4.3,<0.5`, `datasets>=4.0`, and
  the langchain and instructor bounds (deviation 1).
- `.github/workflows/ci.yml`: the test job uses `fetch-depth: 0`, installs
  `.[dev,eval]` (D4), and applies `sql/04` and `05`.
- `.github/workflows/ragas.yml`:
  - `fetch-depth: 0`, and `sql/04` and `05` applied;
  - a contamination gate step;
  - `run_evaluation.py all`, with its output uploaded even on failure;
  - still `workflow_dispatch` only.

**Tests: 410 passed, 0 skipped** (Postgres up). Before this build: 353.
- `tests/unit/test_ragas_runner.py`: **new**, 17 tests. They run **RAGAS 0.4.3's
  own metric code** against `FakeJudge`, which returns prepared response-model
  instances, so every expected score is a number RAGAS computed. They cover:
  - four values;
  - strictness calls;
  - out-of-scope questions: no judge call, and `fallback_correct`;
  - one judge failure giving one missing value;
  - NaN as a missing value;
  - a failed generation;
  - a value out of range;
  - in-scope fallbacks counted;
  - a write after each question;
  - resume, and a resume refused for a different judge;
  - Langfuse scores on the right trace, and Langfuse down;
  - telemetry;
  - the judge's parameters;
  - the embeddings adapter.
- `tests/unit/test_eval_report.py`: **new**, 19 tests. Means over scored questions,
  `compare`'s six refusals and its allowed differences, baseline copy and its
  refusals, and the `MetricValue` invariant.
- `tests/unit/test_eval_generate.py`: **new**, 17 tests. Stage 1 on a fake
  connection, provenance, the golden set (50/45, the SHA against `git log`,
  shallow clones, dirty files), and the CLI's no-key and non-report refusals.
- `tests/integration/test_eval_generate_postgres.py`: **new**, 3 tests on the
  `_test` database. Real `answer()` writes `origin = 'eval'` to the row and the
  trace, the contexts equal `chunks.content` in rank order, the page path writes
  `'visitor'`, and `sql/05` can be applied twice.
- `tests/unit/test_contracts.py`: the two old RAGAS tests are replaced by three
  (deviation 9).
- `tests/integration/conftest.py`: the test database is also built with `sql/05`.

A mutation check: changing "NaN is missing" into "NaN is 0.0" in `ragas_runner.py`
fails `test_nan_from_ragas_is_a_missing_value_not_a_zero`. The code was restored
afterwards.

**Docs:**
- ADR-008 (Planned), written in DESIGN.
- ADR-011: an in-place note that its two preconditions are met.
- AGENTS.md: stack line, repo map, 32 targets, eval commands, `sql/00`–`05`.
- README: roadmap item 7, and the `ragas.yml` and fallback known gaps.
- KB: `evaluation/ragas-metrics.md` (the regression policy replaced, how a run is
  read) and `pydantic/models.md`.

## What deviated from design

1. **The `eval` extra needed more than the RAGAS pin.** With only `ragas>=0.4.3`,
   pip resolved `langchain-community` 0.4 and `langchain` 1.x, and `import ragas`
   failed: ragas 0.4.3 imports `langchain_community.chat_models.vertexai`, which
   0.4 removed. It also picked `instructor` 1.3.2. The extra now bounds
   `langchain`, `langchain-core` and `langchain-openai` below 1,
   `langchain-community` below 0.4, and `instructor` at 1.11 or above. The pinned
   set was installed into a **fresh venv**: `pip check` was clean, and the four
   metrics and `llm_factory` imported.
2. **The judge runs at temperature 0.0 without `top_p`.** DESIGN did not set them.
   RAGAS's defaults send `temperature=0.01` **and** `top_p=0.1`. Recent Claude
   models refuse a request that sets both. Whether Opus 5.5 does is **unverified**,
   because no key exists. Dropping `top_p` avoids the question either way, and
   temperature 0 matches the generator and lowers judge noise.
   `JudgeConfig.temperature` records it, and `compare` refuses a different
   temperature. `compare` also refuses a different `max_tokens`, which DESIGN did
   not list.
3. **A shallow clone is refused, and both workflows fetch the full history.** In a
   depth-1 checkout (the `actions/checkout` default), `git log -1 -- FILE` names
   the only commit whatever last touched the file. The run would record a wrong
   SHA with no error, which defeats ADR-011's comparability rule.
4. **The whole scoring runs in one event loop.** The first draft called
   `asyncio.run` per question. The async client's connection pool belongs to its
   first loop, so the draft would have failed from the second question on. This
   was caught in review before any test, so the test suite does not prove it. See
   gaps.
5. **`ReportComparison` is a new contract**, so `compare()`'s public signature is
   typed (AGENTS.md: no `dict[str, Any]`). DESIGN did not list it.
6. **Two validators DESIGN did not list:**
   - `GoldenQuestion` requires an `expected_answer` exactly when the question is in
     scope;
   - `EvalRecord` requires one context per source.

   Both turn a malformed file into an error at load, not a wrong score later.
7. **`ci.yml` applies `sql/04` and `05`** to its main database. It applied only
   `00`–`03`. The tests use the `_test` database, which conftest builds from all
   files, so nothing failed before. The change keeps CI's database equal to
   `make bootstrap`'s.
8. **`ragas.yml` runs `verify_adversarials.py` as its own step**, and uploads the
   output directory with `if: always()`, so a run that fails late still keeps its
   answers.
9. **The old RAGAS contract tests passed vacuously against the new models.** Both
   expected a `ValidationError`, and got one because the old field names no longer
   exist, not because of the bounds they named. They are replaced by tests of the
   new bounds.
10. **`compare --gate` is not built.** ADR-008 describes it, but it has no threshold
    to apply until the noise measurement has run. `compare` reports, and exits 1
    only when the two reports are not comparable.
11. **`make eval-dry` (a DEFINE COULD) is not built.**

## Found during BUILD, not changed

- **RAGAS's answer relevancy returns 0.0, not NaN, when the judge generates no
  question.** It also returns 0 when every generated question is noncommittal,
  which is a real result for a fallback. The empty case is RAGAS's own
  definition, so the runner keeps it as a score. A run where the judge
  systematically returns empty questions would show up as low relevancy, not as
  missing values.
- **ADR-019 line 189 names `fallback_accuracy` in `RAGASAggregate`.** That field no
  longer exists. ADR-019 is Accepted history, and its claim was already
  superseded by ADR-020's measurement, so it is not edited.
- **ADR-021 still reads "Planned — Accepted when BUILD lands"** (noted in DESIGN).
- **The local `.env` still has `RERANK_TOP_K=5`.** Every run now records
  `rerank_top_k`, and `compare` prints a difference.

## RAGAS delta

**Not measured. No API key exists.** This feature builds the instrument, and no
score has been produced. Retrieval, prompt, model and context format are
unchanged: the `origin` keyword only writes a column.

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | pending | pending | — |
| Context Precision | pending | pending | — |
| Answer Relevance | pending | pending | — |
| Context Recall | pending | pending | — |
| Fallback rate | pending (ADR-020) | pending | — |

## Known gaps at merge time

- **No real run.** The real judge path (instructor and `AsyncAnthropic` against
  Opus 5.5) has not run once. Unverified:
  - whether Opus 5.5 accepts the parameters;
  - whether 4096 tokens truncates;
  - whether one event loop holds across 45 questions.

  The first `make eval-ci` answers all three.
- **No cost figure.** The judge's tokens per question are unknown until a run.
  D9's measurement is 2 generations and 4 scorings.
- **No regression threshold** (ADR-008, Decision 7). `ragas.yml` stays manual.
- **CI's test job installs the eval extra.** Its added install time is not
  measured until CI runs this branch.
- **ADR-008 stays Planned** until this lands. Its threshold section is filled in
  place after the measurement.

## Verification

- [x] `make lint`: exit 0. bandit flagged the loader's fixed git call, which is
      the package's first `subprocess`; it is marked with `# nosec B603 B607`
      and a reason. The golden-set yamllint errors existed before this branch
      and are ignored by the Makefile (`|| true`)
- [x] `make test`: 410 passed, 0 skipped, exit 0
- [ ] `make eval`: not run, no key (see RAGAS delta)
- [x] `make eval` with the contamination gate failing (`CORPUS_DIR=/nonexistent`):
      the gate's message, make exit 2, no run file written
- [x] `make eval` with no key: "ANTHROPIC_API_KEY is empty", exit 2, no run file
- [x] `make bootstrap` twice on the populated local database: exit 0 both times,
      304 chunks intact, `query_log` at 23 columns
- [x] `make verify-indexes`: exit 0. No index or retrieval query changed, so
      `sql/99_verify.sql` is not modified and there is no new EXPLAIN ANALYZE to
      paste. Stage 1's chunk lookup is by primary key
- [x] The eval pins resolve in a fresh venv: `pip check` clean, RAGAS imports
