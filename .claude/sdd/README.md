# .claude/sdd — AgentSpec SDD framework

Six-phase workflow for adding features to data-platform-rag:

1. **Brainstorm** — explore, no commits (`templates/BRAINSTORM_TEMPLATE.md`)
2. **Define** — problem, users, goals, success criteria (`templates/DEFINE_TEMPLATE.md`)
3. **Design** — architecture, interfaces, ADR if needed (`templates/DESIGN_TEMPLATE.md`)
4. **Build** — implement, test, document (`templates/BUILD_REPORT_TEMPLATE.md`)
5. **Iterate** — RAGAS regression, fix, refactor
6. **Ship** — PR, deploy, retrospective (`templates/SHIPPED_TEMPLATE.md`)

Each feature lives in `features/{feature-slug}/` with its phase artifacts.
Shipped features are moved to `archive/` (read-only history).

Reports (RAGAS runs, incident post-mortems, verification captures) live in `reports/`.

Architecture-level contracts live in `architecture/`.
