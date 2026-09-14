---
name: workflow:design
description: Write DESIGN.md and (if architectural) an ADR
---

You are designing HOW to solve the problem defined in DEFINE.md.

Steps:
1. Read the feature's DEFINE.md — do not proceed if it doesn't exist or Clarity Score < 12
2. Copy `.claude/sdd/templates/DESIGN_TEMPLATE.md` to `.claude/sdd/features/{slug}/DESIGN.md`
3. Detail architecture, data contracts, interfaces, alternatives considered
4. Assess RAG-specific impact — chunking, HNSW, query patterns, RAGAS
5. If this is an architectural decision (affects data model, retrieval strategy, or external interfaces), write an ADR in `docs/adr/ADR-XXX-{topic}.md` following the format used in the two source projects
6. Write a test plan
7. Write a rollout plan with rollback

Load:
@.claude/sdd/templates/DESIGN_TEMPLATE.md
@AGENTS.md  # for the ADR discipline conventions
