---
id: OME-1250
linear_url: https://linear.app/openmined/issue/OME-1250/connection-status-can-report-connected-while-every-provider-call-fails
status: in_progress
type: bug
priority: medium
labels: [aigateway, agentic, task, bug]
parent: OME-1317
created: 2026-09-21
closed:
---

# Report confirmed credential failures through provider availability

Outcome-driven credential evidence prevents a migrated OpenRouter API-key Connection from
continuing to report `connected` after a confirmed insufficient-credit response.

## Publication scope

- A classified `401 auth_required` projects the existing `needs_reauth` value and refuses later
  provider dispatch until credential replacement.
- A classified `402 insufficient_credits` projects the existing `error` value without changing
  Connection lifecycle or blocking a recovery dispatch.
- A successfully converted provider response restores `connected`.
- Blob identity, credential revision and dispatch sequence prevent stale completions from changing
  a replacement credential or superseding a newer informative result.
- Availability remains a local metadata read, with no upstream probe or credential decryption.
- Operational-store failures return sanitized retryable `503` responses, including model admission;
  completion-persistence failures do not replace an already determined provider response.
- PostgreSQL protects rolling overlap with older writers. SQLite schema downgrade preserves indexes
  and pair uniqueness; binary rollback without downgrade retains the documented stale-outcome risk.

The optional `unavailable` consumer integration was reverted before publication. The public status
family is unchanged and this change does not require an Engine or SDK enum update.

## Boundaries

Observation is limited to non-streaming dispatch through a migrated pair's effective API-key
Connection when its provider declares an outcome classifier. OAuth, streaming, legacy Profile and
unmarked native paths retain their existing behavior. `429`, `5xx`, transport and local conversion
failures remain neutral; provider and gateway/engine service-health projection is separate remaining
work. This publication does not close the wider outage acceptance of the issue.

The current main selector-refusal and terminal dispatch-error logging contracts are preserved.
The two existing fixture-body changes are explicitly owner-approved; the migration 0012 prior test
remains unchanged.

Spec: `docs/spec/2026-09-30-degraded-connection-status.md`.
Plan: `docs/plan/2026-09-30-degraded-connection-status.md`.
Ledger: `docs/work/2026-09-30-degraded-connection-status.md`.
