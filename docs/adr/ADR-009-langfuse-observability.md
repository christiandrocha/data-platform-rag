# ADR-009 — Langfuse for LLM observability

**Status**: Accepted
**Date**: 2026-09-10

## Context

`data-platform-rag` calls Anthropic Claude Sonnet at runtime for both intent
classification (small call) and generation (main call). Each call has a
cost, latency, and quality dimension that need to be tracked over time —
not just aggregated in application logs, but sliceable by query intent,
prompt version, retrieval collection, and other metadata.

Additionally, RAGAS evaluation produces per-query quality scores that must
be correlated with production traces to detect quality regressions early.

## Decision

Use **Langfuse** (cloud free tier initially) for LLM observability:

- One Langfuse trace per user query
- Child spans per pipeline stage: intent classification, hybrid retrieval,
  reranking, threshold check, generation
- The Anthropic call is instrumented as a Langfuse `Generation` entity,
  unlocking native token and cost tracking
- RAGAS scores from `make eval` push to Langfuse attached to the trace that
  produced the query — same scoring system for evaluation and production
- Client is a singleton with a no-op fallback: `LANGFUSE_ENABLED=false`
  disables all Langfuse calls without changing pipeline code

## Consequences

**Positive**:
- Cost per query, latency per stage, and quality per query are all in one
  place, sliceable by trace metadata.
- RAGAS regression detection uses the same UI as production monitoring.
- Zero-config for contributors who don't want Langfuse — `LANGFUSE_ENABLED=false`
  and everything runs identically.
- Cloud free tier avoids self-hosting operational overhead in v1.
- Explicitly present on target job specs (Rimini Street lists observability
  for LLM systems as a required capability).

**Negative / accepted trade-offs**:
- Adds an external dependency for observability. Mitigated by the no-op
  client — Langfuse being down never breaks user queries.
- Free tier has retention limits (30 days). Sufficient for v1 where the
  goal is trend detection, not long-term audit.
- Trace metadata may leak query content. The system prompt does not include
  PII, and user queries in a public demo are self-selected — acceptable
  risk for v1. Reassess if deployment scope changes.

## Alternatives considered

- **Prometheus + Grafana for metrics, structured logs for traces**: works,
  but two systems instead of one, and no LLM-native concepts (Generation
  entity, cost tracking) require custom instrumentation.
- **Application logs only**: cheap but flat — no way to slice by trace
  metadata, no per-query cost aggregation, no regression detection.
- **Self-hosted Langfuse**: same benefits, more operational surface. Deferred
  to v2 if data locality becomes required.
- **Weights & Biases / Datadog LLM Observability**: comparable feature set,
  Langfuse chosen because open-source is preferred and the free tier is
  sufficient at demo scale.
