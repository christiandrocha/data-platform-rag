# data-platform-rag — Architecture

## Layered view

```
┌──────────────────────────────────────────┐
│         Streamlit UI (data_platform_rag/ui/)     │
└─────────────────┬────────────────────────┘
                  │
┌─────────────────▼────────────────────────┐
│  Generation (data_platform_rag/generation/)      │
│  - system prompt (versioned)             │
│  - fallback logic                        │
│  - Anthropic client                      │
└─────────────────┬────────────────────────┘
                  │
┌─────────────────▼────────────────────────┐
│  Retrieval (data_platform_rag/retrieval/)        │
│  - intent classifier                     │
│  - hybrid_search (dense + sparse + RRF)  │
│  - reranker (bge-reranker cross-encoder) │
│  - pipeline (orchestration)              │
└─────────────────┬────────────────────────┘
                  │
┌─────────────────▼────────────────────────┐
│  Postgres 16 + pgvector 0.7+             │
│  - chunks table (HNSW + GIN indexes)     │
│  - query_log table                       │
└──────────────────────────────────────────┘
                  ▲
┌─────────────────┴────────────────────────┐
│  Indexer (data_platform_rag/indexer/)            │
│  - loader (fetches source repos)         │
│  - chunker (per source_type strategy)    │
│  - embedder (bge-small)                  │
│  - writer (upsert into pgvector)         │
└──────────────────────────────────────────┘
```

## Data flow — offline indexing

1. `make index-corpus` triggers `scripts/index_corpus.py`
2. Clones target repos to `/tmp/dpr-corpus-{timestamp}/`
3. `loader.py` walks the clone, yields `(source_type, source_path, raw_text, metadata)` tuples
4. `chunker.py` splits per strategy (ADR: full document as chunk; README: by heading; contract: whole YAML)
5. `embedder.py` batches through `bge-small-en-v1.5`, returns 384-dim vectors
6. `writer.py` upserts into `chunks` table with idempotent `(source_project, source_path, chunk_index)` key
7. Clone deleted, embeddings persist in Postgres

## Data flow — online query

1. User submits query in Streamlit
2. `pipeline.py` orchestrates:
   - `intent_classifier.py` — LLM-lite call, returns collection(s) to search
   - `hybrid_search.py` — one SQL query with dense + sparse + RRF, top-20 candidates
   - `reranker.py` — cross-encoder scores each candidate against query, top-5 kept
3. Top-1 reranker score compared to threshold
   - Below → `generation/fallback.py` returns fixed message, logged with `fallback_fired=TRUE`
   - Above → `generation/client.py` calls Anthropic with system prompt + top-5 chunks
4. Answer + cited chunks rendered in UI
5. Full query logged in `query_log` table

## Failure modes and mitigations

| Failure | Detection | Mitigation |
|---------|-----------|-----------|
| Postgres down | Health check on startup | Streamlit shows error page, does not retry LLM |
| Anthropic API down | Client timeout at 30s | Return partial answer with retrieved chunks + error notice |
| Embedding model download fails | Cold start check | Fail loud, do not attempt query |
| Reranker OOM | Streamlit Cloud memory limit | Fallback to dense-only retrieval, log warning |
| HNSW index corruption | verify.sql regression | Re-run `sql/02_indexes.sql` (idempotent DROP + CREATE) |

## Reindexing policy

- Idempotent: `(source_project, source_path, chunk_index)` unique constraint means re-running `make index-corpus` upserts, does not duplicate. The project column is load-bearing — both corpus repos have a `README.md`.
- Full reindex needed only if: embedding model changes, chunking strategy changes, or a source repo has been substantially rewritten.
- No streaming updates. This is a periodic-refresh system.
