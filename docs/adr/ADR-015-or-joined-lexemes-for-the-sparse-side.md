# ADR-015 — OR-joined lexemes for the sparse side of hybrid retrieval

**Status**: Rejected — 2026-09-21, by the measurement this ADR fixed in advance. See [Outcome](#outcome)
**Date**: 2026-09-21

> Planned on 2026-09-21 with the decision rule below; rejected the same day by
> BUILD's measurement. The Context, Decision and Consequences sections are kept
> exactly as written before the measurement. They are the prediction the outcome
> is judged against.

## Context

ADR-003 specifies hybrid retrieval: dense (pgvector cosine) and sparse
(PostgreSQL `tsvector`) fused by reciprocal rank fusion. The fusion arithmetic is
implemented correctly and asserted by hand in
`tests/integration/test_hybrid_search_postgres.py`. It has never had two lists to
fuse.

`plainto_tsquery` conjoins every term with `&`, so a natural-language question
demands that one chunk contain all of them:

```
plainto_tsquery('english', 'Why did the Snowflake project choose Snowpipe
Streaming over the classic file-based Snowpipe?')
  → 'snowflak' & 'project' & 'choos' & 'snowpip' & 'stream'
    & 'classic' & 'file-bas' & 'file' & 'base' & 'snowpip'
  → 0 chunks of 304
```

Measured over the golden set: **0 matching chunks for four of five questions, 2
for the fifth**. `websearch_to_tsquery` behaves identically. The planner states it
plainly — `Subquery Scan on s … rows=0`, `Rows Removed by Filter: 304`. Recorded
in ADR-003 Amendment 1 §B, which deliberately left it unfixed because changing
it is a retrieval-strategy decision that needs its own ADR. This is that ADR.

**It is not broken for every input.** Measured live on 2026-09-21,
`make ask q="why Snowpipe Streaming?"` — three words — returns sparse scores of
0.2091 and 0.3118 and a fused score of 0.03202, which is two contributions
summed. The sparse side is **inert for questions and alive for keywords**. The
system has no way to know which it will be given, because no UI exists.

## Decision

**Build the sparse query as a disjunction of the lexemes `plainto_tsquery`
already produces**, rewriting only the operator, inside SQL:

```sql
replace(plainto_tsquery('english', %(query_text)s)::text, ' & ', ' | ')::tsquery
```

`plainto_tsquery` keeps doing the parsing, stemming, stopword removal and — the
part that must not move — the sanitising. Only the separators change.

**Status is Planned, not Accepted, and that is the point.** The decision rule is
fixed here, before the measurement, so the result cannot be rationalised after
it. BUILD runs `make retrieval-recall` on the same snapshot as the before-reading
(`.claude/dev/reports/retrieval-recall-20260921-142654.json`, k=3 3/6, k=10 5/6,
k=20 5/6) and this ADR is promoted or rejected by it:

| reading at k=3 | outcome |
|---|---|
| ≥ 4/6 | promoted to Accepted |
| 3/6, with k=10 or k=20 improving | promoted only if nothing regressed; the case passes to ADR-005 |
| < 3/6 | **rejected.** The equal-ballot problem below is real, and the decision becomes term filtering or honest dense-only |

## Consequences

**The sparse side stops being decorative.** 158–211 of 304 chunks match per
question instead of 0–2. `ts_rank_cd` then does the job it was always given.

**Measured on 2026-09-21 against the live index, before any code changed**, the
top three sparse hits per question would be:

| question | sparse top-1 | is it a declared path? |
|---|---|---|
| q001 | `0029_snowpipe_streaming…` [Context], 2.0 | **yes** — already dense rank 1 |
| q002 | `003_parametrized_notebooks.md`, 1.5, **tied** with `007_pipeline_unification.md` at 1.5 | the tied one is the declared path, currently at dense **rank 7** |
| q003 | `README.md` [Architecture], 1.3 | **yes** — already dense rank 1 |
| q004 | `001_databricks_vs_snowflake.md`, 1.5 | **no** — q004's missing path stays missing |
| q005 | `007_pipeline_unification.md` [Addendum 4], 1.1 | q005 is **out of scope** and declares none |

So the expected gain is concentrated in q002, which is exactly the question the
k=3 criterion turns on. And the expected non-gain is q004, whose missing
Snowflake ADR is not reachable by lexeme overlap either.

**The out-of-scope question gets a higher score, not a lower one.** This is the
consequence worth stating loudest. q005 matches 211 chunks under OR, so its
fused top score rises from `1/(60+1) = 0.01639` to roughly `0.0328` — two
contributions instead of one. **Populating the sparse side makes an out-of-scope
question look more confident, not less.** It does not create the fallback problem
(ADR-006's threshold was already meaningless against RRF: 0.35 against a maximum
of 0.0164) but it does move in the wrong direction, and ADR-005 and ADR-006 must
be written knowing it.

**RRF gives the two sides an equal ballot and there is no weight to turn.** The
query sums `1/(60+dense_rank)` and `1/(60+sparse_rank)` with no coefficient. A
200-row sparse list votes as loudly as a 20-row dense one. ADR-003 says the
weights are RAGAS-tuned; RAGAS does not exist, and no weight field exists in the
query or in `config.py`. **No weight is introduced here** — introducing an
untunable knob would be guessing, which the same ADR-003 line forbids. If the
measurement shows the sparse side drowning the dense one, the answer is the
rejection branch above, not a hand-picked coefficient.

**Ties become common and must break deterministically.** q002's top two sparse
hits are both 1.5. `ORDER BY rrf_score DESC, c.id ASC` already exists for this
reason and now carries real weight.

**`ts_rank_cd` is computed over all 304 candidates before either side is
limited.** Already true, already recorded as a known gap. This change makes it
load-bearing rather than theoretical — the first place to look if retrieval ever
gets slow.

**No schema change, no reindex, no new dependency.** `content_tsv` and its GIN
index are untouched. A revert is a one-expression revert.

## Alternatives considered

**1. `websearch_to_tsquery` as a drop-in.** Measured 2026-09-18: identical to
`plainto_tsquery`, 0 chunks for four of five questions. It ORs nothing unless the
user types `or`. Recorded so it is not proposed again.

**2. Drop generic terms by document frequency, then OR (`ts_stat`).** Attacks the
real risk — "project", "data" and "pipeline" should not vote. Rejected *for now*,
not on merit: it needs a threshold, and a threshold needs justification against a
golden set of 5 questions and 6 declared paths. It stays the first candidate if
this ADR is rejected.

**3. AND first, OR only when AND returns zero.** Keeps conjunction precision for
keyword input, which the `make ask` measurement shows is a real input shape.
Rejected because it puts two retrievers behind one entry point, selected by a
property of the data rather than of the request — a recall number would then
average two different retrievers, which is what ADR-014 exists to prevent. The
open question it answers (what shape does real input take?) belongs to the UI
feature.

**4. Delete the sparse side and be honestly dense-only.** The README, AGENTS.md
and ADR-003 all claim hybrid retrieval, and the claim is currently false.
Rejected because it reverses a decision on the strength of a measurement taken
with a broken implementation — the sparse side has never had a fair run. It
returns as the answer if this ADR is rejected.

**5. Tune `RRF_K`.** Fixed at 60 by ADR-003, and a different constant cannot turn
an empty list into a populated one. Wrong lever.

## Outcome

**Rejected.** Measured on 2026-09-21 on the same snapshot as the before-reading
(`sdd-kafka-databricks@f1295df9`, `sdd-kafka-snowflake-2@82a2e269`, indexed
2026-09-18). Before: `.claude/dev/reports/retrieval-recall-20260921-142654.json`.
After: `retrieval-recall-20260921-162458.json` and `-162524.json`, two runs,
identical rankings and scores.

| | before | after |
|---|---|---|
| questions with sparse rows | 1/5 | 5/5 |
| source recall at k=3 | 3/6 | 3/6 |
| source recall at k=10 | 5/6 | 5/6 |
| source recall at k=20 | 5/6 | 5/6 |
| q005 (out of scope) top fused score | 0.01639 | 0.02964 |

Declared paths, rank before → after:

| question | path | rank |
|---|---|---|
| q001 | `0029_snowpipe_streaming…` | 1 → **2** |
| q002 | `007_pipeline_unification.md` | 7 → 6 |
| q003 | `README.md` | 1 → 1 |
| q003 | `0030_avro_and_schema_registry…` | 5 → **9** |
| q004 | `README.md` (databricks) | 1 → **2** |
| q004 | `0030_avro_and_schema_registry…` | not in top 20 → not in top 20 |

**Why rejected.** DEFINE required q001's declared path to stay at rank 1, and it
did not. q001's top two tie **exactly** at 0.03200. `001_databricks_vs_snowflake.md`
is dense 3, sparse 2, and the correct ADR's chunk is dense 2, sparse 3, so
`1/63 + 1/62` on both sides. The id tiebreak put the wrong ADR first. The sparse
side, given an equal ballot, added no signal that separated the right document
from a wrong one. It only made them indistinguishable. Three declared paths lost
rank, one gained a single place, and no recall bucket moved.

**The predictions this ADR made, checked:**

- *"The gain is concentrated in q002"*: **wrong.** `007_pipeline_unification`
  moved 7 → 6, not into the top 3. Under OR, `003_parametrized_notebooks.md`
  took sparse rank 1 on the 1.5 tie, and the 007 chunk that reached sparse rank
  2 is at dense rank 15.
- *"q004's missing ADR stays missing"*: **right.**
- *"The out-of-scope question gets a higher score"*: **right in direction,
  smaller in size.** Predicted ~0.0328; measured 0.02964 (+81 %). The ranks of
  q005's top chunk on the two sides do not coincide (dense 6, sparse 9).
- *158–211 chunks match per question*: consistent. q002 matched 179 in the
  `EXPLAIN ANALYZE` of the real query.

**A gap in the decision rule, recorded rather than exploited.** The table above
has no row for "flat at every k": the 3/6 row requires k=10 or k=20 to improve.
The reading fell in that gap. It did not decide the outcome, because the DEFINE
criterion on q001 failed independently, but the next decision rule written in
this project should cover every reading, including "nothing moved".

**What survives the rejection.** Two things found during BUILD were not part of
the OR decision and stay in the code:

- **Both `ROW_NUMBER()` windows now break ties by `id`.** Before, a tie on
  `dense_dist` or `sparse_score` was ranked in heap order, so a rank could change
  after a reindex with no change to the corpus. A test that rewrites a row to the
  end of the heap failed without the tiebreak (`assert 2 == 1`) and passes with it.
- **The sanitising and empty-query tests.** They pass under `plainto_tsquery`
  alone and guard the property that must hold whatever builds the tsquery next.

**What this reopens.** Alternative 2 (drop generic terms by document frequency)
is now the first candidate, and the q001 tie is the case it would have to win.
Measured with `ts_stat` over the 304 chunks, q001's broadest lexemes are
`snowflak` (94 chunks, 31 %), `stream` (72, 24 %) and `project` (47, 16 %),
against `snowpip` (19, 6 %) and `classic` (9, 3 %). No term is in most chunks,
so a document-frequency cutoff would have to be low, around a fifth of the
corpus, and whether it separates the q001 tie is unmeasured. Alternative 4
(honest dense-only) remains the fallback. Either one is a new ADR, not an
amendment to this one.
