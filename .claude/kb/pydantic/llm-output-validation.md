# Validating LLM output with pydantic

## The problem

The intent classifier calls an LLM with instructions to return JSON:

```json
{"intent": "decision", "collections": ["decisions"], "confidence": 0.87}
```

LLMs mostly comply, sometimes wrap in prose, occasionally invent fields.

## The solution

```python
from pydantic import ValidationError
from data_platform_rag.contracts import IntentClassification

async def classify_intent(query: str) -> IntentClassification:
    raw = await _call_llm_for_json(query)
    try:
        return IntentClassification.model_validate_json(raw)
    except ValidationError as e:
        # Log field-path context, retry once with an explicit repair prompt
        return await _classify_with_repair(query, raw, e)
```

## Repair pattern

The repair call sends the original LLM output + the ValidationError back to
the LLM, asking it to fix the JSON to satisfy the schema. Works for well-known
LLMs 90%+ of the time on first repair; if it fails, use default:

```python
async def _classify_with_repair(query: str, bad_json: str, err: ValidationError):
    repair_prompt = f"""Your previous JSON output failed validation:
{err.errors()}

Original output:
{bad_json}

Return valid JSON matching the schema. No prose, no markdown fences."""
    raw = await _call_llm_for_json(repair_prompt)
    try:
        return IntentClassification.model_validate_json(raw)
    except ValidationError:
        # Give up, use safe default
        return IntentClassification(
            intent="hybrid", collections=["decisions", "architecture"], confidence=0.0
        )
```

## Why fall back to hybrid?

If the classifier fails twice, defaulting to hybrid across all collections
maximizes recall at some cost to precision — better to over-retrieve than
miss the right chunk. Confidence 0.0 signals downstream that the classification
was a fallback and can be logged as such.
