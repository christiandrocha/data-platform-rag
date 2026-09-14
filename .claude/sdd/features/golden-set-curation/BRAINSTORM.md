# BRAINSTORM: golden-set-curation

> Free exploration. No commitments. No commits from this file alone.

## Date
2026-09-14

## Prompt

First BUILD-phase feature, per `docs/PRE_BUILD_VALIDATION.md` Section 5E.

Produce 50 questions in `docs/golden-set/evaluation_questions.yml` at the
distribution 22 decision / 18 architecture / 5 comparison / 5 out-of-scope, each
with an `expected_answer` and `expected_source_paths`. Five exist as a starter;
45 remain.

This feature is load-bearing in a way the question count understates. The golden
set is the measuring instrument for everything downstream: ADR-004's embedding
decision rule, ADR-005's reranker A/B, ADR-008's CI regression threshold, and all
four RAGAS metrics in the Section 7 publication gate. **A biased golden set does
not produce a wrong number — it produces a confident wrong number**, and nothing
downstream can detect it. That risk shapes every option below.

This brainstorm covers four decisions rather than one, so the template's single
"Options considered" section is split accordingly.

---

## Decision A — Who authors the 45 questions?

### A1: Solo manual — Christian writes all 45

- **Pros**: highest fidelity to what a real reader asks. The author knows which
  decisions were genuinely contested and which are boilerplate, and that judgment
  is not recoverable from the text. Ground-truth answers are authoritative by
  construction.
- **Cons**: 45 × (question + answer + source paths) is many hours of concentrated
  work. Fatigue homogenises the back half of the set. There is also a subtle
  self-serving bias: an author writing questions for their own system tends to
  write questions it can already answer.

### A2: LLM proposes candidates from the corpus; human validates

- **Pros**: fast, systematic sweep across all 21 ADRs; coverage gaps become
  visible immediately; human keeps accept/edit/reject authority.
- **Cons**: **this is the methodological trap, and it is severe.** An LLM reading
  the corpus and generating questions produces questions whose vocabulary mirrors
  the source text. The golden set then measures "can retrieval find text similar
  to text generated from that text" rather than "can it answer what a human would
  ask." Dense retrieval scores inflate, and the inflation is invisible — every
  metric looks healthy. Worse, if the generating model shares a family with the
  answering model, their blind spots correlate.

### A3: Hybrid by band — human writes the judgment-heavy categories, LLM assists on factual ones

Christian writes all 5 comparison + all 5 adversarial + a seed of decision
questions; LLM proposes architecture questions from READMEs and contracts, which
are more factual and less interpretive.

- **Pros**: spends scarce human attention where judgment actually matters. The
  adversarial set in particular cannot be safely LLM-generated (see Decision C).
- **Cons**: two provenance classes in one instrument, with different bias
  profiles, and no field in the schema records which is which. Any later analysis
  that slices by intent unknowingly slices by provenance too.

### A4: Human-first; LLM as auditor and gap-finder, never as author

Christian writes every question. The LLM's role is inverted: audit coverage
(which ADRs have no question, which intents are thin, which source files are
never cited) and red-team each question (does this phrasing accidentally quote
the source? would this question plausibly be asked by someone who had not read
the ADR?).

- **Pros**: captures A2's systematic-coverage benefit while structurally
  excluding the contamination in A2. The LLM never sees a blank page, so it never
  writes source-mirroring text. Auditing is also the task LLMs are reliably good
  at here, versus authoring, where the failure is silent.
- **Cons**: still 45 human-written questions. Slower than A2 by a wide margin.

---

## Decision B — Where do the questions come from?

### B1: Extracted from ADR content, one per decision

- **Pros**: guaranteed coverage and trivially traceable `expected_source_paths`.
- **Cons**: produces "quiz the document" phrasing, which the existing curation
  rule already forbids ("Questions must sound natural — no 'According to
  ADR-007...'"). Also the purest form of the A2 contamination, arrived at by a
  different route.

### B2: Contextual invention — what would a reader actually ask?

- **Pros**: natural phrasing; tests paraphrase robustness, which is the entire
  justification for dense retrieval over plain keyword search.
- **Cons**: coverage is accidental. Inventing 50 natural questions freehand
  reliably over-samples the interesting decisions and leaves whole ADRs
  unreferenced.

### B3: Real provenance — questions Christian was actually asked

From interviews, LinkedIn threads, code review on the two source projects.

- **Pros**: maximum realism. The product exists to answer exactly these, and a
  question with real provenance is evidence, not a guess about user behaviour.
- **Cons**: supply-limited. Unlikely to reach 50, and certainly not at the
  required intent distribution.

### B4: Natural invention against an explicit coverage matrix

Write naturally (B2), then check each question against an ADR × intent matrix and
deliberately fill the holes. Real questions (B3) seed the set where they exist.

- **Pros**: natural phrasing *and* deliberate coverage, with the gaps made
  visible rather than discovered later as a RAGAS anomaly. The matrix is also a
  reusable artefact — it tells ADR-004's benchmark which questions exercise which
  corpus regions.
- **Cons**: requires building and maintaining the matrix. Filling holes
  deliberately reintroduces some B1 artificiality at the margins.

---

## Decision C — The 5 adversarial questions

The hardest five to get right, and the ones most likely to be written carelessly
because they look trivial.

The constraint is not "must be out of scope" but **"must fire the fallback
unambiguously"** — which makes these five a test of `fallback_threshold = 0.35`
as much as of the corpus boundary. A question that is out of scope but scores
0.36 makes the threshold untunable: you cannot tell whether a failure means a bad
threshold or a bad question.

### C1: All trivially out-of-domain

"What is the weather in Lisbon?" — guaranteed to fall below threshold.

- **Pros**: zero ambiguity; the fallback will fire.
- **Cons**: tests nothing. No real user asks this, and it leaves the actual
  failure mode — plausible adjacent questions — completely unmeasured.

### C2: All adjacent-but-absent

"What did Christian decide about Delta Live Tables?" — plausible, in-domain
vocabulary, genuinely not in the corpus. The existing curation rule suggests this.

- **Pros**: tests the boundary where the system will actually fail in production.
- **Cons**: high variance. Adjacent questions can score just above threshold, and
  five of them concentrated at the boundary makes `fallback_accuracy` noisy —
  exactly the metric that must be 100% per Section 7.

### C3: A deliberate difficulty gradient

Spread the five across the range: one trivially out-of-domain, two
adjacent-but-absent, one subjective/opinion (the existing q005 shape), one
prompt-extraction attempt.

- **Pros**: `fallback_accuracy` becomes diagnostic instead of binary — a failure
  tells you *where* on the gradient the threshold sits. Covers the Section 7
  non-negotiable requiring an adversarial security test (someone attempting to
  exfiltrate the system prompt gets the fallback, not the prompt), which
  currently has no home anywhere in the repo.
- **Cons**: five questions is a thin gradient; each point is a sample of one.

### C4: Expand the adversarial set beyond five

Keep 5 in the scored distribution, add a separate unscored adversarial suite for
the security cases.

- **Pros**: security testing stops competing for slots with corpus-boundary
  testing. The two measure different things and arguably should not share a
  metric.
- **Cons**: changes the 22/18/5/5 distribution that Section 5E fixed and the
  golden-set README documents. Needs an explicit decision, not a drift.

---

## Decision D — Validating `expected_answer` quality

Under-discussed and consequential: `expected_answer` is RAGAS's ground truth. If
it contains a claim not supported by the corpus, Context Recall for that question
becomes unachievable — a permanently red metric caused by a bad golden set, not a
bad system, and indistinguishable from the outside.

### D1: Author's assertion

Write it, trust it.

- **Pros**: free.
- **Cons**: the failure mode above goes undetected until someone spends a day
  debugging retrieval for a question whose expected answer was always wrong.

### D2: Sentence-level source grounding

Every clause in `expected_answer` must be traceable to a specific passage in a
file listed in `expected_source_paths`. A second pass verifies before the
question enters the set.

- **Pros**: catches the failure at authoring time, when it is cheap. Also
  improves `expected_source_paths` accuracy as a side effect, since ungroundable
  clauses reveal missing sources.
- **Cons**: roughly doubles authoring time per question.

### D3: RAGAS as its own validator

Run the set; treat anomalously low faithfulness on an individual question as a
signal that the *expected answer* may be wrong, not only the system.

- **Pros**: free once the pipeline exists; catches what human review misses.
- **Cons**: circular — it needs the pipeline that the golden set is meant to
  validate, and it cannot distinguish a bad expected answer from a genuine
  retrieval failure without human adjudication anyway.

### D4: LLM as grounding auditor

LLM reads `expected_answer` alongside the cited sources and flags unsupported
clauses. Authoring stays human; checking is delegated.

- **Pros**: mechanises D2's expensive part while keeping the LLM out of the
  authoring path, consistent with A4. This is verification, where an LLM's
  failure is visible, not generation, where it is silent.
- **Cons**: needs the corpus files available locally at curation time, which
  conflicts with the AGENTS.md rule that clones are transient. Needs a deliberate
  workflow.

---

## Discarded early

- **Fewer than 50 questions to save time** — Section 5E fixes the count, and
  ADR-008's regression threshold needs enough questions for a 0.05 metric drop to
  be signal rather than noise.
- **Synthetic question generation at scale (hundreds)** — volume does not fix
  contamination; it industrialises it.
- **Reusing a public RAG benchmark set** — the corpus is two private-ish
  portfolio repos. No public set touches this material.
- **Crowdsourcing the questions** — no plausible crowd for a corpus this specific.
- **Deferring `expected_answer` and scoring on retrieval only** — RAGAS
  Faithfulness and Answer Relevance both need it. Halves the instrument.

---

## Emerging preference

**A4 + B4 + C3 + (D2 for the first pass, D4 to mechanise later)**.

The through-line: **the LLM verifies, the human authors.** Every option where an
LLM writes questions fails in the same silent way — it produces an instrument
biased toward the system being measured, and no downstream metric can reveal it.
Every option where an LLM checks human work fails visibly and recoverably.

A4 (human-first, LLM audits coverage and red-teams phrasing) and B4 (natural
invention against an explicit ADR × intent matrix) compose into one workflow: the
matrix is what the auditor checks against. C3's difficulty gradient turns
`fallback_accuracy` from pass/fail into a diagnostic and gives the Section 7
security test a home. D2 is the honest first pass; D4 is the optimisation once
the corpus-local workflow exists.

**Documented fallback — acceptable pragmatic retreat if D2 proves too slow.**
If, during DEFINE or early BUILD, authoring 45 questions at D2 rigour proves
unworkable in reasonable time, migrating to A3 is pre-approved and requires no
new brainstorm. The condition: add a `provenance` field to the question schema
first, so human-authored and LLM-proposed questions stay separable in any later
analysis. Approved 2026-09-14.

**What would change our mind:** if authoring 45 questions at D2 rigour proves to
take more than roughly two focused sessions, the pragmatic fallback is A3 —
human-authored comparison and adversarial questions, LLM-proposed architecture
questions from the more factual README and contract material, with a `provenance`
field added to the schema so the two classes stay separable in later analysis.

---

## Open questions for DEFINE

1. ~~**`expected_source_paths` cannot name a project, and the schema has a
   collision bug.**~~ **RESOLVED 2026-09-14, before DEFINE.** The unique key is
   now `(source_project, source_path, chunk_index)` and `expected_source_paths`
   entries are `{project, path}` objects. See dev log finding #8.
2. **The validator does not enforce the distribution.**
   `scripts/validate_golden_set.py` checks fields, intent membership, and
   duplicate ids, but not the 22/18/5/5 counts or the total of 50. Cheap to add
   and would make the target self-enforcing.
3. **`expected_source_paths` are never verified to exist.** Validation would
   require the corpus cloned, which the AGENTS.md transient-clone rule
   complicates. Possibly a separate `make` target that runs only when a clone is
   present.
4. **Does `should_fallback: true` imply `intent: out-of-scope`?** They are
   currently independent fields that must agree by convention. The validator does
   not check the pairing.
5. **Should the schema record question provenance?** Needed if A3 is ever adopted;
   harmless and cheap if A4 holds.
6. **Where does the Section 7 security test live** if C4 is chosen over C3 —
   inside the scored 5, or in a separate suite with its own pass criterion?

## Next step
- [x] Write DEFINE if a clear direction emerged
- [ ] Or park with `status: Parked` and revisit

Direction: A4 + B4 + C3 + D2→D4. DEFINE pending user confirmation.
