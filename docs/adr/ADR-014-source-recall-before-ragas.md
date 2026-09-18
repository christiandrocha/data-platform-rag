# ADR-014 — Source recall at k as the retrieval metric, before RAGAS exists

**Status**: Accepted
**Date**: 2026-09-18

## Context

Two ADRs are Planned and both are blocked on the same missing thing.

**ADR-004** must choose an embedding model and tune HNSW parameters "against the
golden set". **ADR-005** must show that a cross-encoder reranker improves
results. Neither can proceed, because the project has no way to say whether one
retrieval configuration is better than another. There is no number.

The obvious answer is RAGAS, and it is not available. RAGAS scores *generated
answers* against *retrieved contexts*, so it needs generation, which does not
exist; and it needs a representative golden set, which stands at 5 of 50. Waiting
for RAGAS means ADR-004 and ADR-005 wait too, and it means the retrieval work
lands with no evidence at all about whether it retrieves the right things.

There is already evidence that it will not always. A dense-only smoke check
during `corpus-indexing-writer` returned `001_databricks_vs_snowflake.md` above
`007_pipeline_unification.md` for golden-set question q002, whose declared anchor
is the latter. That observation was recorded and then had nowhere to go, because
no metric existed to hold it.

**The golden set already carries what is needed.** Every question declares
`expected_source_paths` — a list of `{project, path}` pairs naming the documents
that should ground the answer. Four of the five current questions are in scope
and declare six paths between them. That is a labelled retrieval set, and nothing
reads it.

## Decision

**Source recall at k becomes the project's retrieval metric until RAGAS is
available**, and it is defined precisely enough to be comparable across runs.

1. **Definition.** For one question, retrieval returns a ranked list of chunks.
   A declared `expected_source_paths` entry counts as **retrieved at k** if any
   chunk in the top k carries that exact `(source_project, source_path)` pair.
   Source recall at k is retrieved entries divided by declared entries, summed
   across questions rather than averaged per question — so a question declaring
   two paths contributes twice as much as one declaring a single path, which is
   correct: it has twice as much to find.

2. **k is reported at 3, 10 and 20**, not one value. Three numbers say something
   one cannot: k=20 is what hybrid retrieval returns, k=3 is what
   `settings.rerank_top_k` will pass to generation, and k=10 sits between them.
   A configuration that wins at 20 and loses at 3 is exactly the case reranking
   exists to fix, and a single k would hide it.

3. **Out-of-scope questions are excluded from the denominator**, because they
   declare no paths and correctly retrieving nothing is not a recall event.
   Their **top fused score is recorded alongside** the in-scope ones. That
   comparison is the raw material for ADR-006's threshold, which is currently an
   unjustified `0.35` in config.

4. **It is measured by a script and recorded as an artifact**, not asserted by a
   test. It needs a populated database and an embedding model, and a CI job that
   downloads a model to assert a number nobody has justified yet would be a
   threshold invented to make a gate green.

5. **It is not a RAGAS score and never appears as one.** It does not go in the
   README badges, which stay `pending` until `make eval-ci` has run. It measures
   whether the right documents come back, and says nothing about whether the
   answer built from them is faithful.

## Consequences

**Positive**

- ADR-004 and ADR-005 become possible. Both can now be argued with a
  before-and-after on the same six declared paths.
- The q002 observation has somewhere to live. It stops being an anecdote in a
  build report and becomes a tracked number.
- The curator gains a check on their own work: a question whose declared anchor
  is not retrieved at any k is either a badly anchored question or a retrieval
  failure, and either way it is worth knowing before 45 more are written.
- ADR-006's `fallback_threshold` gets evidence. Today `0.35` is a literal nobody
  has defended.

**Negative**

- **The denominator is tiny.** Six paths across four questions. A single path
  moving changes the number by 17 percentage points, so early readings are
  directional at best. This is an argument for growing the golden set, not
  against having the metric — but a reading must never be quoted without its
  denominator.
- Recall ignores rank within k. A path retrieved at position 1 and at position
  20 score identically at k=20. MRR would capture that and is deliberately not
  adopted; see Alternatives.
- The metric can be gamed by returning more chunks. It is only meaningful
  reported at fixed k values, which is why k is part of the name and never
  dropped.
- A manual script is a step someone must remember to run. The alternative was a
  CI gate on an unjustified threshold, which is worse.

**Neutral**

- The metric is retrieval-only by construction. When RAGAS arrives it does not
  replace this: context precision and recall answer a different question, and a
  regression in source recall will still be the fastest way to localise a
  retrieval-side cause.

## Alternatives Considered

**Mean reciprocal rank, or nDCG.** Both capture rank position, which recall
discards, and both are standard. Rejected for now on the grounds that they are
harder to read and the denominator is six. MRR over six labelled paths produces a
number with more precision than the sample can support, and the false confidence
is worse than the lost information. Revisit when the golden set reaches 50 —
nothing in this ADR prevents computing MRR from the same recorded rankings later,
because the script records the full ranking, not just the hit.

**Wait for RAGAS.** Rejected: it blocks ADR-004 and ADR-005 indefinitely, and it
means shipping retrieval with no evidence it retrieves correctly. RAGAS also does
not subsume this — a faithfulness score falling tells you the answer was wrong,
not that the right document never came back.

**Judge retrieval by reading the results.** This is what the `make ask` command
in the same feature is for, and it is genuinely useful — but it is not
comparable across runs and cannot show a regression. The two are complements: one
is for understanding a single question, the other for comparing configurations.

**Assert a pass threshold in CI now.** Rejected, and this is the AGENTS.md
boundary against invented numbers applied to a metric rather than to a badge.
No baseline exists, so any threshold would be chosen to pass, and a gate tuned to
whatever the code currently does measures nothing.
