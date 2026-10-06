---
ticket: OME-1495
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-10-06
finished: 2026-10-06
---

# engine-app-otlp-env — give the engine App Deployment the OTLP env so `url4.accept` exports

## Intent

Bug, verified on dev 2026-10-06. `OME-1218` (PR #1216) made the engine App emit a control-plane
`url4.accept` server span and forward ITS span id to the run, so `url4.run` is its child. Dev runs
a revision that contains #1216, yet SigNoz shows 0 `url4.accept` spans in 14 days, and since
10-02 `url4.run` carries a parentSpanID that does not exist in SigNoz.

Root cause (chart): the OTLP settings reach the RUNNER POOL only. `configmap-runner-env.yaml` holds
the `OTEL_*` keys and `deployment-runner.yaml` attaches the tracing Secret; the App container's
`envFrom` (`deployment.yaml`) has the app ConfigMap + artifact secrets and no `OTEL_*` key at all.
In engine src, the App builds its sink with `control_plane_span_sink(os.environ)` =
`tracing.loader.load_span_sink`, which returns `None` unless `OTEL_EXPORTER_OTLP_ENDPOINT` (or the
traces-specific variable) is set — so on dev the App has no sink, opens no accept span, and
forwards the CALLER's inbound traceparent, whose parent span id the run then adopts (the
`OME-1218` relay change, D6). That caller span is never exported: the dangling parent.

Env is the only missing piece: `sink_from_env` reads `OTEL_SERVICE_NAME`; the OTel
`OTLPSpanExporter` reads `OTEL_EXPORTER_OTLP_HEADERS` from the process env itself; the endpoint is
resolved from the same mapping. No code change needed.

## Design

- **D1 — one source for the OTLP keys.** Move the `OTEL_*` block (incl. the endpoint-required
  `fail`) out of `configmap-runner-env.yaml` into a `screamingface-engine.tracingEnv` helper in
  `_helpers.tpl`; include it in BOTH ConfigMaps. A one-sided edit becomes impossible, the same
  "one value, two renderings" invariant `URL4_CLOUD_LOG_LEVEL` and the artifact store carry.
  Rejected: `envFrom` of the runner-env ConfigMap on the App — it would inject runner-only keys
  (e.g. `AIGATEWAY_*`, the runner's own `URL4_CLOUD_*` names) into the App.
- **D2 — the credential.** App container's `envFrom` gains the tracing `secretRef` under the same
  `screamingface-engine.tracingHasSecret` condition the pool uses — never reference a Secret that
  will not exist.
- **D3 — service name: unchanged, shared.** `OME-1218` expected the App to use the same loader
  and the same default (`screamingface-engine`); `tracing.serviceName` (when set) applies to both.
  The spans are distinguished by name/kind (`url4.accept` server vs `url4.run`). No new values knob.
- **D4 — stale doc.** `values.yaml` says tracing "Applies to the RUNNER POOL only. The control
  plane publishes no spans" — false since `OME-1218`; corrected.

## Planned changes

- `apps/screamingface-engine/deploy/helm/templates/_helpers.tpl` — new `tracingEnv` helper
- `apps/screamingface-engine/deploy/helm/templates/configmap-runner-env.yaml` — include it
- `apps/screamingface-engine/deploy/helm/templates/configmap.yaml` — include it
- `apps/screamingface-engine/deploy/helm/templates/deployment.yaml` — tracing `secretRef`
- `apps/screamingface-engine/deploy/helm/values.yaml` — comment fix (D4)
- new `apps/screamingface-engine/tests/unit/test_chart_render_app_tracing.py`

## Test plan

- With tracing enabled (default): the App ConfigMap carries `OTEL_EXPORTER_OTLP_ENDPOINT` +
  `OTEL_RESOURCE_ATTRIBUTES`, and the App container reads that ConfigMap via `envFrom`.
- App and runner-env OTLP keys are identical (one source), incl. a set `serviceName`.
- Headers set → App `envFrom` has the chart-created `-tracing` secretRef; credential not a literal
  in the App Deployment or App ConfigMap. `existingSecret` → that name referenced.
- Enabled with no credential → no tracing secretRef on the App.
- Disabled → no `OTEL_*` key in the App ConfigMap and no tracing secretRef, even with headers set.
- Enabled with empty endpoint (schema skipped) still refuses (existing tests; helper keeps `fail`).

## Acceptance

- Rendered App Deployment carries the OTLP env (+ secretRef when a credential exists) exactly when
  `tracing.enabled`; all prior chart tests unmodified and green; `run_gates.py
  screamingface-engine` green.
- Live (post-merge, post-deploy, NOT verifiable here): SigNoz shows `url4.accept` spans from dev
  and `url4.run`'s parent resolves to one.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `_helpers.tpl` (new `tracingEnv` helper; `tracingHasSecret`
  doc now names the App too), `configmap-runner-env.yaml` (block replaced by the include —
  rendered data byte-identical to `origin/main` with tracing on and off, comments aside),
  `configmap.yaml` (include), `deployment.yaml` (tracing `secretRef` under `tracingHasSecret`),
  `values.yaml` (D4 comment fix), new `tests/unit/test_chart_render_app_tracing.py` (7 tests).
- **Commits:** `fix(engine): give the App Deployment the OTLP env so url4.accept exports` (see PR).
- **Gates:** `run_gates.py screamingface-engine` — ALL GATES GREEN (append-only vs HEAD, ruff
  check, ruff format, pyright, check_layering.py, pytest + cov >= 80; 4563 passed, 77 skipped).
  Also `helm lint` 0 failed; `.github/scripts/verify_chart_wiring.py` 117/117.
- **Engine src confirmed (no code change needed):** App = `create_app_from_env` →
  `control_plane_span_sink(os.environ)` (= `tracing.loader.load_span_sink`), on only when an
  OTLP endpoint var is non-blank; `sink_from_env` reads `OTEL_SERVICE_NAME`; the OTel HTTP
  exporter reads `OTEL_EXPORTER_OTLP_HEADERS` from `os.environ` (`_resolve_headers`).
- **Deviations:**
  - Service name NOT split: the App reports the same `service.name` as the pool
    (`tracing.serviceName` or the code default `screamingface-engine`) — what OME-1218's shared
    loader already does; no new values knob. Spans differ by name/kind.
  - `values.schema.json`'s endpoint-required description still says "runner pool" — left as is
    (accurate, just incomplete; out of scope).
  - Live verification impossible pre-merge (previews disabled; dev deploys via ArgoCD from the
    infra repo). Post-deploy SigNoz check is in the PR body; NOT verified here.
