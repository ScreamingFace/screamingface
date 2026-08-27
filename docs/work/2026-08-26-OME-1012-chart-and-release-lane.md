---
ticket: OME-1012
stack: report-intake
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1012 — Helm chart, deployment wiring, and the release lane

## Intent

`apps/report-intake` runs, stores, files and retries, but nothing can deploy it: there is no
chart, and the `report-intake-v*` tag release-please already pushes builds nothing (CONTRIBUTING
says so out loud). This unit closes both — a chart that renders spec §7's two-hostname edge and
plan §2.4's environment surface, plus the lane that publishes the image and the chart from that
tag.

The chart is where two of the service's invariants stop being code and become deployment facts.
Plan §10 fixes both:

- **Two hostnames, not one.** A public intake hostname with no Cloudflare Access, an
  unconditional `RequestHeaderModifier` stripping `X-User-Email` and `CF-Connecting-IP`, and
  Turnstile required; an identity hostname with an Access application and a fail-closed
  `SecurityPolicy` whose `claimToHeaders` *sets* `X-User-Email`. The one-route alternative with
  `spec.jwt.optional: true` is a full identity bypass — the JWT filter is skipped for a
  token-less request, so `claimToHeaders` never runs and a client-supplied `X-User-Email`
  reaches the backend untouched.
- **The chart renders exactly `Settings`' environment surface.** `extra="ignore"` makes a name
  mismatch silent, and on `AUTH_MODE` that means a production pod serving with authentication
  disabled. `create_app`'s startup guard is the in-process half (`OME-1005`); the
  `verify_chart_wiring.py` assertion is the other, and it is what survives a future rename.

## Planned changes

- `apps/report-intake/charts/report-intake/` — `Chart.yaml`, `values.yaml`,
  `values-cloud.yaml`, `README.md`, and `templates/`: `_helpers.tpl`, `configmap.yaml`,
  `deployment.yaml`, `service.yaml`, `serviceaccount.yaml`, `job-migrate.yaml`,
  `httproute-public.yaml`, `httproute-identity.yaml`, `securitypolicy.yaml`,
  `networkpolicy.yaml`, `tests/test-connection.yaml`.
- `apps/report-intake/tests/unit/test_chart_environment.py` — the app-side half of the §2.4
  contract, run by this stack's own gates with no helm on the box.
- `.github/scripts/verify_chart_wiring.py` — a `report-intake` section: the rendered
  environment against `Settings`, the two-hostname topology, the refusals, the probe split,
  and the chart's image against the lane that publishes it.
- `.github/workflows/charts.yml` — the chart's paths in both filters, plus lint and the
  values-cloud render.
- `.github/workflows/release-report-intake.yml` — the lane the `report-intake-v*` tag triggers.
- `CONTRIBUTING.md` — the release row stops saying the lane does not exist.
- `apps/report-intake/README.md` — "what exists today" and a pointer to the chart.
- This ledger.

## Test plan

- Every `REPORT_INTAKE_*` name the chart's templates carry is a declared `Settings` field, and
  every `Settings` field appears in the templates — both directions, because a renamed field
  and a new unrendered field fail differently and both end in a pod running on a default.
- A bare `helm template` with default values succeeds and renders no HTTPRoute, no
  SecurityPolicy and no NetworkPolicy.
- `--set anonymous.enabled=true` with `turnstile.enabled=false` is REFUSED, and the refusal
  says what it is protecting.
- `authMode=mesh_or_turnstile` without `allowedNetworks`, and without `turnstile.enabled`, are
  each refused at render — the two conditions `create_app` refuses at boot.
- The public route strips `X-User-Email` and `CF-Connecting-IP`; the identity route's
  `SecurityPolicy` targets it by name, carries an audience, and declares no `jwt.optional`.
- Liveness and readiness name DIFFERENT endpoints (spec §10).
- The rendered `FORWARDED_ALLOW_IPS` does not overlap the rendered
  `REPORT_INTAKE_ALLOWED_NETWORKS` — the render-time half of `_check_forwarded_allow_ips`.
- The chart's image repository IS the one `release-report-intake.yml` publishes.

## Acceptance

- `helm lint` and `helm template` pass for `values.yaml` and for `values-cloud.yaml` with its
  install-time values supplied.
- `verify_chart_wiring.py` passes, including the new `report-intake` section.
- A `report-intake-v*` tag builds and publishes an image and a chart.
- `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` green in
  `apps/report-intake`.

## Outcome

- **Actual files:** as planned. Chart at `apps/report-intake/charts/report-intake/`
  (`Chart.yaml`, `values.yaml`, `values-cloud.yaml`, `README.md`, and eleven templates),
  `apps/report-intake/tests/unit/test_chart_environment.py`,
  `.github/workflows/release-report-intake.yml`, plus edits to
  `.github/scripts/verify_chart_wiring.py`, `.github/workflows/charts.yml`, `CONTRIBUTING.md`
  and `apps/report-intake/README.md`. No `docs/tasks/` mirror and no Linear change — the
  orchestrator owns both.
- **Gates:** `uv run .claude/scripts/run_gates.py report-intake` — ALL GATES GREEN.
  `pytest` 417 passed, coverage 99.61% (floor 80); `ruff check` clean; `ruff format --check`
  81 files already formatted; `pyright` 0 errors, 0 warnings, 0 informations.
  `verify_chart_wiring.py` 72/72 (was 45/45). `helm lint` 5 charts, 0 failed.
- **The chart's guards were verified by breaking them, not by reading them.** Eleven negative
  controls, each reverted after: a number-shaped string (`deliveryTimeoutS: 3s`), a renamed
  ConfigMap key, a `FORWARDED_ALLOW_IPS` overlapping `allowedNetworks`, `jwt.optional: true`
  on the SecurityPolicy, the public route no longer stripping `X-User-Email`, a dropped
  `FORWARDED_ALLOW_IPS`, the Turnstile secret inlined as a literal, readiness re-pointed at
  `/healthz`, a renamed image repository, and both directions of the app-side name equality.
  Every one produced a named FAIL rather than a traceback — the first pass did not, and the
  key reads were made tolerant so a renamed key reports the drift instead of aborting the
  script twenty lines later.
- **The rendered cloud ConfigMap was fed through the app's own parser and all three startup
  guards** (`Settings()`, `_reject_unknown_environment`, `_check_forwarded_allow_ips`,
  `_check_auth_mode`) and passed. Not committed as a check — it needs helm and the app in one
  process, and plan §2.4 froze the two enforcement mechanisms deliberately — but its cheap half
  is: the verifier now derives which fields are `int`/`float` and which values `AuthMode`
  declares straight from `config.py`'s AST, so a value the app cannot parse fails the PR
  instead of the pod.
- **Deviations, three, all recorded in the chart:**
  1. **`networkPolicy.enabled` stays `false` in `values-cloud.yaml` as well as `values.yaml`.**
     Plan §10 only requires the default off. Enabling it needs the `app.kubernetes.io/name` of
     the mesh gateway's data plane, which is cluster-specific and which I could not establish
     to the confidence bar — and the template refuses an empty peer set rather than emitting an
     allow-all, so a guessed value would either be wrong or fail the render. Unlike aigateway's,
     this policy is hardening rather than the authentication boundary (the in-process peer check
     against `allowedNetworks` is), so off is a defensible default rather than an opening. The
     verifier exercises it with a placeholder peer and asserts both the pairing and the refusal.
  2. **Four render-refusal guards beyond the one plan §10 names.** The plan names
     `anonymous.enabled` without `turnstile.enabled`. The chart also refuses
     `mesh_or_turnstile` without `allowedNetworks` or without `turnstile.enabled` (mirroring
     `main._check_auth_mode`, which otherwise fires after the pod is scheduled, into a log
     nobody watches during an upgrade), an edge in front of an `authMode: disabled` pod, and
     `forwardedAllowIps: "*"`.
  3. **The guard is included from every template that can `fail` or `required`, not once.** Helm
     aborts at the first template that raises and the walk order is not the chart's to control:
     included only from the ConfigMap, `--set anonymous.enabled=true` aborted inside the public
     route's `required` on `gateway.parentRef.name` — true, and the wrong sentence to hand
     someone who has just turned on an unauthenticated write.
- **`values-cloud.yaml` names two hostnames this repo has not provisioned** —
  `reports.screamingface.ai` and `reports-internal.screamingface.ai`, in the shape
  `screamingface-engine`'s `values-cloud.yaml` uses for `url4.screamingface.ai`. They are
  install-time overrides, but they are the one thing in this unit asserted by nothing.
