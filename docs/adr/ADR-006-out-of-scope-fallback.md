# ADR-006 — Out-of-scope fallback message

**Status**: Accepted
**Date**: 2026-09-10

## Context

`data-platform-rag` is grounded on a finite corpus of ADRs and technical documentation.
Users will inevitably ask questions the corpus does not cover ("what did you
study in college?", "have you worked with Delta Live Tables?", "compare
Kafka and Pulsar"). The default LLM behavior — generate plausible-sounding
answers from parametric memory — is exactly what breaks trust in RAG
systems.

## Decision

When the top-ranked retrieved chunk falls below a similarity threshold
(baseline: 0.35 cosine, to be RAGAS-calibrated), the system does NOT call the
LLM. It returns a fixed fallback message:

> This question goes beyond what's documented in the ADRs I'm grounded on.
> Christian is the right person to answer directly — reach out on
> [LinkedIn](https://linkedin.com/in/christiandrocha) with the specific context.

The fallback event is logged in `query_log.fallback_fired = TRUE`, including
the query text and the top retrieved chunks (with their scores) that failed
the threshold. This log becomes the primary input for future corpus
expansion — questions that hit the fallback often are candidates for new
ADRs or KB entries.

## Consequences

**Positive**:
- Converts a limitation (finite corpus) into a product feature (honest scope).
- Turns unsatisfied queries into qualified leads — someone who asks a
  technical question and reads the fallback is more likely to reach out with
  useful context.
- Zero LLM cost on out-of-scope queries.
- The fallback rate is a real quality metric: if 80% of queries fire the
  fallback, either the threshold is too strict or the corpus is too narrow.
  Both are actionable.

**Negative / accepted trade-offs**:
- False negatives are possible — a query that *could* be answered from
  retrieved chunks below threshold gets the fallback anyway. This is
  preferable to hallucination.
- The threshold value is a magic number. ADR-008 will document its
  calibration against the golden set.
- Some users will experience the fallback as a dead-end. The redirect to
  LinkedIn is a partial mitigation, not a cure.

## Alternatives considered

- **Always answer, note uncertainty**: standard RAG anti-pattern. The LLM
  hedges plausibly and users don't know when to trust it.
- **Always answer with "I don't know" for unmatched queries**: kills the
  lead-generation angle and gives users nothing.
- **Two-stage: below threshold → LLM with explicit "context is weak" system
  prompt**: was considered. Rejected because it burns tokens on queries the
  corpus can't answer, and empirically LLMs still fabricate under "context
  is weak" prompting.

## Related

- ADR-008 (planned) — RAGAS calibration of the fallback threshold.
- Query log analysis in `data_platform_rag/evaluation/fallback_analytics.py`.
