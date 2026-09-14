---
name: workflow:iterate
description: Fix issues found during BUILD or by RAGAS regression
---

You are iterating on a feature after initial BUILD revealed problems.

Steps:
1. Read the BUILD_REPORT for known issues
2. Prioritize by acceptance test failures first, RAGAS regressions second, code quality third
3. Fix, re-test, re-eval
4. Update BUILD_REPORT.md with a "Iteration N" section describing what changed and why

Iteration ends when acceptance tests pass AND RAGAS meets targets.
