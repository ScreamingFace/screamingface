---
ticket: OME-1124
stack: screamingface
status: done
started: 2026-09-25
finished: 2026-09-29
---

# Local SDK analytics

## Intent

Implement the local SDK slice approved in conversation on 25 September, following
the OME-1124 spec/plan and OME-1152 wire contract. The owner confirmed anonymous
dev ingestion, PostHog receipt, Access configuration and edge limits. Colab bridge,
identity linking, website tracking and service changes remain separate work.

## Planned changes

- Add `_analytics/{ports,core,local,delivery,wiring,tracking,prompt}.py`, public
  `analytics.py`, and a shared `_core/engine_origin.py` classification helper.
- Wire `client.py`, `_default_client.py`, `_scoreboard/leaderboards.py`,
  `_runtime/cli.py` and package exports; reuse classification in the existing UI.
- Instrument public sync/async evaluation and submission boundaries once.
- Add behavior tests and SDK documentation; preserve prior tests.
- No PR or new Linear issue without owner confirmation.

## Test plan

- RED first: no ID/network/file creation before consent, consent precedence and
  revocation, stable installation IDs, concurrent persistence, process/fork sessions.
- Four-event schema, sync/async outcome parity, cancellation and error preservation,
  payload privacy, bounded queue/retries and consent recheck before dispatch.
- Run screamingface card gates, including notebook determinism and distribution.

## Acceptance

- Explicit local opt-in enables correctly classified evaluation/submission events.
- Unknown or invalid metadata drops telemetry without affecting product execution.
- Repeated processes share installation continuity; opt-out stops further dispatch.
- No Colab continuity or account identity claims in this slice.

## Source audit and resolved decision

Worktree created from freshly fetched origin/main at
`1c22a64a64403f64b2a86346e2153307f293a5a4`; HEAD and origin/main match.
No analytics implementation exists under the SDK sources.

The current SDK lacks an explicit BYOK/hosted usage-mode field. On 25 September
the owner confirmed the current product invariant: only local engines are BYOK;
remote engines are hosted. This resolves the mode question without an Engine
contract change or a manual user setting. Use the existing loopback/unspecified
address classification, sharing that logic between UI and analytics rather than
importing UI into analytics core. This mapping must be revisited if remote BYOK
becomes supported. Never export the endpoint URL in event properties.

## Outcome

- **Actual files:** planned SDK modules/integration, four new analytics test modules,
  an appended test-isolation fixture, README, owner clarification in spec/plan, and this ledger.
- **Commits:** none; awaiting the snapshot gate exception before commit.
- **Gates:** final full SDK tests: 1881 passed, 26 skipped, 95.72% coverage.
  Fifty focused analytics tests pass. Ruff check/format, pyright, deterministic
  notebook check, wheel/sdist build and distribution check pass.
  The normal gate runner stops on the additive JSON public-surface snapshot;
  its append-only checker cannot parse JSON. Owner approval was requested for
  that exact exception and remains pending. No skip flag was used.
- **Deviations:** owner clarified local/remote mode mapping; no remaining mode blocker.
  The public API snapshot adds only the `analytics` export and module entry (five
  added lines, zero removals). Existing API entries were checked for preservation;
  existing test bodies are unchanged. Changelog records the approved new API.
  Implementation is ready locally; no Linear issue, PR or deployment was created.


## Wisdom review

- Core depends on narrow consent/sink ports; adapters are composed in one process-local
  wiring module. No app internals are imported by production SDK code.
- Sync/async wrappers share operation construction, outcome mapping and consent checks.
  The outer context guard prevents duplicate module/client events and is PID-aware.
- No new dependency, database, product credential, durable event queue or service change.
- Tests cover concurrent first enable, bad state, symlinks, unwritable state, consent
  precedence, background delivery, retries, wire validation, outcomes and exception identity.
- Privacy resets invalidate sessions too, including when another process resets the
  shared ID, to avoid joining replacement identifiers through a reused session.
- Delivery is dev-only for this unit. Colab, production rollout and historical deletion
  process verification remain outside this implementation.

## Live dev verification — 25 September 2026

- Exercised the actual SDK public evaluation/submission validation-failure paths
  against `https://analytics.dev.screamingface.ai/v1/events`. Six events across
  two Python processes returned HTTP 202 with `upstream_accepted`, count 1 each.
  The observing HTTP wrapper delegated real network requests and verified no
  authorization, client auth or cookies. No paid model evaluation or scoreboard
  submission was performed; successful operation outcomes remain unit-tested.
- Confirmed all six events in the signed-in `screamingface-dev` PostHog project
  601604. Expanded the second process's evaluation_finished event and checked
  event ID, installation/session/operation IDs, sync/python/python_sdk, byok,
  failed outcome, under_1s, consent/schema version and SDK version.
- Test installation: `d0630e28-a00b-42a1-b04e-4e750f4dc631`.
  Sessions: `69d5b5e8-1397-43b5-9dcc-3ac4ac74caa5` and
  `e66d6df2-d668-483b-9260-bc68645f17a2`.
  A fresh process preserved consent/installation identity and created a fresh
  session. Unknown consent and subsequent disable both produced zero requests.
  Used a temporary preferences file, leaving the owner's real preferences intact.
- PostHog confirmed person-profile processing false and GeoIP disabled. It also
  displayed an IP property absent from SDK payloads; this appears to be the
  ingestion service's outbound IP, but that attribution was not independently
  verified. Service-side IP suppression/attribution remains a separate follow-up;
  do not claim no IP is stored by PostHog.
- MCP OAuth completed, but PostHog tools were unavailable in this running session;
  verification used the authenticated PostHog browser UI. No dashboard changes.

## Resume — 29 September 2026

Owner requested completion and a draft PR, explicitly not merging, after being
informed of the pending additive API snapshot approval. This authorizes the five
additive snapshot lines for the new analytics export; no existing snapshot values
were removed. Preserved original work in a named Git stash before fast-forwarding
the worktree to origin/main `6323ec88`; reapplied without conflicts.

The existing runner cannot parse the JSON snapshot. Ran its append-only check on
all existing Python tests separately and recursively verified all original JSON
values are preserved. Run the full gate runner with `--skip-append-only` only for
this documented snapshot exception; no gate code or existing test body changed.

Review found delivery retried HTTP 502 despite the gateway contract. Added six
status cases (two RED failures), then restricted status retries to 429/503. All
12 delivery tests pass. Colab remains intentionally off; future Colab integration
and deployed acceptance are separate from this local SDK draft.


## Final validation — 29 September 2026

All current-main gates pass: lint, formatting, types, complete SDK suite with the
95% coverage threshold (coverage report rounds to 96%), notebook determinism,
build and distribution validation. Existing Python append-only tests and JSON
value preservation were verified separately, as described above. No dependencies
added. The first buffered full run was interrupted during slow reconnect tests;
clean-main isolated reproduction passed in 96.16 seconds, matching the existing
90-second reconnect budget. The uninterrupted final gate run passed without test
skips or modified timeouts beyond the suite's existing selection.

Final review: no product payloads enter analytics, no secrets embedded, no new
runtime dependency, local preference failures leave automatic tracking off,
Colab disabled, dev-only destination documented. Existing public API entries
preserved. SDK integration changes remain in one package. Commit:
`feat(screamingface): add consented local SDK analytics`. Draft PR only, no merge.
