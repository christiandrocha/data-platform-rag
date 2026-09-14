# Phase 0 — findings deliberately not fixed

Recorded during the Phase 0 (Preparation) pass over `docs/PRE_BUILD_VALIDATION.md`
Section 6, applied 2026-09-14. Everything below was found while applying the ten
approved changes, falls outside Section 6's scope, and was left untouched on
purpose. Each entry names where it should be resolved.

---

## 1. `Chunk` dataclass diverges from `ChunkMetadata` — resolve in BUILD: corpus-indexing

**Owner**: feature `corpus-indexing`
**Raised by**: Change 4 (added `keywords` to `ChunkMetadata`)

`data_platform_rag/indexer/chunker.py::Chunk` is the dataclass that *produces*
chunk metadata, and it mirrors `contracts.py::ChunkMetadata` field by field —
by hand, with no enforced relationship. After Change 4 the two have diverged:
`ChunkMetadata` has `keywords: list[str] | None`, `Chunk` does not.

This is the second-order problem, and the more important one: a hand-mirrored
dataclass sitting next to the pydantic contract it duplicates will drift again
on the next field. ADR-010 says every inter-module boundary uses a model from
`contracts.py`; `Chunk` is exactly such a boundary (chunker -> writer).

Resolve during BUILD of `corpus-indexing`, choosing one:

- Delete `Chunk` and have the chunker emit `ChunkMetadata` + content directly.
- Keep `Chunk` as an internal working type and add a test asserting its field
  set is a superset of `ChunkMetadata`'s, so drift fails CI.

The first is more in the spirit of ADR-010. Either way, `keywords` gets added.

---

## 2. `loader.py` lists this repo as a corpus source — violates an AGENTS.md boundary

**Status**: RESOLVED 2026-09-14
**Resolution**: docstring corrected and an explicit "this repo is NOT a corpus
source" note added. `RawDocument.source_project` retyped from bare `str` to
`SourceProject` imported from `contracts.py`, so the two-project constraint is
now enforced by the type rather than described in prose. `contracts.py`
already held the correct two-value `Literal` and needed no change.

`data_platform_rag/indexer/loader.py:6` documents the corpus as:

```
- data-platform-rag (self) -> this project's docs/adr/
```

AGENTS.md states, as a hard boundary: "Never index the data-platform-rag repo
itself as a corpus source. [...] Self-indexing introduces recursion risk and was
explicitly rejected." `docs/PRE_BUILD_VALIDATION.md` Section 2 fixes the corpus
at two projects.

It is a docstring, not executable code — which is precisely why it is dangerous.
It is the specification someone implements `load_corpus` against.

---

## 3. `loader.py` annotates an undefined name

**Status**: RESOLVED 2026-09-14
**Resolution**: fixed as a side effect of #2 — `Collection`, `SourceProject`,
and `SourceType` are now imported from `contracts.py`, and the duplicated local
`SourceType` alias was deleted (ADR-010: `contracts.py` is the single source).
`Iterator` moved from `typing` to `collections.abc`. `ruff check` is now clean
across `data_platform_rag/` and `scripts/`.

`loader.py:29` declares `collection: Collection` on `RawDocument`, but
`Collection` is never imported — line 15 only carries a comment saying the alias
lives in `data_platform_rag.contracts`. `from __future__ import annotations`
defers evaluation, so the module imports fine and nothing fails today. It breaks
type checking, and it breaks at runtime for anything calling `get_type_hints()`.

---

## 4. `sql/01_schema.sql` header contradicts its own constraint

**Status**: RESOLVED 2026-09-14
**Resolution**: header corrected to "Two logical collections", aligning it with the
`CHECK` constraint, the table comment, and the title of ADR-002. The header was
the only place in the repo claiming three.

Line 2 says "Three logical collections, one physical table". The `CHECK`
constraint on line 15 allows two (`decisions`, `architecture`), ADR-002 is
titled "Two logical collections in one physical table", and the table comment on
line 49 says two. The header is the only place claiming three.

Left as found: Change 5's scope was the `keywords` column and the `pg_trgm`
comment, and silently rewriting an unrelated header comment in the same pass
would have buried it.

---

## 5. `sql/01_schema.sql` repeats the self-indexing violation

**Status**: RESOLVED 2026-09-14
**Resolution**: the `source_project` column comment now lists the two corpus
projects and states that this repo is not one of them.

The inline comment on the `source_project` column lists three values, including
`data-platform-rag`. Same boundary violation as #2, in a second file. Fixing one
without the other leaves the contradiction intact.

---

## 6. README cost claim is arithmetically wrong

**Status**: DECIDED 2026-09-14 — one cascade still open (see below)
**Decision**: top-k reduced pre-emptively to meet the Section 7 cost
non-negotiable — revisit during BUILD iteration with real RAGAS data. If the
reduction proves load-bearing for quality rather than just cost, it earns
ADR-011 rather than remaining a config default.

`config.py::rerank_top_k` 5 -> 3, mirrored in `.env.example`. Recomputed cost
is **$0.0083/query**, not the $0.0076 estimated when the decision was taken:
scaling the old total linearly by token count assumes input and output cost the
same, and they do not (output is 5x). The decision holds either way — both
figures clear the < $0.01 gate — but the KB carries the per-direction
arithmetic so the next reader can check it.

**Still open**: `README.md:64` continues to claim "cost per query <$0.005",
which no longer matches any computed figure.

`README.md:64` claims "cost per query <$0.005", and
`.claude/kb/langfuse/cost-tracking.md:29` claims the same. At the token shape
that file itself documents (500 system + 2000 context + 50 query in, 200 out)
and Claude Sonnet 4.6 pricing ($3/$15 per MTok), a query costs ~$0.0107 — which
also trips the ">$0.01/query, investigate" alarm in the same KB file, on every
normal query.

`docs/PRE_BUILD_VALIDATION.md` Section 7 makes "cost < $0.01 per non-fallback
query" a publication non-negotiable, so this is not cosmetic: the current model
choice fails that gate on paper before a single query runs.

Three ways out, all requiring a decision: correct the target, switch the model
(`claude-sonnet-5` is $2/$10 -> ~$0.0071, still above $0.005), or shrink the
context budget. AGENTS.md forbids publishing invented numbers, so the claim
cannot simply stand.

---

## 7. Langfuse KB and client are written against SDK v2; the pin resolves to v4

**Status**: RESOLVED 2026-09-14 (contained, not eliminated)
**Decision**: API divergence Langfuse v2 vs v4 to be resolved during Phase 4
BUILD of `langfuse-integration` — verify the current SDK API before implementing
decorators.

`pyproject.toml` now pins `langfuse>=2.50,<3.0`, so an install resolves to the
API the KB and `langfuse_client.py` actually describe. This stops the bleeding;
it does not modernise anything. The v4 line is two majors ahead.

`pyproject.toml` pins `langfuse>=2.50` with no upper bound; the current release
is 4.15.2. `.claude/kb/langfuse/python-sdk.md` documents
`from langfuse.decorators import observe`, and both that KB file and
`observability/langfuse_client.py` assume the v2 `trace()` / `span()` /
`generation()` surface, replaced in v3.

The failure mode is the bad one: `NoopLangfuse` implements the v2 shape and
keeps working, so with the default `LANGFUSE_ENABLED=false` nothing surfaces
until observability is switched on.

Decide whether to cap the pin at 2.x or rewrite for 4.x, then make the KB match.
