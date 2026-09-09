---
id: OME-1152
linear_url: https://linear.app/openmined/issue/OME-1152
status: In Progress
priority: High
labels: [analytics, agentic, autonomous]
created: 2026-09-09
closed:
---

# OME-1152 — analytics delivery

## Outcome

Create an independently deployable `apps/analytics` service that validates opted-in SDK events and forwards them to the shared PostHog destination. Start with a docs-only contract/spec/plan PR; review and merge it before a separate implementation PR.

## First implementation scope

* Strict versioned event ingestion contract and privacy allowlist.
* PostHog forwarding with bounded retry, explicit delivery semantics and duplicate handling.
* Health/readiness, configuration, request/rate limits, synthetic tests and service CI/release/deployment registration.

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

Metadata prerequisite completed: owner-created analytics label is applied and registered in the task-board card. Design-session remains during docs review. Keep this issue open until service implementation acceptance.

## Confirmed measurement contract — 9 September 2026

- Activity is an observed evaluation_started event in the trailing seven-day UTC window. WAS counts distinct session IDs; weekly active browsers/installations count their available persistent IDs separately. Failed/cancelled attempts still qualify activity. These are not unique-person counts.
- One session per Python process/notebook kernel, shared across clients and wrappers; no idle rotation. Restart/fork creates a new session. Persistent IDs remain stable while consent is valid, with reset on opt-out, explicit reset or storage loss.
- Remember consent without a scheduled re-prompt; ask again only when purpose/data materially changes or the choice is lost. Consent-only Colab bridge reads are approved before consent is known, but create no analytics ID or events; explicit disable suppresses those reads too.
- Four initial events: evaluation_started/finished and submission_started/finished, with coarse duration on finish. Evaluation outcomes: succeeded only for a returned reconciled Report with Report.ok=true, completed_with_failures for Report.ok=false, failed for exceptions, cancelled for user cancellation. Submission outcomes: succeeded/failed/cancelled. Missing terminal events are not inferred.
- Explicit origin=colab/local_jupyter/python/cli and usage_mode=byok/hosted. No unknown or mixed values. Missing/invalid integration metadata drops the event with a local debug diagnostic; evaluation proceeds. The service rejects invalid payloads. No endpoint guessing.
- Best-effort background delivery, bounded retries, occasional loss accepted, no durable queue first phase. Analytics must never block evaluations.
- Raw events retained for 90 days. Longer-lived aggregates contain no browser/installation/session IDs; individual retention beyond 90 days is unavailable.
- Discovery/review events and benchmark/provider/cost/cache-hit fields are deferred. No identity linking, email prompts, website instrumentation or Scoreboard database aggregates in this first slice.

Authoritative docs review: [ScreamingFace analytics docs PR](https://github.com/ScreamingFace/screamingface/pull/871). Docs approval/merge precedes a separate service implementation PR; this update implements no product code.

## Implementation

Owner authorized service implementation after the docs PR merged. Branch:
`OME-1152-analytics-service`; ledger:
`docs/work/2026-09-09-OME-1152-analytics-service.md`.
Mock tests do not complete the live PostHog smoke or production rollout acceptance.
