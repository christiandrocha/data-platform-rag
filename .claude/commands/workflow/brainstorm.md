---
name: workflow:brainstorm
description: Start a brainstorm for a new feature or open question
---

You are helping the user explore a topic before committing to a direction.

Steps:
1. Ask what we're exploring (if not provided in the invocation)
2. Create `.claude/sdd/features/{slug}/BRAINSTORM.md` from `.claude/sdd/templates/BRAINSTORM_TEMPLATE.md`
3. Propose 3-4 options with pros/cons
4. Note discarded early options with reason
5. Recommend an emerging preference OR park the topic

Do NOT commit any code from a brainstorm alone. Do NOT proceed to DEFINE without user confirmation.

Load the SDD workflow contract before starting:
@.claude/sdd/architecture/WORKFLOW_CONTRACTS.yaml
