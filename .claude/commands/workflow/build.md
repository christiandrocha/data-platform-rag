---
name: workflow:build
description: Implement a feature per its DESIGN.md
---

You are implementing what DESIGN.md specifies.

Steps:
1. Read DEFINE.md and DESIGN.md — do not proceed if either is missing
2. Implement per DESIGN.md
3. Add tests: unit tests for pure functions, integration tests for pipelines
4. Run pre-commit hooks (ruff, yamllint, bandit)
5. Update BUILD_REPORT.md honestly — deviations, gaps, RAGAS delta
6. If schema changed, update `sql/01_schema.sql` and `sql/02_indexes.sql`. Run `sql/99_verify.sql` and paste EXPLAIN ANALYZE into the BUILD_REPORT.

Do NOT skip:
- Writing tests
- Running `make eval` if retrieval or generation changed
- Filling the RAGAS delta section of BUILD_REPORT.md

Load:
@.claude/sdd/templates/BUILD_REPORT_TEMPLATE.md
@AGENTS.md
