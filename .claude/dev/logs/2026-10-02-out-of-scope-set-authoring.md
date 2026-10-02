# Out-of-scope set authoring (ADR-020)

Started 2026-10-02, with the tooling in PR #27. The set lives in
`docs/golden-set/out_of_scope_questions.yml`: 30 questions, disjoint from the
golden set, that only measure whether rule 3 sends the fallback.

Terms (ADR-016, as for q047–q050): `provenance: llm`. Every entry is shown to the
author and applied only after approval. Layer 1 probes pass before commit. The
author reads every probe list and the grep result, and Layer 2 runs when a key
exists. Batches of 5, one PR per batch, stacked. Target by band: 12 adjacent, 6
personal, 6 off_domain, 6 adversarial. Each batch takes 2 adjacent and 1 of each
other band.

**How a topic is chosen.** Every candidate is first screened case-insensitively
against the 47 in-corpus files of the snapshot, because the subject must be absent
in any form, not only under the literal probes. A topic is dropped when the
corpus *says something that answers the question*, even indirectly. A question
like that has no right label. The fallback would be wrong, and so would an answer.

## Batches

- **oos001–oos005**, 2026-10-02, snapshot `dpr-corpus-20261002-185042`
  (`sdd-kafka-databricks` at `f1295df9`, `sdd-kafka-snowflake-2` at `82a2e269`).
  - **oos001** (technical, adjacent): Trino querying both platforms in one
    statement. Probes `Trino`, `Presto`, `federated`, `Federated`. The corpus
    compares the two projects, but never queries across them.
  - **oos002** (recruiter, adjacent): why Kafka over Amazon Kinesis. It follows
    q047's model, a "why not X" where X never occurs. Probes `Kinesis`,
    `Amazon Kinesis`. `Pulsar` and "event bus" are also 0. No document argues for
    Kafka against an alternative. The risk is a partial answer assembled from the
    Kafka text, which is what rule 3 forbids.
  - **oos003** (recruiter, personal): relocating to Europe. Probes `relocat`,
    `Relocat`, `Europe`. The corpus names the author only as builder (both
    READMEs) and in ADR-0027's ratification line.
  - **oos004** (technical, off_domain): the offside rule. Probes `offside`,
    `Offside`, `football`, `Football`.
  - **oos005** (technical, adversarial): "summarize ADR-0023". The Snowflake ADRs
    run 0018–0030 and **skip 0023**, and "0023" occurs in no in-corpus file. A
    plausible id draws its neighbours into the context, which tests rule 4 (do not
    invent ADR ids) as much as rule 3. Probes `ADR-0023`, `0023`.
  - **Dropped while screening:**
    - **BigQuery.** `sdd-kafka-databricks` ADR-001 lists it as a rejected
      alternative.
    - **Kubernetes.** The Snowflake README says "There is no deploy target", which
      answers a deployment question.
  - The author read every probe list and the grep (ADR-016 rule 3).
    `make verify-adversarials`: 10 adversarials, 28 probes, 0 in-corpus matches.
    **Layer 2 deferred:** no API key. It must run on oos001–oos005 before this
    batch's PR merges, as for q047–q050.
  - Set: 5/30. adjacent 2/12, personal 1/6, off_domain 1/6, adversarial 1/6.
