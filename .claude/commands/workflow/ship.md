---
name: workflow:ship
description: Ship a feature — PR, deploy, retrospective
---

You are shipping a completed feature.

Steps:
1. Confirm all acceptance tests pass and RAGAS meets targets (via BUILD_REPORT)
2. Open PR referencing DEFINE.md, DESIGN.md, and ADRs (if any)
3. Wait for CI green (lint, test, ragas jobs)
4. Merge to main
5. Verify Streamlit Cloud deploy at production URL
6. Copy DEFINE/DESIGN/BUILD_REPORT to SHIPPED.md summary and move feature folder to `.claude/sdd/archive/`

Do NOT ship without:
- CI green
- Deploy verified on production URL
- SHIPPED.md written

Load:
@.claude/sdd/templates/SHIPPED_TEMPLATE.md
