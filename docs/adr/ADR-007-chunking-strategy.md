# ADR-007 — Chunking strategy per source type

**Status**: Accepted
**Date**: 2026-09-14

## Context

Chunking is the highest-leverage decision in this pipeline. It is made once,
at index time, and everything downstream inherits it: the dense vector
represents whatever the chunk contains, the reranker scores that same unit,
and the UI cites it by name. A bad chunk boundary cannot be recovered by
better retrieval parameters — it can only be reindexed away.

The corpus is heterogeneous. `contracts.py::SourceType` enumerates five
kinds of source material, and they have genuinely different internal
structure: an ADR is one argument, a README is a sequence of independent
sections, a YAML contract is a record.

`indexer/chunker.py` currently raises `NotImplementedError` and carries a
docstring marked "per ADR-007, planned" that covers only four of the five
source types. This ADR is promoted from Planned to Accepted so that the
first BUILD feature creating chunks has a decided specification to build
against, per `docs/PRE_BUILD_VALIDATION.md` Section 5A.

## Note on revision

Section 5A of PRE_BUILD_VALIDATION.md stated "ADRs — one chunk per ADR file
(typical size <2000 tokens)". This ADR revises that rule: one chunk per ADR
file for ADRs under 480 tokens, split by `##` heading with ADR title
preserved as preamble for ADRs above that budget. The revision reflects a
technical constraint of the embedding model (bge-small/base/large all have a
512-token context window and truncate silently) that Section 5A did not
account for. The intent of Section 5A — preserving decision coherence as the
retrieval unit — is preserved for short ADRs and approximated for long ones.

## Decision

One strategy per source type:

| `source_type` | Strategy | Rationale |
|---------------|----------|-----------|
| `adr` | One chunk per ADR file | Context/Decision/Consequences is a single argumentative unit. Splitting it separates a decision from its justification — which is precisely the pairing users ask about. |
| `readme` | Hierarchical: one chunk per top-level `##` section | README sections are independently meaningful and rarely cross-reference each other. |
| `contract` | One chunk per YAML file | Small and self-contained; a data contract read in halves is not a data contract. |
| `macro` | One chunk per SQL file | A macro is one unit of behavior. |
| `schema` | One chunk per Schema Registry subject definition | The subject is the natural boundary; one file may define several. |

### Metadata mapping

| `source_type` | `chunk_index` | `source_anchor` |
|---------------|---------------|-----------------|
| `adr` | `0` (unless split — see below) | `null` (or the heading when split) |
| `readme` | Ordinal of the section in the file | The `##` heading text |
| `contract` | `0` | `null` |
| `macro` | `0` | `null` |
| `schema` | Ordinal of the subject in the file | The subject name |

`UNIQUE (source_path, chunk_index)` in `sql/01_schema.sql` is the dedup key,
so `chunk_index` must be deterministic for a given input file. Re-running
`make index-corpus` on unchanged sources must produce identical keys.

### The embedding window constraint (binding)

`bge-small-en-v1.5` — and every candidate in ADR-004 — accepts a maximum of
**512 tokens** per input. `sentence-transformers` truncates silently past
that: no warning, no error, just a vector representing the first 512 tokens.

This constrains the table above. A 2000-token ADR stored as one chunk would
be embedded from its first ~25% only. The `content` column, the citation,
and the text sent to Claude would all be complete — the dense vector alone
would be quietly wrong, and nothing in the pipeline would report it. The
sparse side (`to_tsvector`) has no such limit and would still match exact
terms in the truncated remainder, which makes the failure even harder to
notice: recall degrades rather than collapsing.

**Oversize rule.** Every chunk *body* targets **≤ 480 tokens**, leaving
headroom under the 512 window for the preamble below. The *assembled* chunk —
preamble plus body — is asserted against the hard 512 limit at index time, so
the guarantee does not depend on the preamble estimate being correct.

1. A source unit within budget is stored whole, per the strategy table.

2. An ADR over budget is split by heading, and **every resulting sub-chunk
   carries a preamble with the ADR's ID, title, status, and date**, so it
   stands alone when retrieved:

   ```
   # ADR-0019 — <title>
   **Status**: <status>
   **Date**: <date>

   ## <section heading>
   <section body>
   ```

   Status and date matter here as much as the title. The corpus contains
   superseded and reverted decisions, and a mid-document chunk retrieved
   without its status is exactly how a superseded decision gets cited as
   current.

3. **Split fallback hierarchy**, applied in order, descending only as far as
   needed:

   | Level | Boundary | Applied when |
   |-------|----------|--------------|
   | 1 | `##` top-level sections | Default for any over-budget ADR |
   | 2 | `###` sub-sections | A single `##` section is still over budget |
   | 3 | Paragraph (blank-line) boundaries | A single `###` section is still over budget |

   Never split mid-sentence, mid-code-block, or mid-table.

4. If an atomic block (a code block or table that cannot be split without
   corrupting it) exceeds the budget on its own, the indexing run **fails
   loudly**, naming the file and the block. It is never truncated silently
   and never split mid-block. Resolution is a human decision: reformat the
   source, or record an explicit exception in this ADR.

5. Sub-chunks inherit `adr_id`, `status`, `topic`, and `source_path` from the
   parent document. `chunk_index` is the sub-chunk ordinal; `source_anchor`
   is the deepest heading that produced it.

6. `token_count` in `ChunkMetadata` records the assembled chunk, preamble
   included.

The same rule applies to README sections and Schema Registry subjects.
`contract` and `macro` files are small enough that the rule is not expected
to fire; if it does, the file is split at top-level YAML keys or at statement
boundaries respectively.

## Consequences

**Positive**:
- Citations name a real, human-meaningful unit: "ADR-0019, Decision" rather
  than "chunk 7 of 12". The UI can link to a heading anchor.
- Chunk boundaries follow author intent, which is the strongest available
  signal of semantic cohesion in a documentation corpus.
- Every stored vector represents its entire chunk. No silent truncation.

**Negative / accepted trade-offs**:
- The 480-token budget means longer ADRs are split, so the "one chunk per
  ADR" ideal in Section 5A holds only for short ADRs. A question whose
  answer spans Context *and* Consequences of a long ADR now needs two chunks
  retrieved. With `rerank_top_k = 3` that is two of the three slots reaching
  the LLM, leaving one for everything else — noticeably tighter than the
  top-5 budget this ADR was drafted against (reduced the same day for the
  cost reason recorded in the Phase 0 dev log). The golden set must include
  such a question so the squeeze surfaces in Context Recall rather than in
  user complaints.
- The preamble costs roughly 25-30 tokens per sub-chunk, duplicated across
  every sub-chunk of the same ADR. Accepted: it is what makes a mid-document
  chunk interpretable standalone, both to the embedding model and to a
  reader in the UI.
- Splitting is deterministic but layout-sensitive. Reformatting a source ADR
  (adding a `##`) changes `chunk_index` and therefore the dedup key,
  producing orphan rows. `make reindex` is the remedy; incremental
  reindexing of edited files is not supported in v1.

## Alternatives considered

- **Fixed-size sliding window with overlap** (the RAG default, e.g. 512
  tokens / 50 overlap). Rejected: it ignores the structure the corpus
  already has. It would routinely cut between a decision and its rationale,
  and it makes citations meaningless, which breaks the product's core claim
  of grounded, attributable answers.
- **Per-paragraph chunking.** Rejected: too fine. Individual paragraphs in
  an ADR are frequently uninterpretable without their section.
- **Parent-document retrieval** — embed small child chunks, return the full
  parent ADR to the LLM. Genuinely attractive here, and it would dissolve
  the split/cohesion trade-off above. Deferred to v2: it needs a
  `parent_id` column, a second fetch in the retrieval path, and a rethink
  of how `RerankedChunk` feeds `generation/`. Revisit if RAGAS Context
  Recall on multi-section questions lags the rest of the golden set.
- **Semantic chunking** (embedding-based boundary detection). Rejected:
  unjustifiable complexity for a corpus of ~21 ADRs with explicit,
  author-provided structure.

## Verification

- `tests/unit/test_chunker.py` asserts, per source type: the expected chunk
  count for a fixture document, deterministic `chunk_index` across repeated
  runs, and correct `source_anchor` extraction.
- A fixture exercises each level of the split hierarchy: an ADR split at
  `##`, one requiring `###`, and one requiring paragraph boundaries.
- **No assembled chunk exceeds 512 tokens.** An index-time assertion fails
  the run otherwise, counted with the tokenizer of the model selected in
  ADR-004 — not with a whitespace approximation. This is the check that
  makes the truncation failure mode impossible rather than merely unlikely.
- After the first `make index-corpus`, record the `token_count` distribution
  (min / median / p95 / max, and how many ADRs required splitting, at which
  hierarchy level) in this ADR's Consequences section.
- `indexer/chunker.py` docstring updated to match this ADR, including the
  `schema` source type it currently omits.
