# DESIGN: Measure rule 3, the LLM's out-of-scope fallback

> [DEFINE.md](DEFINE.md). How the measurement is built so it can run unchanged the
> day an API key exists.

## Metadata

| Field | Value |
|-------|-------|
| Feature | llm-fallback-eval |
| Depends on | [DEFINE.md](DEFINE.md) (14/15, Q1–Q3 settled 2026-09-30, Amendment 1 2026-10-02) |
| Date | 2026-10-02 |
| Status | Reviewed (D1–D5 settled by the author, 2026-10-02) |
| ADR needed | Yes: [ADR-020](../../../../docs/adr/ADR-020-llm-rule-3-as-the-out-of-scope-gate.md), Status Planned until the measurement |

## Q4, answered

DEFINE left Q4 to DESIGN: the model id, `max_tokens`, and the context format.

- **Model: `claude-sonnet-4-6`**, as `settings.llm_model` already has it. Checked
  on 2026-10-02 against the Claude API reference (the `claude-api` skill, model
  table cached 2026-09-25): a current model, $3 / $15 per MTok. The newer
  `claude-sonnet-5-5` was considered and **rejected by the author on 2026-10-02**:
  it returns a 400 on any non-default `temperature`, which reopens Q3, and its
  safety classifiers can end a turn with `stop_reason: "refusal"`, an output
  DEFINE's three classes do not cover. ADR-020's reading holds for
  `claude-sonnet-4-6` only. A model change is a re-measurement under the same rule.
- **No `thinking` parameter.** On Sonnet 4.6, omitting it means no extended
  thinking. That is the cheaper, more repeatable setting, and it is the one
  measured. Turning thinking on later is a change to what was measured.
- **`temperature = 0.0`** (DEFINE Q3). Sonnet 4.6 accepts it.
- **`max_tokens = 1024`.** Rule 5 caps answers at 300 words, about 400 tokens, and
  the fallback is about 50. 1024 leaves room so a long answer is not cut. A cut one
  is still classified, because the class depends only on the text. Every output
  records its `stop_reason`, and the script lists any `max_tokens` stop by id.
- **Context format:** below, under Interfaces.

## Architecture overview

```text
make fallback-eval
  │
  ├─ preflight: key present? anthropic importable? both question files load?
  │     └─ any no → message on stderr, exit 2, nothing written
  │
  ├─ for each of the 80 questions (45 in-scope golden + 5 golden OOS + 30 new OOS):
  │     retrieve(question, top_k=settings.rerank_top_k)        ← once per question
  │
  ├─ for run in 1..3:
  │     for each question:
  │         generate(question, chunks, client)  →  GenerationResult
  │         classify_output(result.text)        →  fallback | non_compliant | empty | answer
  │
  ├─ summarize_run(items) per run  →  B1 and B2 inputs, ids per failure
  │     (only when all 3 runs completed: an incomplete artifact has no numbers)
  └─ write .claude/dev/reports/fallback-eval-{timestamp}.json, print numbers, no verdict
```

**What changes:**

| file | change |
|---|---|
| `data_platform_rag/generation/client.py` | **new.** `build_user_message()`, `generate()` |
| `data_platform_rag/generation/fallback.py` | **new.** `classify_output()` |
| `data_platform_rag/generation/prompt.py` | adds `CONTEXT_FORMAT_VERSION`. `SYSTEM_PROMPT` and `FALLBACK_MESSAGE` are untouched, so `SYSTEM_PROMPT_VERSION` stays `v1.1.0` |
| `data_platform_rag/contracts.py` | adds the models under Data contracts |
| `data_platform_rag/config.py`, `.env.example` | `llm_max_tokens`, `llm_temperature` |
| `scripts/fallback_eval.py` | **new.** The measurement |
| `docs/golden-set/out_of_scope_questions.yml` | **new.** The 30 questions, curated in batches after BUILD's code (below) |
| `docs/golden-set/evaluation_questions.yml` | a `band` line on each of the 5 out-of-scope entries, nothing else |
| `scripts/validate_golden_set.py` | validates the new file too |
| `scripts/verify_adversarials.py` | greps the probes of both files |
| `Makefile` | `fallback-eval` target, `golden-set-check` covers the new file |
| `docs/adr/ADR-020-…`, `docs/adr/index.md` | the ADR, Planned |
| `.claude/kb/pydantic/models.md`, `.claude/kb/rag/rag-architecture.md` | mirror the new contracts and the generation step (KB drift rule) |

**What stays:** retrieval (`pipeline.retrieve` is called, not changed), the
schema, the index, the system prompt text, every golden-set field other than the
new `band`.

**Retrieval runs once per question, not once per call.** Exact-scan retrieval is
deterministic (ADR-018), so 3 retrievals would return the same chunks. Running it
once makes the context of a question identical across the 3 runs, by
construction: the only thing that varies between runs is the LLM.

## Data contracts

### New pydantic models (`contracts.py`)

```python
OutputClass = Literal["fallback", "non_compliant_refusal", "empty", "answer"]
QuestionSource = Literal["golden", "out_of_scope_set"]
OutOfScopeBand = Literal["adjacent", "personal", "off_domain", "adversarial"]


class GenerationResult(BaseModel):
    """One Claude call: what came back, and what it cost."""
    model_config = ConfigDict(frozen=True)

    text: str                     # text blocks joined, in order. May be ""
    model: str                    # response.model, as the API reports it
    stop_reason: str | None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class RetrievedSource(BaseModel):
    """What a question's context was built from. Citation fields only, no text."""
    model_config = ConfigDict(frozen=True)

    chunk_id: int
    source_project: SourceProject
    source_path: str
    source_anchor: str | None
    adr_id: str | None
    dense_distance: float = Field(ge=0.0)


class FallbackEvalItem(BaseModel):
    """One question in one run."""
    model_config = ConfigDict(frozen=True)

    run: int = Field(ge=1)
    question_id: str
    source: QuestionSource
    intent: str                   # the golden-set intent, verbatim
    band: OutOfScopeBand | None   # every out-of-scope question; None in-scope
    expects_fallback: bool
    retrieved: list[RetrievedSource]
    output_text: str
    output_class: OutputClass
    stop_reason: str | None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class FallbackRunSummary(BaseModel):
    """The two numbers DEFINE's rule reads, for one run. Counts, not a verdict."""
    model_config = ConfigDict(frozen=True)

    run: int = Field(ge=1)
    out_of_scope_total: int       # 35
    out_of_scope_fallback: int    # B1 numerator
    in_scope_total: int           # 45
    in_scope_false_fallback: int  # B2 numerator: fallback + non-compliant + empty
    missed_ids: list[str]                 # OOS, class answer or empty
    non_compliant_out_of_scope_ids: list[str]  # OOS, class non_compliant_refusal
    false_fallback_ids: list[str]         # in-scope, fallback, non-compliant or empty
    empty_ids: list[str]                  # either side, class empty
    non_end_turn_ids: list[str]           # any stop_reason other than end_turn


class FallbackEvalReport(BaseModel):
    """The artifact. Everything needed to re-read the measurement later."""
    created_at: datetime
    complete: bool                # False: not a reading (Rollout)
    incomplete_reason: str | None  # the exception, or "interrupted"; None if complete
    model: str
    temperature: float
    max_tokens: int
    runs_requested: int
    top_k: int
    system_prompt_version: str
    system_prompt_sha256: str
    context_format_version: str
    golden_set_sha256: str
    out_of_scope_set_sha256: str
    snapshots: list[IndexedSnapshot]
    summaries: list[FallbackRunSummary]  # empty when complete is False
    items: list[FallbackEvalItem]
    total_input_tokens: int
    total_output_tokens: int
```

`system_prompt_sha256` exists because a version string is a promise and a hash is
a fact: an edit to `SYSTEM_PROMPT` that forgets to bump the version still changes
the hash. The two question-file hashes do the same for the sets.

`AnswerResult`, `RAGASReport` and `RAGASAggregate` are not touched. `AnswerResult`
needs an intent classifier and a Langfuse trace id, neither of which exists, so
it stays the shape the product path will grow into. This feature's path is the
evaluation path.

### The new question file: `docs/golden-set/out_of_scope_questions.yml`

Same entry shape as the golden set's out-of-scope entries, `band` included:

```yaml
- id: oos001
  provenance: llm
  voice: technical
  intent: out-of-scope
  band: adjacent
  question: "..."
  expected_answer: null
  expected_source_paths: []
  contamination_probes:
    - "..."
  grep_verified: 2026-10-0X
```

- **ids** `oos001`–`oos030`, a prefix that cannot collide with `qNNN`.
- **`band`**, required on **every out-of-scope question in both files** and
  rejected on in-scope ones. It is what lets the Outcome judge P1 (misses
  concentrate in the adjacent band) and P2 per band, instead of by reading
  question text. P1 and P2 name golden questions, so the golden 5 carry it too,
  as ADR-016 item 4 already classified them: q005 Flink versus Kafka Streams,
  q047 Airflow and q048 Iceberg **adjacent**, q049 React **off_domain** ("one
  trivially off-domain question"), q050 prompt extraction **adversarial**.
- **Band counts in the new file: 12 adjacent, 6 personal, 6 off-domain, 6
  adversarial** (author, 2026-10-02). With the golden 5, the 35 are **15 adjacent,
  6 personal, 7 off-domain, 7 adversarial**. Weighted towards adjacent because
  that is where ADR-019 found similarity highest and where P1 expects the misses.
  The weighting is a choice, not a fact about visitors. No visitor traffic exists
  to take a mix from. It makes B1 stricter: a pass means more, and a fail may
  partly reflect the emphasis. The Outcome reports per-band counts, not rates,
  because a band of 6 or 7 is too small for one.
- **Disjoint from the golden set:** no id and no question text shared with
  `evaluation_questions.yml` (validator).
- **Authored under ADR-016's terms:** `provenance: llm`, the author approves every
  entry, Layer 1 probes pass before commit, Layer 2 runs when a key exists, and the
  author reads every probe list. Batches of 5 per approval, as the golden set did.

## Interfaces

### `generation/prompt.py`

```python
CONTEXT_FORMAT_VERSION = "v1.0.0"
```

The user-message format lives next to the system prompt because it is part of
what the LLM reads. The artifact records both versions.

### `generation/client.py`

```python
class MessagesAPI(Protocol):
    def create(self, **kwargs: object) -> object: ...

class LLMClient(Protocol):
    messages: MessagesAPI


def build_user_message(question: str, chunks: list[RetrievedChunk]) -> str: ...

def generate(
    question: str,
    chunks: list[RetrievedChunk],
    client: LLMClient,
    *,
    model: str | None = None,          # default settings.llm_model
    temperature: float | None = None,  # default settings.llm_temperature
    max_tokens: int | None = None,     # default settings.llm_max_tokens
) -> GenerationResult: ...
```

- **The client is injected.** `generate` never constructs an `anthropic.Anthropic`
  and never imports `anthropic`. Tests pass a stub. Only `scripts/fallback_eval.py`
  imports the SDK, lazily, after the key check. The package stays importable
  without `anthropic` installed, which is the venv today.
- **`generate` raises on an empty `chunks` list.** `retrieve` never returns empty on
  a populated index, so empty means a broken index, and a call on no context would
  measure nothing.
- The call is `client.messages.create(model=…, max_tokens=…, temperature=…,
  system=SYSTEM_PROMPT, messages=[{"role": "user", "content": build_user_message(…)}])`.
  The text is every `text` block of `response.content`, joined in order.
- **SDK errors propagate.** The SDK already retries 429, 5xx and connection errors
  twice. Anything left is the script's to handle (Rollout).

### The context format (`CONTEXT_FORMAT_VERSION = "v1.0.0"`)

```text
<context>
<chunk index="1" project="sdd-kafka-databricks" source="docs/adr/ADR-007-….md" adr="ADR-007" section="Decision">
…chunk content, verbatim…
</chunk>
<chunk index="2" project="sdd-kafka-snowflake-2" source="README.md" section="Architecture">
…
</chunk>
</context>

Question: {question}
```

- **`project` and `adr` are what rule 2 cites**, "(ADR-XXXX, project-name)". `adr`
  is copied from `ChunkMetadata.adr_id` verbatim, never padded (rule 2's
  "never normalize"). It is omitted when the chunk has none (README, contract,
  macro). `section` is omitted when `source_anchor` is None.
- **Attribute values are escaped** (`&`, `<`, `>`, `"`), so a path or anchor cannot
  break the tag. Chunk content is not escaped. It is corpus text, and the corpus
  is two repos the author owns.
- **Order is retrieval rank.**

### `generation/fallback.py`

```python
def classify_output(text: str) -> OutputClass: ...
```

DEFINE's four classes (three, plus Amendment 1's `empty`), in order.
`text.strip() == ""` → `empty`. Else `text.strip() == FALLBACK_MESSAGE` →
`fallback`. Else `"linkedin.com/in/christiandrocha" in text` →
`non_compliant_refusal`. Else `answer`. The URL substring is a module constant, and a unit test checks it occurs
in `FALLBACK_MESSAGE`, so the two cannot drift apart.

### `scripts/fallback_eval.py` and `make fallback-eval`

```text
make fallback-eval            # 3 runs, writes the artifact
make fallback-eval-dry        # no key needed: retrieves, prints the 80 user messages' sizes and the first one, calls nothing, writes nothing
```

- **Preflight, in order, before retrieval or any write:** the key is non-empty
  (`settings.anthropic_api_key`, which `.env` sets to `""` when absent); `anthropic`
  imports; both question files load and validate. Any failure: one line on stderr
  naming what to do, exit code 2, no file and no directory created. **Never a stub
  fallback** (DEFINE MUST).
- **Questions:** the 45 in-scope golden questions, the 5 golden out-of-scope
  questions, all of the new file. In-scope is `intent != "out-of-scope"`, through
  `should_fallback`, the one definition the validator already owns.
- **Output:** per run, `OOS recall n/35`, `in-scope false fallback n/45`, and the
  ids of each failure list, including `empty_ids`. **Only for a complete
  artifact.** An incomplete one prints the reason and the path, and no number. Then the token totals and the artifact path. **No
  verdict.** The rule lives in ADR-020, and code that re-implemented it could drift
  from it (the same reason `retrieval_recall.py` prints no verdict).

### Config

```python
llm_max_tokens: int = Field(default=1024, ge=1, le=16000)
llm_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
```

`.env.example` gains `LLM_MAX_TOKENS=1024` and `LLM_TEMPERATURE=0.0`. The artifact
records the values used, so an `.env` override cannot change a reading silently.

## Retrieval and RAG-specific concerns

- [x] **Chunking:** no change.
- [x] **HNSW index:** no change, no reindex.
- [x] **Query pattern:** no change. `retrieve(question, top_k=3)` is the same
      exact scan with a smaller `LIMIT`. Its top 3 equal the top 3 of the default
      top 20, because the order is total (cosine distance, `id` tiebreak, ADR-018).
      No `EXPLAIN ANALYZE` baseline moves.
- [x] **RAGAS:** not run, not changed (DEFINE non-goal). The rule-3 numbers are
      reported on their own, never pooled into `fallback_accuracy`.
- **Langfuse and `query_log`:** not wired (DEFINE non-goal). `generate` is the
  evaluation path. The product path, which must trace and log every user query,
  wraps it later.
- **AGENTS.md's "never return an answer without a citation":** not enforced here.
  That is answer quality, a RAGAS concern. This feature measures only whether the
  fallback fires.

## Alternatives considered

- **Retrieve on every call (240 retrievals).** Same result by determinism, 3× the
  embedding work, and a context that is identical across runs only by argument
  rather than by construction. Rejected.
- **Claude Sonnet 5.5.** Rejected by the author on 2026-10-02 (Q4 above).
- **Message Batches API (50% cheaper).** Results arrive asynchronously, possibly
  hours later, and the script becomes submit-then-poll. At 240 short calls the
  saving does not pay for the second code path. A re-measurement at scale could
  revisit it.
- **Prompt caching on the system prompt.** `SYSTEM_PROMPT` is 2,265 characters
  (329 words). Its token count and Sonnet 4.6's minimum cacheable prefix are both
  unmeasured. A prefix under the minimum is silently not cached, so whether caching
  would work at all is unknown, and a cost saving is not worth an unknown in the
  thing being measured. Left out. The artifact's token counts show what it would
  have saved.
- **Stop at the first failed call and write nothing.** It loses the outputs
  already paid for. Rejected in favour of an incomplete artifact (Rollout).
- **A `band` derived from the question text, or no band.** Derived: someone has to
  write the rule, and it would be wrong at the edges. None: P1 is judged by
  re-reading 30 questions by hand. Rejected for a declared field.
- **Re-using `validate_golden_set.py`'s 50-question distribution check for the new
  file.** It would fail: the new file is 30 out-of-scope questions. The per-entry
  checks are shared, and the distribution checks are per file.

## Test plan

No test calls the API, needs a key, or needs `anthropic` installed.

**Unit (`tests/unit/`)**

- `test_fallback.py`: the four DEFINE acceptance cases, which are exact message,
  exact message with surrounding whitespace and newlines, paraphrase with the URL,
  and an answer mentioning "LinkedIn" without the URL. Plus the empty string →
  `empty` (Amendment 1), whitespace only → `empty`, and the URL constant
  occurring in `FALLBACK_MESSAGE`.
- `test_generation_client.py`, with a stub recording the kwargs it gets:
  - `system` is `SYSTEM_PROMPT`, `model`, `temperature` and `max_tokens` come
    from settings, and there is no `thinking` key
  - the user message carries every chunk's content, project and `adr_id` verbatim,
    in rank order, and the question last
  - a chunk without `adr_id` or anchor has no `adr=` or `section=` attribute
  - an attribute value with `"` and `<` is escaped
  - two text blocks are joined. A non-text block is skipped
  - usage, `stop_reason` and `model` land in `GenerationResult`
  - empty `chunks` raises
- `test_fallback_eval.py`:
  - `summarize_run` on hand-built items: a non-compliant out-of-scope item counts
    as a B1 miss and is listed in `non_compliant_out_of_scope_ids`. A
    non-compliant in-scope item counts in B2. An empty in-scope item counts in
    B2 and in `empty_ids`. An empty out-of-scope item is a B1 miss. A
    `max_tokens` stop is listed in `non_end_turn_ids`
  - an empty key → exit 2, and the report directory (a `tmp_path`) is not created
  - `anthropic` not importable (monkeypatched import) → exit 2, nothing created
  - the whole loop with a stub client and a stub retriever: 3 runs × N questions,
    one retrieval per question, the artifact parses back as `FallbackEvalReport`
    with `complete: True`
  - a stub that raises on call k → artifact with `complete: False`, the
    exception in `incomplete_reason`, `summaries` empty, no number printed, exit 1
  - a stub that raises `KeyboardInterrupt` on call k → the same, with
    `incomplete_reason: "interrupted"`
- `test_validate_golden_set.py` (extended): the new file's rules, which are id
  pattern, `band` required and valid on every out-of-scope entry of both files,
  `band` rejected on an in-scope entry, band counts 12/6/6/6 at 30, intent
  out-of-scope only, no shared id or question text with the golden set.
- `test_verify_adversarials.py` (new): both files' out-of-scope questions are
  collected, and a missing new file is reported, not skipped.
- `test_config.py` (extended): the two settings' defaults and bounds.

**Integration:** none new. Retrieval is already covered against Postgres, and
generation needs the API.

**Manual, without a key:** `make fallback-eval-dry` against the local database
prints one real assembled user message, so the context format is read on real
chunks before any money is spent. `make fallback-eval` without a key prints the
preflight message and leaves `.claude/dev/reports/` unchanged.

## Rollout plan

**BUILD order:**

1. ADR-020 (Planned) and its index row, committed before any code (AGENTS.md:
   ADR before code).
2. Contracts, config, `prompt.py`, `fallback.py`, `client.py`, with tests.
3. `fallback_eval.py`, the Makefile targets, with tests.
4. Validator and `verify_adversarials.py` extensions, with tests. `make
   golden-set-check` must pass on an empty `[]` new file.
5. KB mirror. `make lint`, `make test`.
6. The 30 questions, in 6 batches of 5, each shown, approved and then applied,
   with `make verify-adversarials` green after each batch.

**The measurement (when a key exists):**

0. `pip install -e .` (`anthropic` is declared but not installed in `.venv`), then
   Layer 2 on the 34 LLM-written out-of-scope questions, q047–q050 and
   oos001–oos030: `make audit-adversarials q=<id>`. A finding the author accepts
   fixes the question before step 1. Moved here from each batch's merge on
   2026-10-02 (authoring log).
1. `make golden-set-check`, `make verify-adversarials`, `make index-corpus-verify`.
2. ADR-020's rule checked byte-identical to DEFINE's, with the extraction command
   recorded in ADR-020.
3. `make fallback-eval`. 240 calls.
4. The Outcome is written into ADR-020 from the artifact. Status becomes Accepted
   or Rejected per the rule.

**A failed call is not a reading.** If a call still fails after the SDK's
retries, or the run is interrupted (Ctrl-C), the script writes the artifact with
`complete: false`, the reason, and the outputs it has, then exits 1. It computes
and prints **no number** for an incomplete artifact. The rule never reads one, and
the measurement is run again from the start. This is the only re-run DEFINE's "not
re-run until it passes" allows: no reading happened.

**Closing the re-roll door.** The outputs in an incomplete artifact can still be
read by hand, so interrupting a run that looks bad and starting over would be
re-running until it passes by another name. Two things close it: no number exists
to look at, and **ADR-020's Outcome lists every artifact `make fallback-eval`
produced on the branch, incomplete ones with their reason**. An interruption is
then visible, not deniable.

**No migration, no feature flag.** Nothing user-visible changes, and there is no
UI.

**Rollback:** revert the branch. Nothing else imports the new modules, retrieval
is untouched, and no table changes. An artifact already written stays in
`.claude/dev/reports/` as a record.

## Open questions

All settled by the author on 2026-10-02, after a review of each:

- [x] **D1.** Retrieval once per question, reused across the 3 runs. Kept as drafted.
- [x] **D2.** Band counts 12 / 6 / 6 / 6 in the new file, kept. **Changed:** `band`
      is required on every out-of-scope question, the golden 5 included, because
      P1 and P2 name golden questions.
- [x] **D3.** A failed or interrupted run → `complete: false` artifact, not a
      reading, re-run from the start. **Changed:** an incomplete artifact carries no
      numbers, and ADR-020's Outcome lists every artifact, incomplete ones included.
- [x] **D4.** **Changed, through DEFINE Amendment 1:** an empty output is its own
      class and counts against B2. Any `stop_reason` other than `end_turn` is still
      listed by id. A refusal without the LinkedIn URL on an in-scope question is
      still an `answer`. That is a known limitation, recorded in ADR-020.
- [x] **D5.** DEFINE's COULD (`make ask --generate`) is left out of this BUILD. Kept.
