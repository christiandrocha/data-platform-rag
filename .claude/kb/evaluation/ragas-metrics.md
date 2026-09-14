# RAGAS metrics — what they mean, when they degrade

| Metric | Range | What it measures | Common regression cause |
|--------|-------|------------------|-----------------------|
| Faithfulness | 0-1 | Answer supported by retrieved context | LLM hallucination, weak system prompt |
| Answer Relevance | 0-1 | Answer addresses the question | System prompt drift, wrong task framing |
| Context Precision | 0-1 | Retrieved chunks are relevant | Retrieval order (rerank quality) |
| Context Recall | 0-1 | All needed chunks retrieved | Retrieval breadth (k too small, threshold too strict) |

## Baseline targets

Aim for all four > 0.80 before publishing badges. Below that, iterate.

## Regression policy

Any metric dropping > 0.05 from previous CI run → CI red. Override requires an ADR.
