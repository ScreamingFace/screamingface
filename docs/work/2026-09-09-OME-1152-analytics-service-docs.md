---
ticket: OME-1152
stack: repo
status: done
started: 2026-09-09
finished: 2026-09-09
---

# Analytics service contract and docs PR

## Intent

Prepare service-only ingestion/PostHog design and implementation plan, align SDK documents with service-first delivery and deferred Scoreboard aggregates, and open a docs-only PR. No implementation or merge.

## Planned changes

Service spec/plan, aligned SDK spec/plan, issue mirrors and this ledger.

## Test plan

Documentation reference/contract consistency checks and staged whitespace check. No app tests for unimplemented code.

## Acceptance

Child issue under OME-1060; OME-1124 dependency; reviewable docs PR with no runtime changes. Owner-only analytics landing-label prerequisite recorded.

## Outcome

- Created OME-1152 under OME-1060 and set the SDK dependency; aligned parent/SDK scope with service-first delivery and deferred aggregates.
- Added service spec/plan, aligned existing SDK draft spec/plan and three issue mirrors. No application code or infrastructure changed.
- Validation: JSON example and relative Markdown links passed; staged whitespace check before commit. Product tests not applicable to docs-only work.
- Docs PR will carry this branch; issue remains In Progress after docs review. No implementation or merge performed.
- Owner subsequently created analytics label; verified UUID via team-scoped Linear MCP listing, applied it to OME-1152 and registered it in the task-board card. Updated spec/plan/mirror and PR prerequisite wording. No label created by agent.
