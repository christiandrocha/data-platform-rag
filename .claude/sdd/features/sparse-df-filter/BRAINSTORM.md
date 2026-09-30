# BRAINSTORM: A sparse side that votes only on distinctive terms

> Free exploration. No commitments. No commits from this file alone.

## Date

2026-09-29

## Prompt

The golden set reached 50 questions today (PRs #21 and #22, not yet merged). The
first `make retrieval-recall` over the full set
(`.claude/dev/reports/retrieval-recall-20260929-190639.json`, snapshot
`sdd-kafka-databricks@f1295df9`, `sdd-kafka-snowflake-2@82a2e269`, bge-small)
reads:

| | k=3 | k=10 | k=20 |
|---|---|---|---|
| all (45 in-scope, 57 declared paths) | 38 (67%) | 44 (77%) | 46 (81%) |
| decision (22 paths) | 20 | 22 | 22 |
| architecture (24 paths) | 15 | 18 | 20 |
| comparison (11 paths) | 3 | 4 | 4 |

Two observations from the same run:

- **The sparse side returned rows for 7 of 50 questions.** Hybrid retrieval is
  still dense-only for question-shaped input, the defect recorded in ADR-003
  Amendment 1 §B.
- **The top fused score cannot separate in-scope from out-of-scope.** All five
  out-of-scope questions score 0.01639, the same as 38 of the 45 in-scope ones
  (a rank-1 dense hit and nothing else). That is not new (ADR-015 said ADR-006's
  threshold was already meaningless against RRF), but it now holds on 50
  questions.

ADR-015 OR-joined the lexemes and was rejected by its own pre-registered rule
(2026-09-21). With an equal ballot and no weight, generic terms voted as loudly as
specific ones, q001's correct ADR tied exactly with a wrong one and lost rank 1,
and no recall bucket moved. Its Outcome names two ways forward: **drop generic
terms by document frequency, then OR** (its Alternative 2) or **honest
dense-only** (its Alternative 4). Alternative 2 was deferred because a
document-frequency cutoff needs a justification, and 6 declared paths could not
supply one. There are now 57.

What carries over from `sparse-query-strategy`:

1. **Populated is not useful.** The measure is recall and named-case ranks, not
   match counts.
2. **Write the decision rule before measuring, covering every reading,**
   including "nothing moved", the gap ADR-015 recorded in its own rule.
3. **A criterion on a named case caught what an aggregate did not** (q001 stays
   at rank 1).
4. **Pessimistic predictions held up better than the optimistic one.**

## A constraint on this brainstorm itself

**No candidate is simulated here.** The database is running and a DF-filtered
query could be tried in minutes. Doing that before DEFINE fixes the rule would
let the result choose the rule, and the rule exists to prevent exactly that. The
only measurement this file quotes is today's before-reading. Everything about how
a candidate would perform is marked unmeasured.

## Options considered

### Option 1: DF-filtered OR, with one cutoff fixed in advance (ADR-015 Alternative 2)

Build the disjunction from the lexemes `plainto_tsquery` produces, as ADR-015 did,
but first drop every lexeme whose document frequency in `chunks` is above a
cutoff. Postgres supplies the frequencies itself (`ts_stat` over `content_tsv`),
so the corpus stays the only source of truth about what is generic in it. If every
lexeme is dropped, the sparse side returns no rows, which is today's behaviour,
not an error.

**The cutoff is a single number chosen before measuring, on a stated a-priori
basis, and never swept.** The reason is what the golden set is for: the same 50
questions will later report RAGAS. A cutoff picked because it scored best on them
would inflate every number measured on them afterwards. One pre-registered value
removes the search, so there is nothing to overfit. ADR-015's `ts_stat` reading
gives the scale, from q001 alone: `snowflak` in 31% of chunks, `stream` 24%,
`project` 16%, against `snowpip` 6% and `classic` 3%. "Around a fifth of the
corpus", ADR-015's own phrase, is where a cutoff would sit. The exact value and its
justification are DEFINE's job.

- **Pros**
  - Attacks the failure ADR-015 measured: the q001 tie was built from votes on
    broad lexemes.
  - No schema change and no new dependency. The GIN index and `content_tsv` stay
    as they are.
  - A revert is one expression, as it was for ADR-015.
  - Keeps the reason for having a sparse side: identifiers (`Snowpipe`,
    `ADR-0029`, `Lakeflow`, `cluster_by`) are where a 384-dim embedding is
    weakest and a lexeme match is strongest.
- **Cons**
  - **Where the frequencies live** is a real design question. Options: compute
    per query with `ts_stat` (a scan of about 300 rows, negligible today and
    load-bearing at scale), or cache per `corpus_snapshot` (a new object and a
    refresh tied to ADR-013's replace-by-scope). DESIGN decides this, and it is
    not free either way.
  - The equal ballot remains. Filtering makes the sparse votes better. It does
    not make them count less.
  - **Unmeasured: whether it helps comparison at all.** See "A different problem"
    below. The comparison misses may not be lexical.
  - The out-of-scope scores will rise, as they did under ADR-015 (0.01639 →
    0.02964). Any out-of-scope question that shares a distinctive term with the
    corpus gets a second vote. The prediction here is that the rise is smaller
    than ADR-015's, but that is not measured.

### Option 2: Honest dense-only (ADR-015 Alternative 4)

Delete the sparse CTE and the fusion, and amend ADR-003, the README (hybrid appears
in the Why, the diagram and the architecture list) and AGENTS.md to say what the
system actually is.

- **Pros**
  - True today. For 43 of 50 questions the system already is dense-only.
  - Removes the equal-ballot risk entirely and simplifies the hot path.
  - Makes the fallback question cleaner: one score, one distribution.
- **Cons**
  - Gives up exact-term matching for good, in a corpus dense with identifiers.
  - The README states that hybrid retrieval is part of why the project exists
    ("production-grade retrieval discipline … hybrid retrieval"). Removing it is a
    product decision, not only a technical one. It is the author's call.
  - The sparse side still has not had a run with its noise removed. Choosing this
    without Option 1's measurement repeats the objection ADR-015 raised against
    deciding on a broken implementation.

### Option 3: DF-filtered OR with a weight on the sparse side

Option 1, plus a coefficient `w < 1` on the sparse RRF term, so that sparse can
reorder near-ties without outvoting a strong dense hit.

- **Pros**
  - Attacks the equal ballot directly, which Option 1 leaves alone.
  - ADR-003 already says fusion weights are tuned, so a weight is in its spirit.
- **Cons**
  - **Two knobs, both tuned on the same 50 questions.** ADR-003 says RAGAS-tuned,
    and RAGAS cannot run (no API key, 2026-09-29). Recall-tuning it would be the
    overfitting Option 1 avoids.
  - ADR-015 explicitly refused to introduce an untunable knob. Nothing has
    changed that makes it tunable.
  - It can only be judged against Option 1. It is a possible follow-up, not a
    first move.

### Option 4: Document the truth and change nothing

Amend ADR-003 and the README to say that the sparse side votes on keyword-shaped
input only (alive for `make ask q="why Snowpipe Streaming?"`, inert for full
questions), and leave the query alone until a UI shows what real input looks like.

- **Pros**
  - Cheapest. Fixes today's documentation defect whatever else happens.
  - Defensible: ADR-015 Alternative 3 said the real input shape "belongs to the
    UI feature", and no UI exists.
- **Cons**
  - Leaves the measured weakness (comparison at 4/11) with no plan.
  - It is a postponement, not a decision.

## Discarded early

- **OR without filtering (ADR-015 as it was).** Rejected by measurement on
  2026-09-21. Re-running it on 50 questions to see whether it "does better now"
  would be re-rolling a result until it comes out favourable.
- **Sweeping the cutoff and keeping the best one.** It overfits the golden set
  (see Option 1). If one pre-registered value fails, the answer is Option 2 or 4,
  not a second value.
- **`websearch_to_tsquery`, `pg_trgm`, Python-side keyword extraction, tuning
  `RRF_K`.** Each was discarded in `sparse-query-strategy/BRAINSTORM.md` for
  reasons that have not changed.
- **A hand-made stopword list for this corpus.** It is a document-frequency cutoff
  chosen by eye, frozen into a file that rots when the corpus changes. `ts_stat`
  gives the same thing measured and current.

## A different problem, noted so it is not lost

**The comparison misses look structural, not lexical.** In q043 and q045, one
project's ADR is found at rank 1 or 2 and the other project's is absent from the
top 20. The dense list fills up with one project's chunks. A sparse side, filtered
or not, would have to push the missing project's chunk up from below rank 20 on
lexemes alone. That is possible but unmeasured, and ADR-015 already saw q004's
missing ADR stay missing under OR.

The lever that fits this failure is different: **a per-project share of the
candidate list when the question is a comparison** (for example, the top k/2 from
each project). The README's architecture names an intent classifier as the place
where "this is a comparison" would be decided, but no such module exists in
`data_platform_rag/retrieval/` today, so this lever also means building it. That is its own ADR, and possibly a better
first move than this one for the comparison intent specifically. It is recorded
here so the two are not conflated. This brainstorm is about the sparse side, and
its success should not be judged on comparison alone.

## Emerging preference

**Option 1, gated on a rule written before the measurement, with Option 2 as the
pre-agreed destination if it fails.** Option 4's documentation fix belongs in
whichever path wins, because the README is inaccurate today either way.

Sketch of the rule, for DEFINE to make exact:

| reading (same snapshot, same model, vs 20260929-190639) | outcome |
|---|---|
| k=3 improves overall **and** no named case loses rank | Accepted |
| k=3 flat **or** worse, **or** any named case loses rank | Rejected → Option 2 (honest dense-only), as a new ADR |
| nothing moves at any k | Rejected → Option 2. A sparse side that changes nothing is decoration, and decoration is what Option 2 removes |

The named cases should be the ones with the most to lose: every question whose
declared path is at dense rank 1 today (q001 above all). Whether "improves" means
+1 path or a margin is for DEFINE. At 57 paths, one path is 1.75 points.

**What would change my mind:**

- If DESIGN finds the frequency storage costs more than a one-expression change
  (a new table, a refresh policy), Option 1 loses its main advantage over
  Option 2, and the case for simply being honest gets stronger.
- If the author decides the README's hybrid claim is not worth keeping, Option 2
  wins without a measurement, and this becomes a documentation feature.
- If the per-project comparison lever is taken first, this feature's before-reading
  must be retaken after it, not quoted from 20260929-190639.

## Gaps (not estimates)

- **No candidate has been measured**, deliberately (see the constraint above).
- **The before-reading runs on unmerged content.** It uses the q001–q050 set from
  PRs #21 and #22. If either changes before merge, the reading is retaken.
- **Recall is not answer quality.** ADR-014's own Consequences: source recall says
  whether the right file reached the LLM, not whether the answer is right.
  `make eval` is blocked on an API key.

## Author's decisions (2026-09-29)

- **Keep hybrid retrieval.** The README's claim stays a goal, so Option 2 is not
  chosen without a measurement. It remains the pre-agreed destination if Option 1
  fails its rule.
- **The sparse side first.** The per-project comparison lever waits, and when it
  comes, it retakes its own before-reading after this feature lands.

## Next step

- [x] Write DEFINE if a clear direction emerged: Option 1, with the rule above
      made exact and the cutoff fixed with its a-priori justification
- [ ] Or park with `status: Parked` and revisit
