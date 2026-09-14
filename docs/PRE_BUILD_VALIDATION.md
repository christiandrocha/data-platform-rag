# data-platform-rag — Pre-BUILD Validation

> **Purpose**: single document to review and approve before any BUILD-phase code is written.
> If any item here is wrong or misaligned, fix it now — cost is seconds. After BUILD starts, cost is refactors.

**Status**: Awaiting approval
**Date**: 2026-09-10
**Reviewer**: Christian Rocha

---

## 1. Product intent (do not change without a new ADR)

`data-platform-rag` is a RAG answer engine grounded on **architecture decision records** from two production data engineering projects. It answers questions about *why* decisions were made, *what* trade-offs were considered, and *how* the two projects compare.

It is **not**:
- A code search tool (Sourcegraph does that)
- An implementation how-to (the source repos' READMEs do that)
- A general-purpose Christian-chatbot (out of scope)

Questions outside the corpus receive a fixed fallback pointing to LinkedIn. The fallback is a feature, not a bug — it converts scope-out into qualified leads.

**Target audience**: technical recruiters and hiring managers evaluating Christian for senior Data Engineer / AI Data Engineer roles, particularly the Rimini Street "AI Data Engineer III" and equivalent postings requiring pgvector + hybrid retrieval + RAG evaluation experience.

---

## 2. Corpus scope (fixed)

Two source repositories, indexed offline:

| Source | Content | Approximate chunks |
|--------|---------|-------------------|
| `sdd-kafka-snowflake-2` | 12 ADRs + README + macros + Schema Registry doc | ~60 |
| `sdd-kafka-databricks` | 9 ADRs + README + 21 YAML data contracts | ~90 |
| **Total** | | **~150 chunks** |

**Explicitly excluded from the corpus** (v1):
- `data-platform-rag` itself (no self-indexing — see ADR-002)
- Source code from either project (out of intent — see Section 1)
- Issues, PRs, commits from either project (out of intent)
- External references cited in ADRs (would inflate scope without adding grounded content)

If v2 ever expands the corpus, that is an ADR (`ADR-011-corpus-expansion.md`), not a silent change.

---

## 3. Stack (fixed for v1)

| Layer | Choice | Version | Locked by |
|-------|--------|---------|-----------|
| Language | Python | 3.11+ | pyproject.toml |
| Vector store | PostgreSQL + pgvector | 16 + 0.7+ | docker-compose.yml, sql/00_extensions.sql |
| Sparse retrieval | PostgreSQL GIN + tsvector + ts_rank_cd | native | sql/01_schema.sql, sql/02_indexes.sql |
| Embedding | `bge-small-en-v1.5` | 384-dim | config.py default, ADR-004 |
| Reranker | `bge-reranker-base` | cross-encoder | config.py default, ADR-005 |
| LLM | Claude Sonnet | claude-sonnet-4-6 | config.py default |
| Contracts | pydantic v2 + pydantic-settings | 2.7+ | ADR-010 |
| Observability | Langfuse (cloud free tier) | 2.50+ | ADR-009 |
| Evaluation | RAGAS | 0.2+ | ADR-008 |
| UI | Streamlit Community Cloud | 1.35+ | pyproject.toml |
| Methodology | AgentSpec / SDD | — | .claude/sdd/ |

**Deliberate exclusions** (do not add without ADR):
- Dedicated vector DB (Pinecone, Qdrant, Weaviate) — see ADR-001
- Redis cache — not justified at <50 queries/day
- Elasticsearch/OpenSearch — PostgreSQL GIN + tsvector is sufficient
- LangChain / LlamaIndex — direct pgvector + Anthropic SDK is simpler and more inspectable

---

## 4. ADR set (frozen for v1 kickoff)

| ID | Title | Status |
|----|-------|--------|
| ADR-001 | Postgres + pgvector over dedicated vector databases | Accepted |
| ADR-002 | Two logical collections in one physical table | Accepted |
| ADR-003 | Hybrid retrieval — dense + sparse via reciprocal rank fusion | Accepted |
| ADR-004 | Embedding model + HNSW parameter tuning | **Planned — decision during BUILD via benchmark** |
| ADR-005 | Reranking with bge-reranker-base cross-encoder | **Planned — decision during BUILD via A/B on golden set** |
| ADR-006 | Out-of-scope fallback message design | Accepted |
| ADR-007 | Chunking strategy per source type | **Promote to Accepted BEFORE BUILD — see Section 5** |
| ADR-008 | RAGAS in CI with regression threshold | **Planned — write during BUILD with real threshold values** |
| ADR-009 | Langfuse for LLM observability | Accepted |
| ADR-010 | Pydantic v2 as the contract language | Accepted |

---

## 5. Decisions taken from the improvement critique review

### Accepted and now committed to v1

**A. Chunking strategy per source type** — promoted from Planned to Accepted during DEFINE of first BUILD feature. Strategy:

- **ADRs** → one chunk per ADR file (preserves Context/Decision/Consequences coherence; typical size <2000 tokens)
- **READMEs** → hierarchical by `## heading` (each top-level section is one chunk)
- **YAML data contracts** → one chunk per file (small, self-contained)
- **SQL macros** → one chunk per file
- **Schema Registry docs** → one chunk per subject definition

Requires writing full `ADR-007-chunking-strategy.md` **before** the first BUILD feature that creates chunks.

**B. Intent classifier expanded to four values**: `decision`, `architecture`, `comparison`, `hybrid`. The `comparison` intent handles cross-project questions ("How do the two projects handle X differently?") which are a key use case given the trilogy positioning. Requires updating `contracts.py::Intent` Literal type.

**C. Embedding model benchmark during BUILD**. ADR-004 will be revised in scope to cover both embedding model selection AND HNSW tuning. Benchmark: `bge-small` vs `bge-base` vs `bge-large` against the golden set, measuring RAGAS Context Recall, latency, and Streamlit Cloud memory footprint. Winner ships with justification.

**D. System prompt gets project-specific context**. `data_platform_rag/generation/prompt.py` will be revised to include:
- Explicit context about the two source projects (Kafka + Debezium base, Snowflake vs Databricks destinations)
- Citation format: `(ADR-XXXX, project-name)`
- Fallback trigger instruction: "if retrieved context does not directly answer the question, return the fallback verbatim"

**E. Golden set curation as first BUILD feature**. 50 questions distributed as:
- 22 decision-seeking
- 18 architecture-seeking
- 5 cross-project comparison
- 5 adversarial (MUST fire fallback)

**F. RAGAS in CI (ADR-008)**. Write ADR-008 during BUILD with the actual regression threshold value calibrated from first eval runs. GitHub Actions job runs RAGAS on every push to `main`. If any metric drops >0.05 from previous run, CI red.

**G. Metadata enrichment — `keywords` column**. Add nullable `keywords TEXT[]` column to `chunks`. Populated during indexation via noun-phrase extraction from first paragraph of each chunk. No heavy NER — simple regex + stop word filtering. Enables future `WHERE keywords && ARRAY[...]` pre-filter without changing retrieval code today.

**H. Comment on `pg_trgm` in schema**. Add SQL comment explaining that `pg_trgm` is enabled as backup for fuzzy matching, NOT as the primary sparse retrieval mechanism. Primary sparse is `to_tsvector` + `ts_rank_cd` per ADR-003. Prevents future reader confusion.

**I. `@lru_cache` on embedder for repeated queries within session**. `maxsize=100`. Zero infrastructure cost, avoids recomputing embeddings for repeated queries.

### Deferred to v2 (documented in README Roadmap)

**J. Corpus expansion to include source code, issues, PRs** — changes product identity from "answer engine of decisions" to "code search". Reject for v1. Reconsider only if fallback rate exceeds 40% and log analysis shows implementation questions dominate.

**K. Query decomposition for complex multi-hop questions** — adds planner LLM + orchestrator + result fusion. Complexity high, real-world frequency <10%. v2.

**L. Streaming responses in Streamlit** — UX improvement. Real UX bottleneck is latency (1-3s LLM), not perceived latency. v2 if user feedback shows friction.

**M. Feedback loop (thumbs up/down in UI)** — valuable but requires UI state management and Langfuse feedback push. v2.

**N. Continuous ingestion via GitHub webhook** — source projects are stable portfolio repos, not living systems. Manual `make index-corpus` on ADR merge is sufficient. v2 only if source projects gain contributors.

**O. Redis response cache** — <50 queries/day. `@lru_cache` in-process is enough. v2.

**P. Active alerts (PagerDuty-style)** — Langfuse dashboard is passive but sufficient for portfolio scale. v2 only if the product becomes production-critical.

**Q. Performance tests (p50/p95/p99, throughput)** — meaningful at scale. Not meaningful at portfolio scale. RAGAS + EXPLAIN ANALYZE baseline in `sql/99_verify.sql` cover the real regression risks. v2.

**R. Cohere Rerank (paid)** — `bge-reranker-base` local is chosen. Cohere is a candidate for v2 only if RAGAS shows persistent context precision ceiling below 0.85 that reranker upgrade could plausibly fix.

**S. Elasticsearch / pg_search extension for BM25** — `ts_rank_cd` is BM25-like and already implemented. Migration to full BM25 is v2 only if sparse retrieval quality proves inadequate against the golden set.

### Rejected outright (do not add to v2 either)

None. All improvements from the critique are either accepted for v1 or deferred to v2 with a trigger condition documented.

---

## 6. What must change in the repo before BUILD starts

Concrete diffs to apply as part of DEFINE of the first BUILD feature:

1. **`docs/adr/ADR-004-embedding-and-hnsw.md`** — rewrite from Planned to include embedding benchmark plan. New title: "Embedding model selection and HNSW parameter tuning".

2. **`docs/adr/ADR-007-chunking-strategy.md`** — write from scratch, promote from Planned to Accepted. Per-source-type strategy from Section 5A above.

3. **`data_platform_rag/contracts.py`** — add `comparison` to the `Intent` Literal type:
   ```python
   Intent = Literal["decision", "architecture", "comparison", "hybrid"]
   ```

4. **`data_platform_rag/contracts.py::ChunkMetadata`** — add `keywords: list[str] | None = None` field.

5. **`sql/01_schema.sql`** — add `keywords TEXT[]` column to `chunks`. Add GIN index on it in `sql/02_indexes.sql`. Add explanatory comment on `pg_trgm` role.

6. **`data_platform_rag/generation/prompt.py`** — expand `SYSTEM_PROMPT` with two-project context and explicit citation format. Bump `SYSTEM_PROMPT_VERSION` to `v1.1.0`.

7. **`data_platform_rag/indexer/embedder.py`** (to be created) — decorate embedding function with `@lru_cache(maxsize=100)`.

8. **`docs/golden-set/README.md`** — already updated in previous revision. Verify count adds to 50 with 22/18/5/5 distribution.

9. **`README.md`** — add "Roadmap v2" section listing deferred items with trigger conditions.

10. **`docs/adr/index.md`** — update titles: ADR-004 (embedding + HNSW), ADR-007 (chunking strategy Accepted).

**Nothing else changes structurally.** The current 88-file, 520KB repo is otherwise correctly calibrated for BUILD start.

---

## 7. Non-negotiables for v1 publication

The product does not go live on Streamlit Cloud until all of these are true:

- [ ] All four RAGAS metrics (Faithfulness, Answer Relevance, Context Precision, Context Recall) ≥ 0.80 on golden set
- [ ] Fallback fires correctly on all 5 adversarial questions (100% accuracy on the out-of-scope subset)
- [ ] Langfuse dashboard shows traces for all queries with cost < $0.01 per non-fallback query
- [ ] CI green: lint + tests + RAGAS regression check
- [ ] README badges reflect real numbers (no "pending" placeholders on published product)
- [ ] EXPLAIN ANALYZE on top 5 query patterns shows expected index usage (HNSW + GIN)
- [ ] At least one adversarial security test — someone attempting to exfiltrate the system prompt via crafted query gets the fallback, not the prompt
- [ ] The three planned ADRs (004, 005, 008) all Accepted with real numbers in their Consequences sections

If any item above is not true, the product stays in `dev` mode with private URL only. No LinkedIn post until all green.

---

## 8. Timeline expectation

Based on scope above, informal estimate:

- **DEFINE phase for BUILD kickoff** (writing ADR-004 revised, ADR-007, ADR-008 skeletons, revising prompt.py, contracts.py, schema): **1-2 focused days**
- **BUILD phase — corpus indexing + retrieval + generation + Langfuse instrumentation**: **10-15 focused hours** across ~1 week
- **Golden set curation** (50 questions with expected sources): **6-10 focused hours** across ~1 week
- **Iteration phase — RAGAS runs, threshold calibration, embedding benchmark**: **8-12 focused hours** across ~1 week
- **Ship — deploy to Streamlit Cloud, verify, write LinkedIn Ato 1**: **2-4 hours**

**Total realistic**: 3-4 weeks of part-time work (10-15 hours/week alongside day job).

If timeline pressure demands faster: reduce golden set to 30 questions, skip embedding benchmark (default to `bge-small`), ship with RAGAS floor of 0.75 instead of 0.80. Costs credibility of the badges but gets published in ~2 weeks.

---

## 9. Final approval checklist

Sign off on each block before writing any BUILD code:

- [ ] **Product intent** (Section 1) — accurate description of what data-platform-rag is and isn't
- [ ] **Corpus scope** (Section 2) — two projects, no self-index, no code, no issues
- [ ] **Stack** (Section 3) — pgvector, bge-small (subject to benchmark), Claude Sonnet, Langfuse, pydantic
- [ ] **ADR set** (Section 4) — six Accepted, four Planned, no changes to identifiers
- [ ] **Accepted improvements A-I** (Section 5) — nine changes will happen as part of DEFINE
- [ ] **Deferred improvements J-S** (Section 5) — ten items go to v2 Roadmap with trigger conditions
- [ ] **Pre-BUILD diffs** (Section 6) — ten specific file changes before code
- [ ] **Non-negotiables** (Section 7) — eight gates before public publication
- [ ] **Timeline** (Section 8) — 3-4 weeks realistic, 2 weeks aggressive

If any block above is not approved, edit this file and re-review. If all approved, first BUILD action is `git init && git add -A && git commit -m "chore: initial scaffolding per PRE_BUILD_VALIDATION.md"`.

---

## Author's honest critique of this document

**Where this document is strong**: it makes rejection of low-ROI improvements explicit (Section 5, deferred/rejected). That prevents scope creep during BUILD — every future "shouldn't we add X?" gets a documented answer.

**Where this document is weak**: the timeline (Section 8) is optimistic. Every project of this shape overshoots. Realistic is probably 5-6 weeks part-time, not 3-4. If you are timeline-constrained, prefer to reduce scope (30-question golden set, skip embedding benchmark) rather than compress timeline.

**One risk not addressed here**: what happens if the target vacancy (Rimini Street AI Data Engineer III) is filled before you publish. Answer: the product remains valuable for equivalent postings — the category is expanding, not contracting — but the urgency framing weakens. If that vacancy closes, refocus on positioning as portfolio piece for the broader AI Data Engineer job market rather than as an application artifact for a specific role.

**A concrete improvement for future revisions**: after v1 ships, keep this document alive as `POST_V1_VALIDATION.md` documenting what actually happened vs what was planned here. That comparison is itself portfolio material.
