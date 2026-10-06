# RAGAS metrics — what they mean, when they degrade

| Metric | Range | What it measures | Common regression cause |
|--------|-------|------------------|-----------------------|
| Faithfulness | 0-1 | Answer supported by retrieved context | LLM hallucination, weak system prompt |
| Answer Relevance | 0-1 | Answer addresses the question | System prompt drift, wrong task framing |
| Context Precision | 0-1 | Retrieved chunks are relevant | Retrieval order (rerank quality) |
| Context Recall | 0-1 | All needed chunks retrieved | Retrieval breadth (k too small, threshold too strict) |

## Baseline targets

Aim for all four > 0.80 before publishing badges. Below that, iterate. This is
an aim, not an ADR-008 decision, and badges come from a committed baseline only.

## Regression policy (ADR-008, Decision 7)

No threshold exists yet. The rule's form: a metric's mean falling below the
**committed baseline's** by more than T(metric) fails `compare --gate`. T is
chosen by a rule fixed before measuring: generate 2 runs, score each twice, and
T(metric) is the largest difference among those 4 means. Until then `make
eval-compare` reports deltas and never fails.

The old "> 0.05 from the previous CI run" was never measured, and "previous run"
is not a baseline: a slow slide passes every step. It is withdrawn.

## How a run is read

- Every mean is printed with its coverage, `mean (n/45)`. A metric RAGAS could
  not compute (an error, NaN, a failed generation) is **missing**, never 0
  (ADR-008, Decision 5).
- The 5 out-of-scope questions get `fallback_correct` only. In-scope questions
  that got the fallback are scored as they are and counted in
  `in_scope_fallbacks`.
- Two reports are comparable only with the same golden-set SHA (ADR-011), a
  committed golden set, and the same judge (`settings.judge_model`,
  `settings.judge_max_tokens`, `settings.answer_relevancy_strictness`, the RAGAS
  version, the judge temperature).
