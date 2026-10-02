# BUILD REPORT: Measure rule 3, the LLM's out-of-scope fallback

## Metadata

| Field | Value |
|-------|-------|
| Feature | llm-fallback-eval |
| DEFINE | [DEFINE.md](DEFINE.md) (Amendment 1, 2026-10-02) |
| DESIGN | [DESIGN.md](DESIGN.md) |
| ADR | [ADR-020](../../../../docs/adr/ADR-020-llm-rule-3-as-the-out-of-scope-gate.md), Planned |
| Start date | 2026-10-02 |
| End date | — (code done 2026-10-02. The 30 questions and the measurement remain) |
| PR | — |

## What was built

BUILD order steps 1–5 of DESIGN's Rollout. Step 1 (ADR-020) was committed with the
DESIGN. Step 6 (the 30 questions) is next, in approval batches. **No API call was
made.**

**Generation**

- `data_platform_rag/generation/client.py` (new): `build_user_message()` in context
  format v1.0.0, and `generate()` with an injected client. No `anthropic` import,
  no `thinking` parameter. Empty `chunks` raises before any call.
- `data_platform_rag/generation/fallback.py` (new): `classify_output()`, four
  classes in order: `empty`, `fallback`, `non_compliant_refusal`, `answer`.
- `data_platform_rag/generation/prompt.py`: `CONTEXT_FORMAT_VERSION = "v1.0.0"`.
  `SYSTEM_PROMPT` and `FALLBACK_MESSAGE` are byte-unchanged, so the version stays
  v1.1.0.
- `data_platform_rag/contracts.py`: `OutputClass`, `QuestionSource`,
  `OutOfScopeBand`, `GenerationResult`, `RetrievedSource`, `FallbackEvalItem`,
  `FallbackRunSummary`, `FallbackEvalReport`, as DESIGN specifies.
- `data_platform_rag/config.py`, `.env.example`: `llm_max_tokens` (1024),
  `llm_temperature` (0.0).

**The measurement**

- `scripts/fallback_eval.py` (new). The preflight (configuration, key,
  `anthropic`, both files, population) runs before retrieval and before any write,
  and exits 2. Retrieval runs once per question in its own database session, which
  is closed before the first call. Then 3 runs, the artifact, and the numbers
  without a verdict. A failure or Ctrl-C produces an incomplete artifact with no
  summaries, and exit 1. `--dry-run` needs no key.
- `Makefile`: `fallback-eval`, `fallback-eval-dry`.

**The question files**

- `docs/golden-set/out_of_scope_questions.yml` (new): the header comment and `[]`.
- `docs/golden-set/evaluation_questions.yml`: one `band:` line on each of the 5
  out-of-scope entries (q005, q047, q048 adjacent. q049 off_domain. q050
  adversarial). Nothing else.
- `scripts/validate_golden_set.py`: `check_band`, `check_out_of_scope_set`, and
  the per-entry loop extracted to `check_entries`, shared by both files. Also
  `validate_golden`, `validate_out_of_scope_set` and `load_question_file`. `main`
  validates both files.
- `scripts/verify_adversarials.py`: `load_adversarials()` over both files. A
  missing file is an error.

**Tests** (all unit, no network, no key, no `anthropic`)

- `tests/unit/test_fallback.py` (8), `test_generation_client.py` (9),
  `test_fallback_eval.py` (13), `test_verify_adversarials.py` (4). Extended:
  `test_validate_golden_set.py` (+19, 44 → 63), `test_config.py` (+5).
- Suite: **272 passed, 21 skipped** (the skips are the Postgres integration
  tests, which `make test` runs without a database).

**Docs**

- KB: `pydantic/models.md` (new contracts, and the "where used" table),
  `pydantic/config-pattern.md` (two settings), `rag/rag-architecture.md` (the
  pipeline line and a generation paragraph).
- `docs/golden-set/README.md`: the out-of-scope fields, `band`, and the new set.
- `AGENTS.md`: the two new commands.

## What deviated from design

1. **The preflight also checks the population (45 in-scope + 35 out-of-scope).**
   It is not in DESIGN's preflight list. ADR-020's thresholds are counts (34/35,
   4/45), so a run on any other population would read a rule written for different
   denominators. `make fallback-eval` refuses it with exit 2 until the set is
   complete. `--dry-run` only prints a note. Today's files hold 45 + 5.
2. **An incomplete artifact's file name ends in `-incomplete`.** This is an
   addition. The JSON's `complete: false` is the record, and the file name makes
   it visible in a directory listing too. That helps when the Outcome lists every
   artifact.
3. **The script prints the fallback count per band**, computed from the items.
   It is not a field of `FallbackRunSummary`, so the contract is as designed. P1
   and P2 are judged per band, and the artifact already holds what this line
   prints.
4. **`AGENTS.md` and `docs/golden-set/README.md` were edited.** Neither is in
   DESIGN's file table. The README documents the schema `band` joins. AGENTS.md
   lists the commands. AGENTS.md's Makefile count said **25** and was already
   stale: there were 27 targets at HEAD. It now says 29, the real count.
5. **The KB pipeline line was stale beyond this feature.** `rag-architecture.md`
   still drew "Reranking → Threshold check", which ADR-005 and ADR-019 removed. It
   was rewritten while mirroring the generation step. `models.md`'s `RetrievedChunk`
   row named a reader that does not exist (`retrieval/reranker.py`). It now names
   the two that do.
6. **Formatting of untouched code was reverted.** The `ruff-format` pre-commit
   hook, run by hand, reformatted three existing files throughout:
   `validate_golden_set.py`, its test, and `verify_adversarials.py`. Those files
   were not ruff-formatted at HEAD, and 11 files in the repo still are not. The
   reformat was undone mechanically. The diff from "HEAD formatted" to "current"
   was patched onto the original HEAD, and each result was checked to format back
   to the current file. Only this feature's lines changed. The new files are
   ruff-formatted.
7. **`measure()` catches every exception** (`noqa: BLE001`). This is deliberate:
   per D3, any failure after calls began makes the artifact incomplete, never
   silent.
8. **Missed in BUILD, found at the first question batch (2026-10-02): the Layer 2
   audit read only the golden set.** `scripts/audit_questions.py` loaded
   `evaluation_questions.yml` alone, so `make audit-adversarials q=oos001` would
   have found no question. The new set's Layer 2 audit, which DESIGN and ADR-016
   require, could not have run. It now reads both files through
   `verify_adversarials.QUESTION_FILES`, the list Layer 1 already uses, so the two
   layers cannot drift apart. Three unit tests were added
   (`tests/unit/test_audit_questions.py`). DESIGN's file table did not list the
   script, which is how it was missed.

## RAGAS delta

Not measured. `make eval` is a stub (`scripts/run_evaluation.py` prints "not yet
implemented"), and RAGAS is a non-goal of this feature (DEFINE). This feature's
own number is `make fallback-eval`'s, and it waits for an API key and the 30
questions. Retrieval is unchanged.

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | pending | pending | — |
| Context Precision | pending | pending | — |
| Answer Relevance | pending | pending | — |
| Context Recall | pending | pending | — |
| Fallback rate | pending | pending (ADR-020's B1 and B2, at the measurement) | — |

## Known gaps at merge time

- **The 30 out-of-scope questions do not exist yet.** They come next, in 6
  batches of 5, each approved before it is applied, with `make verify-adversarials`
  green after each batch (ADR-016 terms).
- **The measurement waits for an API key.** Before running it: `pip install -e .`
  (`anthropic` is declared in `pyproject.toml` but not installed in `.venv`), then
  DESIGN's measurement steps 1–4, including the byte-identity check recorded in
  ADR-020.
- **Layer 2 audits of the new set** (`make audit-adversarials`) also wait for a key.
- **Langfuse and `query_log`** are not wired to generation (DEFINE non-goal).
- **Pre-existing, not this feature's:**
  - `make lint` hides yamllint failures behind `|| true`: long lines in
    `evaluation_questions.yml`, and a missing final newline in
    `corpus_inventory.yml`. The same errors occur at HEAD. The new file has none.
  - `make lint` fails with "bandit: No such file or directory" unless `.venv/bin`
    is on `PATH`.
  - The pre-commit hook is not installed (`.git/hooks/pre-commit` is absent).

## Verification

- [x] `make lint`: ruff clean. bandit clean (run from `.venv`). yamllint shows
      only the pre-existing errors above, and none in the files this feature added
- [x] `make test`: 272 passed, 21 skipped
- [ ] `make eval`: **not run**. It is a stub (RAGAS delta above)
- [ ] `make verify-indexes`: **not run.** No schema, index or query change.
      `retrieve(question, top_k=3)` is the existing query with a smaller `LIMIT`
- [x] `make golden-set-check`'s validator: golden set 50 valid. Out-of-scope set
      0/30, reported as "curation incomplete"
- [x] **Manual, local database** (snapshot `sdd-kafka-databricks@f1295df9`,
      `sdd-kafka-snowflake-2@82a2e269`, 304 chunks, the snapshot ADR-019 measured):
  - `make fallback-eval-dry` retrieved all 50 current questions and printed q001's
    real user message. ADR ids are copied verbatim (`ADR-0029`, `ADR-001`). A chunk
    without an anchor has no `section`. It ended "50 question(s), 3 run(s) = 150
    call(s) when measured. Nothing called, nothing written." It will be 240 once
    the set holds 80
  - `make fallback-eval` with the empty key from `.env` printed "ANTHROPIC_API_KEY
    is empty…" and exited 2. `.claude/dev/reports/` held 23 files before and after
