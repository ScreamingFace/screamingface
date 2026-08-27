---
ticket: OME-1011
stack: report-intake
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1011 — Bind caller identity from the mesh and gate anonymous callers

## Intent

`apps/report-intake` accepts a report from anyone who can reach the port and records
`caller_email=None` unconditionally. Spec §7 admits **two** caller classes at the same
endpoint and treats them differently: a **mesh-verified** caller, whose address Envoy injected
after re-verifying the Cloudflare Access assertion, skips the bot gate because identity already
answers the question the gate asks; an **anonymous** caller must present a valid Cloudflare
Turnstile token (`403` without one) and lives inside a rate limit (`429`). This item builds both
sides, plus the loopback-only posture that makes `auth_mode=disabled` safe to run locally, plus
CORS so the browser clients spec §2.1 calls first-class can actually post.

This is the repo's first unauthenticated write that reaches human eyes, so the three plan §9
corrections are the load-bearing part, not the happy path:

- **the probes are exempt from the local-only middleware, unconditionally** — kubelet dials the
  Pod IP, so gating `/healthz` is a CrashLoopBackOff and breaks the CI image smoke test;
- **the rate-limit key must not be attacker-controlled** — `CF-Connecting-IP` is trusted only on
  an explicit opt-in and only from a mesh peer, and key-table overflow **refuses new keys as
  throttled** rather than evicting old ones, so filling the table fails closed;
- **the `client` fixture moves to a loopback peer and a loopback base URL** in the same change,
  or introducing the middleware turns every route test red at once.

## Planned changes

New, under `apps/report-intake/src/report_intake/`:

- `identity/__init__.py`
- `identity/mesh_identity.py` — the **one** module naming `X-User-Email`; peer check first.
- `identity/rate_limit.py` — token bucket keyed on the verified peer; the `CF-Connecting-IP`
  opt-in; refuse-new-as-throttled on overflow.
- `identity/turnstile.py` — the bot gate: the token header, the `TurnstileVerifier` port, and
  the httpx adapter that calls siteverify.
- `identity/gate.py` — `admit(request)`: mesh identity, else rate limit, else Turnstile.
- `core/local_only.py` — loopback-only middleware for `auth_mode=disabled`, probes exempt.

Edited:

- `config.py` — plan §2.4's remaining names: `auth_mode`, `cors_origins`,
  `trust_client_ip_header`, `turnstile_secret`, `turnstile_verify_url`, `turnstile_timeout_s`,
  `anon_rate_limit`, `anon_rate_window_s`, `anon_rate_max_keys`, `anon_rate_burst`.
- `core/problem_catalogue.py` — `403` joins `PROBLEM_CATALOGUE`; `bot_gate_required()` (403),
  `bot_gate_unverifiable()` (503), `loopback_only()` (403).
- `routes/reports.py` — one added first line: the gate supplies `caller_email`.
- `main.py` (as a diff) — a third startup guard for `mesh_or_turnstile`, the rate limiter, the
  verifier, CORS and the local-only middleware, and closing the verifier in `_lifespan`.
- `pyproject.toml` + `uv.lock` — `httpx` moves from the dev group to a runtime dependency,
  because siteverify is an outbound call the deployed pod makes.
- `README.md` — the identity section and the environment table.
- `tests/conftest.py` — the loopback `client` fixture, plus a `mesh_client`.

## Test plan

Spec §10's identity list, behaviour-named:

- a forged `X-User-Email` from outside the mesh is not honoured; the mesh-injected one from
  inside is; an IPv4-mapped IPv6 peer resolves against an IPv4 network.
- an anonymous request with no Turnstile token is `403` and stores nothing; with a valid token
  it is accepted; a mesh-verified request is accepted with no token at all.
- siteverify unreachable is `503`, **not** `403`; a secret-side error code is `503` too, because
  fetching a fresh token cannot fix our own secret.
- rotating `CF-Connecting-IP` does not reset the budget; filling the key table throttles the new
  key rather than releasing an old one's; a full bucket may be pruned and a throttled one may not.
- `/healthz` and `/readyz` answer `200`/`503` from a non-loopback caller in every auth posture.
- `mesh_or_turnstile` without `allowed_networks`, or without a Turnstile secret, refuses to boot.
- the catalogue holds exactly `{400, 403, 413, 422, 429, 503}`; no problem detail ever echoes the
  token or the address.
- `X-User-Email` is named in **exactly** one module (the containment test tightens from `<=`).

## Acceptance

- Both caller classes work end to end through the real app; the mesh address reaches
  `Submission.caller_email` and a forged one does not.
- Every refusal is RFC 9457 from a catalogued constructor, and `403` vs `503` splits the two
  things a client must do differently.
- `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `apps/report-intake/docs/complexity-baseline.md` (refreshed,
  as every item on this app does) and `tests/unit/test_local_only.py` / `test_mesh_identity.py` /
  `test_rate_limit.py` / `test_turnstile.py` / `test_auth_gate.py` / `test_cors.py`.
- **Commits:** one on `OME-1002-report-intake-service`; sha recorded by the orchestrator.
- **Gates:** `uv run .claude/scripts/run_gates.py report-intake` — ALL GATES GREEN.
  412 passed, ruff check clean, ruff format clean, pyright 0 errors, coverage 99.61 %
  (floor 80 %). The identity package is at 100 % line coverage, `main.py` at 100 %.
- **Deviations:**
  - **`httpx` moved from the dev group to a runtime dependency.** Siteverify is a real outbound
    call the deployed pod makes, and the alternative — `urllib.request` in a thread — is a
    worse implementation of the same dependency. `uv lock --check` is clean.
  - **`turnstile_secret` is a `SecretStr`, not a `str`.** The plan names the environment variable
    and not the type; `apps/aigateway` uses `SecretStr` for every credential and a new secret
    field taking the house pattern seemed strictly better than a rule about never printing
    `Settings`. A test asserts the value does not survive a `repr`.
  - **A third `403` constructor, `loopback_only()`.** Plan §2.6 names two (`bot_gate_required`,
    `bot_gate_unverifiable`) and the catalogue stays exactly `{400, 403, 413, 422, 429, 503}`, so
    the client-facing contract is unchanged. The loopback guard needed a catalogued status rather
    than an ad-hoc one, and its refusal is unreachable in any deployment an SDK talks to —
    `disabled` mode is loopback-only by construction.
  - **`HttpTurnstileVerifier` takes an optional `transport`.** httpx's own injection point, so the
    adapter's request building and response decoding are what the tests drive rather than a stub
    that agrees with them by construction. Production passes nothing.
  - **`create_app` grew 20 → 23 statements** (threshold 26). The middleware stack went into
    `_install_middleware` to keep it there; the baseline's tightening roadmap is updated from
    "26 → 22 is reachable" to "26 → 24", with the reason splitting the composition root further
    is the wrong trade.

### Worth knowing for `OME-1012`

- **The chart's `REPORT_INTAKE_*` set is now complete**: plan §2.4's list is exactly
  `Settings.model_fields`, and `create_app` refuses to start on any other `REPORT_INTAKE_*` name.
  `TURNSTILE_SITE_KEY` is asserted **absent** by a test, so rendering it would be a boot failure.
  `test_the_environment_surface_is_exactly_the_one_the_plan_froze` pins the 19 names from the app
  side; `verify_chart_wiring.py` is the other half and has something exact to compare against.
- **`auth_mode` defaults to `disabled`, which is loopback-only.** A chart that renders no
  `REPORT_INTAKE_AUTH_MODE` produces a pod that 403s every caller except the probes — visible
  immediately rather than silently open, but it does mean the value is not optional in
  `values-cloud.yaml`.
- **`mesh_or_turnstile` refuses to boot without BOTH `allowed_networks` and `turnstile_secret`.**
  The chart's own render-refusal guard and this one must agree, or the pod fails after the chart
  said yes.
- **Liveness and readiness are exempt from the loopback guard**, so a probe works in every
  posture — which is what keeps the CI image job (a non-loopback peer through a published port)
  green and is plan §11 conflict 9.
- **`FORWARDED_ALLOW_IPS` must stay disjoint from `REPORT_INTAKE_ALLOWED_NETWORKS`** — unchanged
  from `OME-1005`, but now load-bearing for the rate-limit key as well as for identity.
