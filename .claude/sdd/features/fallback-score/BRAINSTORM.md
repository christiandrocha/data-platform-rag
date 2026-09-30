# BRAINSTORM: What decides "out of scope", and on what number

> Free exploration. No commitments. No commits from this file alone.

## Date
2026-09-30

## Prompt

ADR-018 made retrieval dense-only and left one gap open on purpose. Every result
carries `rrf_score = 1/(60 + dense_rank)`, so the top score is `1/61` for every
question, in scope or not (ADR-018 P2, measured). ADR-006's fallback gate
("below 0.35 cosine, do not call the LLM") has nothing to act on.

What is true today, without measuring anything new:

- **Nothing reads `settings.fallback_threshold`.** Generation does not exist.
  0.35 is a literal in `config.py`, and ADR-006 calls it "a magic number".
- **Two out-of-scope gates are designed, and neither is built.** ADR-006 puts a
  score gate *before* the LLM (no tokens spent, fixed LinkedIn message). The
  system prompt's rule 3 makes the *LLM* return the same message when "the
  retrieved context does not directly answer the question". ADR-006 considered
  and rejected relying on the LLM alone ("LLMs still fabricate under 'context is
  weak' prompting").
- **The number a score gate would read already exists.** `RetrievedChunk.dense_distance`
  is the cosine distance, so the similarity is `1 − dense_distance`. No contract
  change is needed to have it, only to name it.
- **The labelled evidence is thin on the negative side.** The golden set has 5
  out-of-scope questions (q005, q047–q050) against 45 in scope. q047–q050 were
  written to sit close to the corpus on purpose (ADR-016): React frontend
  experience, prompt extraction, and so on. A threshold fitted on these 5 is
  fitted on the test.
- **Nobody has looked at the top similarity per question, and no artifact holds
  it.** The recall artifacts record rank, path, anchor and `rrf_score` per chunk,
  not `dense_distance` (checked 2026-09-30). The number does not exist yet, so it
  cannot be read early. It gets measured once DEFINE fixes what it will mean (the
  same discipline as ADR-017 and ADR-018).

## Options considered

### Option 1: Measure separability first, with a pre-registered fork

Report the top-1 similarity (`1 − dense_distance`) per question, in scope and
out of scope, in the recall artifact. Fix in DEFINE, before reading it, what each
outcome means:

- **The in-scope and out-of-scope top similarities separate** (every in-scope
  question's top similarity is above every out-of-scope one's) → the score gate is
  viable, and the next ADR calibrates its threshold on a **separate calibration
  set** of out-of-scope questions written for the purpose, disjoint from the
  golden set. The golden set only verifies.
- **They overlap** → a similarity threshold cannot tell even the curated set
  apart. ADR-006's score gate is superseded, and out-of-scope becomes rule 3's job
  (the LLM decides), measured by `make eval` once it exists.

- **Pros**
  - Measures before deciding. Whether cosine similarity can separate at all is
    unknown, and every other option assumes an answer.
  - Small. One summary per question in the recall report, and no gate code.
  - The fork is written before the numbers exist, so the numbers cannot pick
    their own conclusion.
- **Cons**
  - It does not ship a working fallback. It decides which fallback to build.
  - "Separate on 50 questions" is a necessary condition, not a sufficient one. A
    clean split can still be luck with 5 negatives. That is why the threshold
    value comes from a separate set.

### Option 2: Calibrate the threshold now, on the golden set

Pick the value that splits the 45 from the 5, write it into `fallback_threshold`,
and wire the gate.

- **Pros**
  - Finishes ADR-006 in one step.
- **Cons**
  - Fits a value on the same 50 questions that will later grade the system, with
    only 5 negatives. That is the overfitting ADR-017's "no swept cutoff" rule
    exists to prevent.
  - It assumes separability before knowing it.
  - The gate has no caller until generation exists.

### Option 3: Supersede the score gate now, and let the LLM decide

Amend ADR-006: no retrieval-score gate, and rule 3 alone sends the fallback.

- **Pros**
  - The LLM reads content rather than a distance, which is what the near-corpus
    out-of-scope questions (q047–q050) need.
  - One gate, not two.
- **Cons**
  - It reverses ADR-006 without a measurement. ADR-006 rejected exactly this,
    citing fabrication under weak context.
  - It cannot be measured today. `make eval` is a stub and there is no API key.
  - Every out-of-scope query spends tokens.

### Option 4: Two gates, a conservative score gate plus rule 3

A low threshold catches only the plainly unrelated ("what did you study in
college?"). Rule 3 catches the near-corpus ones.

- **Pros**
  - It is probably the right end state: cheap rejection of the obvious, and
    judgement for the subtle.
- **Cons**
  - It still needs a threshold value, so it inherits Option 2's calibration
    problem and Option 3's measurement problem.
  - Nothing tells us yet whether the "plainly unrelated" band exists in cosine
    space for this model.

## Discarded early

- **Wire 0.35 as it is.** Never measured, and ADR-006 calls it a magic number.
  Whether bge-small's similarities even fall near 0.35 is unknown. It could fire
  on everything or on nothing.
- **A relative score** (top-1 minus top-k gap, z-score over the list). It is
  another number to calibrate, with less intuition than a similarity, and nothing
  shows the absolute one has failed yet.
- **Keep `rrf_score` as the gate's input.** It is `1/61` for every question.

## Emerging preference

**Option 1.** Every other option assumes an answer to "does cosine similarity
separate in-scope from out-of-scope for this model and corpus?", and that answer
is one measurement away. Option 4 is the likely destination if the answer is yes,
and Option 3 if it is no.

**The rule for DEFINE to fix** (a sketch, to be settled with the author):

- **Separable:** min(in-scope top similarity) > max(out-of-scope top similarity),
  over the 45 + 5. → next ADR: a score gate calibrated on a disjoint calibration
  set (Option 2's gate done right, or Option 4).
- **Not separable:** any overlap. → ADR-006's score gate is superseded, and rule 3
  decides (Option 3), pending `make eval`.
- **Pre-registered prediction, not gating:** not separable, because q047–q050
  were written to sit near the corpus.

**Scope of the code:** the recall report gains `top_similarity` per question and
a separability summary. `rrf_score`'s future (remove it, or leave it as a
compatibility field) is a DEFINE question. No gate is built in this feature.

**What would change my mind:** if the author wants a working fallback before
generation exists, Option 4 with an explicit "provisional" value would be the
honest shortcut. But the gate has no caller yet, so there is no cost to waiting.

## Next step

- [x] Author confirms Option 1 (2026-09-30)
- [ ] Write DEFINE: the separability rule, both branches, and `rrf_score`'s fate
