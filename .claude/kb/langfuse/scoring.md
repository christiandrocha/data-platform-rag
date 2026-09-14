# Scoring — RAGAS feedback into Langfuse

## Flow

```
make eval → scripts/run_evaluation.py
    │
    ├─ For each golden-set question:
    │    1. Run the pipeline (creates a Langfuse trace)
    │    2. Compute RAGAS metrics
    │    3. Push scores to Langfuse, attached to that trace
```

## Scores we push

| Score name | Type | Range | Source |
|-----------|------|-------|--------|
| `ragas_faithfulness` | numeric | 0-1 | RAGAS |
| `ragas_answer_relevance` | numeric | 0-1 | RAGAS |
| `ragas_context_precision` | numeric | 0-1 | RAGAS |
| `ragas_context_recall` | numeric | 0-1 | RAGAS |
| `fallback_correct` | boolean | 0/1 | Ground truth: should_fallback == fallback_fired |

## Why send RAGAS to Langfuse

- Slice metrics by any trace metadata (intent, collections, prompt version)
- Detect regressions over time — Langfuse UI shows score trends
- Same score system whether trace came from eval or production
