---
ticket: OME-943
stack: aigateway-ui
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# aigateway-ui-bff-error-log — one server-side log line per BFF error; LOG_LEVEL gets a reader

## Intent

A failing call from the console's BFF to aigateway's admin API (`request()` /
`uploadCacheSnapshot()` in `src/lib/aigateway/client.ts`) is turned into an `AdminApiError` and
handed to the page or server action — and nothing is written server-side, so the failure reaches
the browser and disappears. Separately, the chart renders `LOG_LEVEL` into the container and no
code reads it. This unit adds a minimal server-only structured logger that emits exactly one JSON
line per BFF error (method, path, `AdminErrorKind`, status, request id) and makes it the consumer of
`LOG_LEVEL`.

**Wire vs delete — WIRE.** The logger this ticket introduces is a real reader: BFF errors split
into `warn` (the gateway answered with a request-level refusal — forbidden, unauthenticated,
invalid, not_found, conflict) and `error` (the console cannot be served — unavailable,
unreachable, unknown). `LOG_LEVEL=error` therefore has an observable effect (silences expected
refusals), and the chart value already exists with the conventional default `info`. Deleting it
would mean re-adding it the first time anyone wants to quiet the 4xx noise.

## Planned changes

- `apps/aigateway-ui/src/lib/log.ts` (new, `server-only`): `log(level, msg, fields)` — one JSON
  line, level threshold from `process.env.LOG_LEVEL` (read per call; unknown/empty → `info`).
- `apps/aigateway-ui/src/lib/aigateway/client.ts`: both failure paths (`request()`,
  `uploadCacheSnapshot()`) report through one helper before throwing. Request id = incoming
  `x-request-id` (Envoy sets it), `null` when absent. Path logged WITHOUT its query string
  (`?q=` carries operator-typed search text). NEVER the upstream body, `detail`, or message.
- `apps/aigateway-ui/charts/aigateway-ui/values.yaml` + `templates/configmap.yaml` + chart
  README + app README: document `LOG_LEVEL` values and its consumer.

## Test plan

- `src/lib/log.test.ts`: threshold (debug/info/warn/error), default `info`, unknown value →
  `info`, one JSON line with level/time/msg/fields, routed to the console method for its level.
- `src/lib/aigateway/client.test.ts` (append-only — new describe block): a failing admin call
  produces exactly ONE structured line with path/kind/status/requestId; query string stripped;
  upstream body text (incl. a provider-ish secret) never appears in the line; unreachable logs at
  `error`, 4xx at `warn`; `LOG_LEVEL=error` suppresses the warn line; a success logs nothing;
  missing `x-request-id` → `requestId: null`; upload path logs too.

## Acceptance

- vitest: a failing admin call produces exactly one structured server log line.
- `run_gates.py aigateway-ui` green (npm ci, lint, lint:css, typecheck, build, test:ci).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `src/lib/aigateway/client-log.test.ts` (new file instead of
  appending to `client.test.ts`: that file's `headers()` stub answers every header name with the
  caller email, so request-id assertions there would be meaningless; it stays untouched).
  `client.ts`: one choke point `reportingFailure(method, path, call)` wraps `request()` and
  `uploadCacheSnapshot()`; the original bodies became `send()` / `sendSnapshot()` unchanged.
- **Commits:** see the PR for OME-943 — `feat(aigateway-ui): log one server-side line per BFF error and wire LOG_LEVEL`.
- **Gates:** `run_gates.py aigateway-ui` → ALL GATES GREEN (append-only check, npm ci, lint,
  lint:css, typecheck, build, test:ci — 258 tests). `verify_chart_wiring.py` 113/113.
- **Deviations:** request id is the incoming `x-request-id` (Envoy's), `null` when absent —
  not minted locally, since a locally generated id correlates with nothing. Only `AdminApiError`
  is logged; any other throw already reaches Next's error boundary, which logs it.
  Discovery (not fixed, out of scope): `baseUrl()` is evaluated inside `request()`'s fetch
  `try`, so a missing `AIGATEWAY_ADMIN_BASE_URL` surfaces as `unreachable`, not the intended
  `unavailable`.
