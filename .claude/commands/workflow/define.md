---
name: workflow:define
description: Write a DEFINE.md for a feature — problem, users, goals, success criteria
---

You are formalizing what problem we're solving.

Steps:
1. If a BRAINSTORM.md exists for this feature, read it and cite emerging preferences
2. Copy `.claude/sdd/templates/DEFINE_TEMPLATE.md` to `.claude/sdd/features/{slug}/DEFINE.md`
3. Fill in problem, users, goals (MUST/SHOULD/COULD), measurable success criteria, acceptance tests
4. Run the Clarity Score self-check honestly — 12/15 minimum to proceed
5. Surface any open questions explicitly

Do NOT proceed to DESIGN if Clarity Score < 12/15 — return to gather more clarity first.

Load:
@.claude/sdd/templates/DEFINE_TEMPLATE.md
@.claude/sdd/architecture/WORKFLOW_CONTRACTS.yaml
