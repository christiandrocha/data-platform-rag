# Project: data-platform-rag

> RAG answer engine grounded on the architecture decisions of a two-pipeline data platform (Kafka + Debezium CDC into Snowflake and Databricks).
> Single source of truth for any coding agent reading this repo. Read this file first.

---

## Stack

- **Language**: Python 3.11+
- **Vector store**: PostgreSQL 16 + pgvector 0.7+ (HNSW indexes with tuned parameters)
- **Sparse search**: PostgreSQL full-text search (GIN + tsvector) for hybrid retrieval
- **Embedding**: `bge-small-en-v1.5` via sentence-transformers (384-dim, local)
- **Reranker**: `bge-reranker-base` cross-encoder (post-retrieval scoring, local)
- **LLM**: Anthropic Claude Sonnet via API (retrieval-augmented generation only)
- **Contracts**: pydantic v2 for all inter-module boundaries — config, chunk metadata, retrieval results, LLM output, RAGAS reports
- **Observability**: Langfuse (cloud free tier initially) — traces every query, tracks Claude cost, receives RAGAS scores as feedback
- **Evaluation**: RAGAS framework — golden set of 50 questions, runs in CI on every push, scores pushed to Langfuse
- **UI**: Streamlit
- **Orchestration**: Makefile (14 targets: bootstrap, index, eval, dev, deploy, and observability targets)
- **Quality**: ruff, pytest, yamllint, bandit, pre-commit
- **CI/CD**: GitHub Actions (lint, test, ragas, streamlit deploy)
- **Methodology**: AgentSpec/SDD — six-phase workflow (brainstorm → define → design → build → iterate → ship)

### Corpus sources

Two external repositories, indexed offline (not runtime):

- **`sdd-kafka-snowflake-2`** — PostgreSQL WAL → Debezium → Kafka → Snowflake (dbt + Dagster)
  - 12 ADRs + README + 3 dbt macros. The Schema Registry subjects are **not**
    corpus: no `.avsc` or subject file exists in the repo, because they live in a
    running registry that `scripts/sync_metadata.py` reads over the network. The
    `schema` source type therefore has no v1 producer (ADR-012).
- **`sdd-kafka-databricks`** — PostgreSQL WAL → Debezium → Kafka → Databricks (Lakeflow + Unity Catalog)
  - 9 ADRs + README + 21 YAML data contracts

The `data-platform-rag` repo is NOT indexed as a corpus source. It is the
knowledge layer over the platform, not part of the platform itself. Its own
ADRs document the design decisions of the RAG system and live in `docs/adr/`
for repo consumers to read directly.

---

## Repo map

```text
data-platform-rag/
├── AGENTS.md                   # This file — read first
├── CLAUDE.md → AGENTS.md       # Symlink for Claude Code
├── README.md                   # Public-facing overview + RAGAS badges + Langfuse public dashboard link
├── LICENSE                     # MIT
├── Makefile                    # 14 operational targets
├── pyproject.toml              # ruff + pytest + pydantic/pydantic-settings + langfuse
├── docker-compose.yml          # postgres+pgvector for local dev
├── Dockerfile                  # streamlit runtime
├── .env.example                # documented env vars, secrets blank
├── .pre-commit-config.yaml
├── .yamllint.yml
├── .gitignore
│
├── .claude/                    # AgentSpec / SDD framework
│   ├── sdd/                    # 5 phase templates + WORKFLOW_CONTRACTS
│   ├── commands/workflow/      # slash commands per phase
│   ├── agents/                 # specialized agents (ai-ml, data-engineering, code-quality)
│   ├── kb/                     # curated knowledge base (rag, pgvector, langfuse, pydantic, evaluation)
│   └── dev/                    # ephemeral work-in-progress
│
├── docs/
│   ├── adr/                    # canonical ADRs of THIS project's decisions
│   └── golden-set/             # RAGAS evaluation questions + expected answers
│
├── data_platform_rag/                  # Application code (importable package)
│   ├── config.py               # pydantic-settings — all env-derived config
│   ├── contracts.py            # pydantic models for all inter-module boundaries
│   ├── indexer/                # loader, chunker, embedder, writer
│   ├── retrieval/              # intent_classifier, hybrid_search, reranker, pipeline
│   ├── generation/             # prompt, client, fallback logic
│   ├── observability/          # langfuse_client, decorators, no-op fallback
│   ├── evaluation/             # ragas_runner, golden_set_loader, langfuse_scorer
│   └── ui/                     # streamlit app
│
├── sql/                        # DDL and index definitions
├── scripts/                    # operational scripts
├── tests/                      # pytest suite (unit + integration)
├── observability/              # optional local grafana configs (v2, not v1)
└── .github/workflows/          # ci.yml, ragas.yml, deploy.yml
```

---

## Conventions

### ADR discipline (load-bearing)

- Every non-trivial decision gets an ADR in `docs/adr/`. Format follows the
  convention used in `sdd-kafka-snowflake-2` and `sdd-kafka-databricks`:
  Status, Context, Decision, Consequences, Alternatives Considered.
- Reversals are documented in-place. Never rewrite history — supersede
  explicitly (as in ADR-006 reverting ADR-003 in the databricks project).
- Debts and unverified claims go in a Known Gaps section of the README.

### pgvector performance discipline

- Every vector column gets an HNSW index. Parameters (`m`, `ef_construction`,
  `ef_search`) tuned against the golden set, documented in the ADR.
- Index recreation is scripted (`sql/02_indexes.sql`) and versioned. No
  ad-hoc `CREATE INDEX` in migrations.
- Hybrid retrieval combines dense (pgvector cosine) + sparse (GIN tsvector)
  via reciprocal rank fusion. Weights are RAGAS-tuned, not guessed.
- Query plans are inspected. `EXPLAIN ANALYZE` output for the top query
  patterns lives in `sql/99_verify.sql` as regression baseline.

### Contract discipline (pydantic)

- Every inter-module boundary uses a pydantic model from `data_platform_rag/contracts.py`.
- No `dict[str, Any]` as public function signature. Exceptions need an ADR.
- Config is pydantic-settings, singleton via `@lru_cache`, no `os.getenv` in
  application code.
- LLM structured output is validated via pydantic with a one-shot repair
  retry on ValidationError, safe default on repair failure.

### Observability discipline (Langfuse)

- Every user query produces one Langfuse trace with child spans per pipeline
  stage. The Generation entity (Anthropic call) is Langfuse-native.
- RAGAS scores from evaluation runs push to Langfuse attached to the trace
  that produced the query — same score system for eval and production.
- Langfuse client is a singleton with no-op fallback: `LANGFUSE_ENABLED=false`
  disables all Langfuse calls without changing the pipeline code.
- Never block the query pipeline on Langfuse. Fire-and-forget; log failures
  locally and continue.

### RAG discipline

- Never return an answer without at least one retrieved chunk citation. If
  retrieval score falls below threshold, use the fixed fallback message
  pointing to LinkedIn.
- The system prompt is versioned in `data_platform_rag/generation/prompt.py`, not
  scattered in code.
- Every query is logged in Postgres `query_log` AND emits a Langfuse trace.
  Postgres log is source of truth for analytics; Langfuse is source of truth
  for observability and scoring.

### AgentSpec workflow (when adding features)

Six phases: `brainstorm → define → design → build → iterate → ship`.
Each feature lives under `.claude/sdd/features/{feature-slug}/` with the
phase artifacts. See `.claude/sdd/architecture/WORKFLOW_CONTRACTS.yaml`.

---

## Commands

```bash
# Environment
make bootstrap                  # start postgres+pgvector, run migrations, seed extensions
make dev                        # run streamlit locally against local db
make down                       # stop containers

# Data pipeline
make fetch-corpus               # clone, extract in-corpus files, write MANIFEST, delete clone
make index-corpus-dry           # chunk the snapshot per ADR-007, report tokens, write nothing
make index-corpus               # chunk, embed, upsert into pgvector (slice 2, not yet built)
make reindex                    # drop and rebuild vectors (destructive)
make verify-indexes             # EXPLAIN ANALYZE the top queries, compare to baseline

# Evaluation
make eval                       # run RAGAS against golden set, push scores to Langfuse
make eval-ci                    # eval + write results to .claude/dev/reports/ragas-{timestamp}.json
make golden-set-check           # validate golden-set/*.yml schema + ADR coverage
make golden-set-next            # next uncovered ADR in the seeded walk order
make golden-set-next-architecture        # next uncovered README section / contract / macro
make golden-set-next-comparison-pair     # next cross-project ADR pair for a comparison question
make verify-adversarials        # Layer 1: literal contamination probes (blocks eval)
make audit-adversarials q=q005  # Layer 2: Opus semantic audit (advisory)

# Observability
make langfuse-check             # verify Langfuse credentials and connectivity
make langfuse-flush             # force flush pending observations (useful before deploy)

# Quality
make lint                       # ruff check + yamllint + bandit
make test                       # pytest -q
make precommit                  # run all pre-commit hooks

# Deploy
make deploy                     # push to streamlit cloud (via git)
```

**Corpus location.** Scripts that read the corpus default to the newest
`/tmp/dpr-corpus-*`, created by `make fetch-corpus` (ADR-012). Local dev may override
`--corpus-dir` (or `CORPUS_DIR=` for make targets) for iteration speed; CI uses
the default for reproducibility — a GitHub Actions runner has no `~/Documents`,
so `/tmp` is the only path that works in both environments.

---

## Boundaries

What an agent working on this repo must **NEVER** do:

- **Never index the data-platform-rag repo itself as a corpus source.** The corpus
  is `sdd-kafka-snowflake-2` and `sdd-kafka-databricks` only. Self-indexing
  introduces recursion risk and was explicitly rejected.
- **Never bypass ADR discipline.** Any architectural change gets an ADR
  before code. If in doubt, write the ADR first.
- **Never invent RAGAS scores.** Numbers in the README come from
  `make eval-ci` runs, timestamped. If eval hasn't run, badges show
  "pending", never a fabricated number.
- **Never remove the out-of-scope fallback.** Questions outside the corpus
  MUST return the LinkedIn redirect. Product decision, not bug.
- **Never store secrets in the repo.** `.env.example` has all keys with
  blank values. Real values live in `.env` (gitignored) locally, in GitHub
  Actions secrets in CI, in Streamlit Cloud secrets in production.
- **Never index the target repos as full clone.** The corpus is the extracted
  in-corpus file set, never the whole tree. `make fetch-corpus` shallow-clones
  each repo, copies only in-corpus files into `/tmp/dpr-corpus-{timestamp}/`,
  writes a `MANIFEST.json` recording the commit SHA and a sha256 per file, and
  deletes the full clone before exiting. The extracted snapshot persists until
  the next `fetch-corpus` — that is deliberate, and its consumers depend on it
  (ADR-012).
- **Never re-declare the in-corpus file set.** It is defined once, in
  `data_platform_rag/indexer/corpus.py`. A consumer that names its own paths
  drifts from the index, and a gate wider than the index over-blocks (ADR-012).
- **Never commit generated embeddings as JSON dumps.** Embeddings live in
  Postgres. Reindex is idempotent.
- **Never skip HNSW index tuning.** Default parameters are baseline. Tuning
  ADR (`ADR-004`) must justify chosen values against the golden set.
- **Never write to `.claude/sdd/archive/`.** Read-only history of superseded
  features.
- **Never use `dict[str, Any]` as a public function signature.** Write a
  pydantic model in `data_platform_rag/contracts.py` instead.
- **Never block on Langfuse.** If the client raises, log and continue.

---

*This file is the source of truth for all coding agents (Cursor, Claude Code,
Codex). The CLAUDE.md symlink makes Claude Code read this same file. Same
principle applies to `.cursor/rules/`.*
