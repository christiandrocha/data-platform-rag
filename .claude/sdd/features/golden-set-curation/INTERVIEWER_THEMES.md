# Interviewer themes — angles for the 45 remaining questions

> Research input for authoring, 2026-09-22. **Angles, not questions.** ADR-011
> Commitment 1 stands: every question and `expected_answer` is written by the
> author. This file only says *what a technical interviewer would be curious
> about*, per corpus unit.

## How this was built, and what it avoids

- **Audience.** A technical interviewer (hiring manager or senior engineer)
  probing the two projects: why, trade-off, failure, what would change. All 45
  questions carry `voice: technical` (see DESIGN T4).
- **Market input.** 2026 interview guides for data engineers on Kafka/CDC,
  Snowflake/dbt, Databricks and Dagster (sources at the end) set which themes
  interviewers probe: CDC and deletes, schema evolution and contracts,
  idempotency and watermarks, medallion layering, cost governance, governance
  and naming, orchestration triggers, platform choice.
- **Corpus input.** Angles are tied to units using only each ADR's title and
  opening lines, and the TL;DR / Problem / Stack sections of both READMEs. ADR
  bodies were not read, so their phrasing could not leak into the angles.
- **Written in Portuguese on purpose.** The author writes each question in
  English, in their own words. Translating an angle is not copying a sentence.
- **Lookup, not a script.** Authoring order still follows `make golden-set-next`
  (seed `20260914`, ADR-011).

Legend: **SF** = `sdd-kafka-snowflake-2`, **DB** = `sdd-kafka-databricks`.

## Decision — 20 (18 uncovered ADRs + 2)

| Unit | Angle |
|---|---|
| SF 0018 | Que falha do orquestrador justificou um banco dedicado, e por que não reusar o Postgres de origem? |
| SF 0019 | Como detectar dado novo sem acordar o warehouse, e qual era o conflito com o auto-suspend? |
| SF 0020 | Duas fontes descreviam limites de gasto diferentes: como isso foi descoberto e resolvido? |
| SF 0021 | O que a tipagem nativa na ingestão elimina nos modelos, e que custo ela traz? |
| SF 0022 | Como provar que um domínio não é usado antes de cortá-lo da ingestão? |
| SF 0022 (+1) | Por que ler as dependências reais dos modelos em vez de confiar nos nomes? |
| SF 0024 | Por que uma marca d'água global esconde domínios de baixo volume? |
| SF 0025 | Que mecanismos quebram se a camada bronze deixar de ser só inserção? |
| SF 0026 | Por que um modelo que calcula uma razão global não pode ser incremental? |
| SF 0027 | Qual critério decide entre `error` e `warn` num teste? |
| SF 0028 | Por que manter os metadados do Kafka que a tipagem nativa deveria ter eliminado? |
| SF 0030 (+1) | Que compatibilidade de schema foi escolhida, e o que ela permite ou barra? |
| DB 001 | O que ficou idêntico e o que mudou ao trocar só a camada de destino? |
| DB 002 | Achatar o envelope do Debezium no conector ou no Spark: qual o trade-off? |
| DB 003 | Parametrizar notebooks resolveu a duplicação, mas o que isso quebrou depois? |
| DB 004 | Por que a chave de clustering precisa bater com a chave do MERGE? |
| DB 005 | Como um join em coluna não única corrompe a camada gold sem erro visível? |
| DB 006 | Por que a linhagem do Unity Catalog forçou a migração para Lakeflow? |
| DB 008 | O que a origem precisa configurar para um DELETE chegar ao destino? |
| DB 009 | Por que renomear campos que vêm do Debezium teve de ser revertido? |

## Architecture — 17 of 61 units, chosen by interviewer relevance

| Unit | Angle |
|---|---|
| SF README#The Problem | Quais são as duas falhas de um pipeline CDC que não parecem falhas? |
| SF README#Stack | Como o dado atravessa as camadas, da origem até o dbt? |
| SF README#Layered modeling | Que responsabilidade tem cada camada do dbt? |
| SF README#Cost governance | Onde fica o freio de gasto, e o que acontece quando ele dispara? |
| SF README#Data quality | Como a severidade dos testes foi aplicada no conjunto? |
| SF README#CI/CD | Como o CI valida o dbt sem credenciais reais? |
| SF README#Known gaps and unverified claims | O que não foi comprovado, e por quê? |
| SF README#What Evolved from sdd-kafka-snowflake | O que a primeira versão errou que a segunda corrigiu? |
| SF dbt/macros/resolve_cdc.sql | Como a estratégia de CDC vira dado em vez de SQL? |
| DB README#TL;DR | Por que o volume do dataset é suficiente para validar o desenho? |
| DB README#Stack | Quais os trade-offs de KRaft, de `availableNow` e dos Asset Bundles? |
| DB README#Data Contracts — The Differentiator | Onde o contrato é aplicado: no carregamento, no Spark, no CI? |
| DB README#Unity Catalog Structure | Como catálogos e schemas separam os ambientes? |
| DB README#Domain Map (20 tables) | Como 4 sistemas de origem viram 20 tabelas? |
| DB contracts/users_mongo.yml + users_mssql.yml | Como reconciliar a mesma entidade vinda de fontes distintas? |
| DB README#Next Steps | O que falta para esse pipeline aguentar volume real? |
| DB README#Methodology — AgentSpec SDD | Como o desenvolvimento orientado por especificação guiou as decisões? |

**Excluded on purpose:** both `README.md#Interview Cheat Sheet` sections. They
already answer interview questions almost verbatim, so an interviewer's question
would match them by phrasing, not by retrieval. That is the contamination
ADR-011 exists to prevent.

## Comparison — 4

| Angle | Units |
|---|---|
| Mesmo CDC, dois destinos: onde os trade-offs divergiram? | DB 001 + SF README#Stack |
| Propagação de DELETE em cada projeto | DB 008 + SF resolve_cdc.sql |
| O que dispara o processamento: gatilho do warehouse ou job agendado? | SF 0019/0024 + DB README#Stack / 007 |
| Onde vive o contrato: Schema Registry ou contratos YAML? | SF 0030 + DB README#Data Contracts |

The last pair sits close to q004 (schema evolution across both projects). Kept
on purpose; the author should make the two questions ask different things.

## Out-of-scope — 4, completing decision C3's gradient

q005 already fills the subjective/opinion band.

| Band | Angle | Probe candidates |
|---|---|---|
| adjacent-but-absent | Por que não Airflow para orquestrar? | `Airflow` |
| adjacent-but-absent | Considerou Apache Iceberg como formato de tabela? | `Iceberg` |
| trivially out-of-domain | Uma pergunta técnica sem relação com dados (ex.: frontend, mobile) | to be chosen by the author |
| prompt-extraction | Pedido para revelar ou ignorar as instruções do sistema | n/a — grep the probe anyway |

Reserves for the adjacent band: `Great Expectations`, `Apache Hudi`.
All were absent on 2026-09-14 and **must be re-grepped** (ADR-011 Layer 1,
case-sensitive, in-corpus files only) before entering the set.

## Sources

- https://www.kore1.com/data-engineer-interview-questions/
- https://www.kore1.com/snowflake-engineer-interview-questions/
- https://www.kore1.com/databricks-engineer-interview-questions/
- https://datavidhya.com/blog/kafka-data-engineering-interview-questions/
- https://datavidhya.com/blog/data-engineering-interview-questions/
- https://datavidhya.com/blog/databricks-data-engineering-interview-questions/
- https://www.datacamp.com/blog/databricks-interview-questions
- https://www.datainterview.com/blog/snowflake-data-engineer-interview
- https://www.tryexponent.com/blog/data-engineering-interview
- https://pipeline2insights.substack.com/p/week-1734-data-pipelines-and-workflow-airflow-dagster-interview-questions
