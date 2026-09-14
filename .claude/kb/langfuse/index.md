# Langfuse KB — data-platform-rag

Scope: LLM observability for `data-platform-rag`. Traces every retrieval + generation
attempt, tracks token cost, and receives RAGAS scores as feedback.

Langfuse Cloud free tier initially. Self-hosting is a future option if data
locality becomes a requirement.

## Files

- `traces-and-generations.md` — trace hierarchy for our pipeline
- `cost-tracking.md` — token accounting for Anthropic Claude Sonnet
- `scoring.md` — pushing RAGAS scores back to Langfuse as observations
- `python-sdk.md` — SDK setup, decorators used in `data_platform_rag/observability/`

## Design principles

1. **One trace per user query.** Root span = whole pipeline. Child spans =
   intent classification, retrieval, reranking, generation.
2. **Scores land on traces.** RAGAS metrics push to the trace that produced
   the query, so we can slice quality by any trace metadata.
3. **Never block on Langfuse.** Failures to flush must not break the query
   pipeline. Async client, fire-and-forget.
4. **Metadata is stable.** The set of tags on a trace is documented and
   enforced by pydantic. Adding a new tag is a code change, not ad-hoc.

## Anti-patterns

- Instrumenting inside a tight loop without batching
- Storing PII in trace metadata (queries can contain names, addresses)
- Using traces to replace application logs
