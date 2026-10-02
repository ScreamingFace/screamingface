---
ticket: OME-1250
stack: aigateway (+ screamingface-engine, screamingface)
status: blocked   # STOP: design requires a breaking wire change and a schema migration
started: 2026-10-01
finished:
---

# connection-status-outcome-driven — `connected` must mean "calls will work right now"

## Intent

Owner decision (2026-10-01, Linear comment): **outcome-driven status**. Derive a provider's
reported status from recent dispatch outcomes, with a distinct state for "authenticates but
cannot serve" (402 / quota / out of credits) vs "credential is bad" (401). No upstream probe on
listing. The 401-only rule for marking a stored credential unusable (D9,
`plugins/openrouter_provider/plugin.py:279`) is preserved. Lands on the successor listing
`GET /v1/provider-access` (OME-1244/1245), verified live on `origin/main` `ba1545d81`
(`routes/provider_access_availability.py`; Engine reads it via
`connections/provider_access_availability.py`).

## Findings that gate the design (verified on `ba1545d81`)

1. **Every consumer decodes `status` as a closed family and hard-fails on an unknown value.**
   - aigateway: `AvailabilityStatus` Literal (`core/provider_access/types.py:80`) is the response
     schema (`ProviderAccessAvailabilityRow`, `extra="forbid"`; INVARIANT "the closed status
     family IS the schema").
   - Engine: `decode_provider_access` raises `ConnectionBadResponse` (502 for the WHOLE listing)
     on any status outside `ConnectionStatus` (`connections/port.py:15`).
   - SDK: `Connection.__post_init__` raises `ValueError("unknown connection status …")`
     (`packages/screamingface/src/screamingface/connections.py:24,62`); the widget `match` uses
     `assert_never`.
   → An additive enum value emitted by the gateway breaks every already-deployed Engine and
   every already-installed SDK. It is additive in the schema but **breaking on the wire**.
2. **D17 locks rows to `provider` + `status` only**, so a side-channel `reason` field on the row
   is itself a spec change, and the Engine ignores additive row fields (so it would not reach
   the SDK without further Engine + SDK changes anyway).
3. **The existing `status` column cannot carry the new state.** `OAuthConnection.status` gates
   dispatch; writing a degraded value there would stop the credential being tried, so it could
   never self-heal on success, and it would erode the D9 rule. Outcome history therefore needs
   its own storage: DB columns (Tortoise migration) or in-memory (per-replica, lost on
   restart; aigateway `replicaCount: 1` today in `values.yaml` / `values-prod.yaml`).
4. Two backings answer op 6 (profile-backed legacy precedence + connection-backed overlay for
   migrated pairs, `connection_backed.py:94`); the outcome overlay must apply to both.

## Proposed design (pending owner choice of rollout option)

- New wire state: **`unavailable`** ("authenticates, cannot serve": 402/403-quota/429-quota),
  `error` stays "credential rejected" (401). `connected` = active AND no live degraded outcome.
- Recording: at the shared dispatch-failure boundary (NOT `routes/chat_dispatch.py`; hook at
  the plugin's status classifier caller), 402/quota → `degraded_until = now + window`; any 2xx
  dispatch clears it (reset-on-success). Window: 15 min, sliding on each new 402.
- 5xx/408/transient 429 do NOT degrade (would flap on provider outages; acceptance only demands
  that a provider *rejecting every call* for a credential reason stops reading `connected`).
- Concurrency: last-writer-wins single-row update (`UPDATE … SET degraded_until`), no lock;
  success-clear vs failure-set races resolve to whichever lands last, self-correcting on the
  next call.

## Rollout options (STOP — owner decides)

- **A. Staged additive value (recommended).** PR1: Engine + SDK learn `unavailable` (SDK
  release, Engine deploy). PR2 (after PR1 deployed + SDK published): gateway emits it, plus
  the outcome store. Wire-safe; ~2 releases; old SDKs still break once PR2 ships unless they
  upgrade → also add a tolerant "unknown → unavailable" decoder in PR1 for future widening.
- **B. Single PR, coordinated deploy.** All three stacks in one PR; breaks pinned/old SDKs and
  any Engine deployed before the gateway. Fastest, breaking.
- **C. No new state on the wire.** Keep the closed family; map degraded → `error` and move
  401 → `needs_reauth`. Non-breaking for decoders but changes existing semantics and existing
  tests (prior-test change); needs owner sign-off on re-meaning `needs_reauth`.

Storage sub-choice: **S1 DB columns** (`degraded_until`, `degraded_reason` on
`oauth_connections` + profile equivalent; Tortoise migration; correct across replicas and
restarts — recommended) vs **S2 in-memory TTL map** (no migration; wrong under >1 replica and
forgets on restart).

## Planned changes (under A + S1, PR2)

- `apps/aigateway/src/aigateway/core/provider_access/types.py` — widen `AvailabilityStatus`.
- `apps/aigateway/src/aigateway/core/oauth/models/oauth_connection.py` + migration.
- `core/provider_access/connection_authority.py`, `profile_backed.py` — overlay outcome.
- new `core/provider_access/outcomes.py` — record/clear port + Tortoise adapter.
- Engine `connections/port.py`, SDK `connections.py` + `_ui/connection_view.py` (PR1).

## Test plan

- 402 dispatch → listing `unavailable`; 401 → `error` (D9 unchanged); success after 402 →
  `connected`; window expiry → `connected`; 5xx never degrades; listing makes no upstream call.

## Acceptance

- As the ticket: rejecting credential never reports `connected`; 402 distinguishable from a
  revoked key; healthy connection unaffected; listing cost unchanged (one DB read).

## Outcome

- **Actual files:** this ledger only (STOP after ledger per the run instructions).
- **Commits:** ledger commit on the branch, not pushed.
- **Gates:** not run (no code).
- **Deviations:** stopped before RED — design needs a breaking wire change and a migration.

## Owner decision 2026-10-02 and second STOP

Owner chose rollout A + DB columns (`degraded_until`, `degraded_reason`) + the proposed rule.
PR1 was to make decoding lenient for unknown future values. That contradicts two prior tests,
so the run stops again before RED (append-only rule):

- `apps/screamingface-engine/tests/unit/test_connections_provider_access_availability.py::
  test_a_malformed_availability_body_is_a_bad_gateway_response[legacy-profile-state-vocabulary]`
  — `{"provider": "openrouter", "status": "authenticated"}` must raise `ConnectionBadResponse`
  (502). INVARIANT there: "a malformed body is refused, never guessed".
- `packages/screamingface/tests/test_connections.py::
  test_connection_catalog_rejects_malformed_payloads` (payload `_row(status="unknown")`) —
  must raise `ProviderConnectionError(code="invalid_connection_response")`.

Accepting the new `unavailable` value alone needs no prior-test change.
