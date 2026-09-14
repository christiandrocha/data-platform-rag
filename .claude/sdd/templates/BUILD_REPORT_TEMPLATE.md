# BUILD REPORT: {Feature Name}

## Metadata

| Field | Value |
|-------|-------|
| Feature | {feature-slug} |
| DEFINE | link |
| DESIGN | link |
| Start date | YYYY-MM-DD |
| End date | YYYY-MM-DD |
| PR | link |

## What was built

Concrete list of files changed, tests added, ADRs written.

## What deviated from design

Every real build deviates from design somewhere. Log it honestly.

- Deviation 1 — why, impact
- Deviation 2 — why, impact

## RAGAS delta

Before this feature | After this feature

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Faithfulness | | | |
| Context Precision | | | |
| Answer Relevance | | | |
| Context Recall | | | |
| Fallback rate | | | |

## Known gaps at merge time

Things acknowledged as not-done, with next-step link if any.

## Verification

- [ ] `make lint` clean
- [ ] `make test` green
- [ ] `make eval` results attached
- [ ] `make verify-indexes` shows expected query plans
