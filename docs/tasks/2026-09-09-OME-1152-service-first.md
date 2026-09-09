---
id: OME-1152
linear_url: https://linear.app/openmined/issue/OME-1152
status: In Progress
priority: High
labels: [repo, agentic, design-session]
created: 2026-09-09
closed:
---

# OME-1152 — analytics delivery

## Outcome

Create an independently deployable `apps/analytics` service that validates opted-in SDK events and forwards them to the shared PostHog destination. Start with a docs-only contract/spec/plan PR; review and merge it before a separate implementation PR.

## First implementation scope

- Strict versioned event ingestion contract and privacy allowlist.
- PostHog forwarding with bounded retry, explicit delivery semantics and duplicate handling.
- Health/readiness, configuration, request/rate limits, synthetic tests and service CI/release/deployment registration.

## Excluded

SDK changes, Colab consent/cookie endpoints, website instrumentation, Scoreboard database aggregates and identity linking. These are later separate layer-specific units. SDK submission-success events cover the first funnel; database totals are deferred.

## Acceptance

- [ ] Docs-only PR defines HTTP/event contract, failure/dedup semantics, implementation plan and acceptance tests; approved and merged before code.
- [ ] Ingestion rejects unknown/forbidden fields, oversize payloads and invalid identifiers/event combinations.
- [ ] Transient failures retry within explicit bounds; retries preserve analytics event IDs; downstream delivery isn't falsely claimed.
- [ ] Synthetic test project proves anonymous PostHog delivery and dedup behavior; no production test events.
- [ ] Health, secrets/config, retention and operational limits documented and tested.
- [ ] Separate implementation PR includes service registration and required gates.

## Dependencies and workflow

Shared strategy: `OME-1060`. SDK `OME-1124` depends on this service contract/delivery. Work one layer at a time: service ingestion -> SDK local analytics -> service Colab bridge -> SDK Colab adapter. Do not merge or begin implementation from scope confirmation alone; review the docs PR first.

Metadata prerequisite: no analytics landing label exists. This issue is temporarily repo/design-session for the docs phase. Before service implementation, owner creates `analytics` under `app`, registers it in .claude/task-board.local.md, and applies it here in place of repo. Agents must not create labels.
