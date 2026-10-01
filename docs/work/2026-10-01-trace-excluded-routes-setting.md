---
ticket: OME-1453
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# trace-excluded-routes-setting — stop reusing OTEL_PYTHON_EXCLUDED_URLS for route matching

## Intent

`OME-1217` made aigateway's probe-span exclusion read `OTEL_PYTHON_EXCLUDED_URLS` but match it
against the resolved ROUTE TEMPLATE, not the URL. Operators set that standard variable
cluster-wide with unanchored values for the stock OTel instrumentors (e.g. `healthz,models`);
here such a value would silently drop real gateway routes like `/v1/models`. Latent (nothing in
the repo sets it), but a trap.

## Decision (picked in this ledger, per the ticket)

Option 1 — **rename** to a gateway-specific setting `AIGW_TRACE_EXCLUDED_ROUTES`: a
comma-separated list of anchored regexes over route templates, default `^/healthz$`. Read through
`Settings` (`config.py`, pydantic-settings — the mechanism every other `AIGW_*` setting uses) and
handed to `CallIdMiddleware` by `create_app`. `OTEL_PYTHON_EXCLUDED_URLS` is no longer honoured.

- Matching stays `re.search` (unchanged semantics; prior tests pin it). "Anchored" is the
  documented convention for entries — the default is anchored, and the AIDEV-NOTE says why an
  unanchored entry is dangerous against route templates. No startup refusal (that was option 2).
- `span_exclusion.py` stays stdlib + `opentelemetry-sdk` only (liftable for `OME-1218`): it gains
  `SpanExclusion.from_setting(raw)`; `from_env(env)` delegates to it via `ENV_VAR`.
- Chart: does not expose the variable (only via `extraEnv`), so no chart README change.
- **Minor, noted per ticket:** `POST`/`HEAD /healthz` (405) spans are dropped too, because they
  resolve to the probe route template. Harmless — a 405 on the probe route is not a signal an
  operator needs as a root span. Not changed.

## Planned changes

- `apps/aigateway/src/aigateway/span_exclusion.py` — `ENV_VAR` → `AIGW_TRACE_EXCLUDED_ROUTES`;
  `from_setting`; docstring + AIDEV-NOTE.
- `apps/aigateway/src/aigateway/config.py` — `trace_excluded_routes` field.
- `apps/aigateway/src/aigateway/main.py` — pass the exclusion from settings.
- `apps/aigateway/tests/unit/test_trace_excluded_routes_setting.py` (new).
- `docs/tasks/2026-10-01-OME-1453-trace-excluded-routes.md` (mirror).

## Test plan

- `ENV_VAR == "AIGW_TRACE_EXCLUDED_ROUTES"`.
- An unanchored `OTEL_PYTHON_EXCLUDED_URLS=healthz,models` in the environment does NOT drop
  `GET /v1/models` through the real `create_app`; `/healthz` is still dropped by the default.
- `Settings` reads `AIGW_TRACE_EXCLUDED_ROUTES` (unset → `None`); `create_app` honours it
  (a setting naming `^/v1/models$` drops that route and no longer drops `/healthz`).
- `from_setting`: `None` → default; blank → nothing; invalid → default + warning.
- Prior `test_probe_span_exclusion.py` stays green, unmodified.

## Acceptance

- Gateway ignores `OTEL_PYTHON_EXCLUDED_URLS`; `AIGW_TRACE_EXCLUDED_ROUTES` governs exclusion.
- `run_gates.py aigateway` green; no prior test edited.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `span_exclusion.py`, `config.py`, `main.py`, new
  `tests/unit/test_trace_excluded_routes_setting.py` (12 tests), this ledger, the mirror.
  `tests/unit/test_probe_span_exclusion.py` untouched and green (it references `ENV_VAR`
  symbolically, so the rename needed no edit there).
- **Commits:** `fix(aigateway): read probe-span exclusion from AIGW_TRACE_EXCLUDED_ROUTES` (sha in
  the PR).
- **Gates:** `run_gates.py aigateway` — ALL GATES GREEN (append-only check, ruff, ruff format,
  pyright, check_no_enterprise, pytest 5069 passed / 89 skipped, coverage 93% ≥ 80%;
  `span_exclusion.py` 96%).
- **Deviations:** none from the plan. Ticket board not moved to In Progress (the dispatching
  session allowed only the In Review + PR-link Linear change). Chart untouched: it does not
  expose the variable.
