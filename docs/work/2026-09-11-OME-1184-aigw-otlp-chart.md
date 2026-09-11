---
ticket: OME-1184
stack: aigateway
status: done
started: 2026-09-11
finished: 2026-09-11
---

# OME-1184 — Ship the OTLP endpoint to aigateway through its chart

## Intent

`OME-1132` made aigateway emit spans and left it inert: nothing sets `OTEL_EXPORTER_OTLP_ENDPOINT`,
and the chart had no way to. This is the deployment half, mirroring `OME-1131`'s engine shape.

With this merged and four values set in the GitOps repo, a run produces a connected two-service
trace in SigNoz — which is Phase 2's whole acceptance.

## What is already known, so nothing here is guesswork

Resolved from SigNoz's own logs during `OME-1131`/`OME-1132` follow-up:

- **The collector is in-cluster**: `signoz-otel-collector` in namespace `signoz`, cluster
  `aks-dev`, listening OTLP/HTTP on `[::]:4318` (read from its own startup log, not assumed).
  So `http://signoz-otel-collector.signoz.svc.cluster.local:4318`, **no credential**.
- **Deployment is ArgoCD**, not GitHub Actions. `screamingface-sf-aigw` (dev) already tracks
  chart revision `79a949e1` — `OME-1132`'s merge — with values from
  `$values/kubernetes/apps/sf-aigw/values/dev.yaml` in `OpenMined/infrastructure`.
- **⚠️ `https://signoz.pulse.dev.openmined.org/v1/traces` answers `200 text/html`** — the UI's
  SPA catch-all. OTel treats any 2xx as success, so that hostname silently discards every span
  while the exporter reports healthy. Warned at the config site, as in the engine chart.

## Design decisions

**D1 — the assertion lives in a pytest render test.** The issue asked whether it should live
there or in `verify_chart_wiring.py`.

`verify_chart_wiring.py` is rejected: it exists for the **pair** of charts (the console must
point at the Service the gateway renders; the gateway must admit the label the console's Pods
carry). Single-chart tracing config is not a cross-chart concern, and putting it there would
blur the one file whose whole point is that it owns what neither app's lane owns.

A pytest render test also matches the engine's, so one shape covers both charts.

**Correction — an earlier draft of this unit also added `azure/setup-helm@v5` to the test job,
on the false premise that the chart tests would otherwise skip in CI.** They do not:
GitHub's `ubuntu-latest` image ships helm, and the engine's equivalent tests have been passing
on the merge gate all along (verified in the run log — zero `helm is not installed` skips).
The step was removed and `OME-1189`, filed on that premise, cancelled. What remains true and
is recorded in the test file: helm comes from the RUNNER IMAGE rather than anything this repo
pins, so if a future image drops it these tests would start skipping silently.

`verify_chart_wiring.py` was the alternative and is rejected: it exists for the **pair** of
charts (the console must point at the Service the gateway renders; the gateway must admit the
label the console's Pods carry). Single-chart tracing config is not a cross-chart concern, and
putting it there would blur the one file whose whole point is that it owns what neither app's
lane owns.

**D2 — the shape is `OME-1131`'s, copied deliberately.** Same values keys, same ConfigMap /
Secret split, same fail-the-render rule, same optional credential. Two charts that configure the
same feature two different ways is a tax paid at every future edit, and the engine's shape was
reviewed and merged hours ago.

**D3 — NO `lookup` reuse in the Secret.** `OME-1131` wrote it (copying `secret-tavily.yaml`)
and removed it as an active bug: the template renders only when headers are supplied, so the
reuse branch fires exactly where the operator DID supply a value, silently reverting a rotation
to the stale cluster copy. And it cannot be fixed by moving the condition, because "absent" is
a legitimate configuration here. `existingSecret` is the durable path.

**D4 — the credential is OPTIONAL and the Secret is referenced only when it exists.** The
in-cluster collector needs none, and that is the deployment we actually have. An `envFrom`
naming a Secret that is never created stops the pod from starting, so "I enabled tracing and
needed no credential" must not become an outage.

**D5 — previews are left alone, and that is a decision not an omission.** aigateway's preview
Applications (`aigw`, `tag=pr-NNN-*`) carry **inline** values in the ArgoCD Application rather
than a values file, so they would need the stanza set separately. Previews are short-lived and
would add per-PR noise to a shared tracing backend. Default-off means they get nothing unless
somebody opts them in; whether to is an owner call, recorded on the issue.

## Planned changes

- `charts/aigateway/values.yaml` — the `tracing` stanza, off, posture stated at the config site.
- `charts/aigateway/values.schema.json` — the `tracing` object + the `enabled ⇒ endpoint` rule (if a schema exists).
- `charts/aigateway/templates/_helpers.tpl` — `tracingSecretName`, `tracingHasSecret`.
- `charts/aigateway/templates/configmap.yaml` — endpoint / service name / resource attributes.
- `charts/aigateway/templates/secret-tracing.yaml` (new) — the headers Secret.
- `charts/aigateway/templates/deployment.yaml` — the conditional `envFrom.secretRef`.
- `tests/unit/test_chart_render_tracing.py` (new).
- `.github/workflows/aigateway-tests.yml` — `azure/setup-helm@v5` in the `test` job (D1).

## Test plan

Against the RENDERED manifest, because `helm lint` reports success for a chart that cannot
render at all.

- Default values render NO OTLP variables anywhere.
- An endpoint reaches the app's ConfigMap and the pod inherits it.
- `enabled: true` with an empty endpoint fails the render, naming the missing value.
- Headers reach the pod by `envFrom.secretRef` and appear NOWHERE as a literal — not in the
  Deployment, not in a ConfigMap.
- Headers optional: endpoint alone renders cleanly and creates no Secret, and the pod
  references no Secret that does not exist.
- `existingSecret` suppresses the chart-created Secret and is what the pod references.
- Unset `serviceName`/`resourceAttributes` are ABSENT, not empty — an empty value overrides the
  code's own default, and a blank `service.name` is indistinguishable from unconfigured.
- The variable names are OpenTelemetry's specified ones (conformance, on both sides).

**And the tests must actually run:** confirm `helm` is present in the job, i.e. that
`pytest -rs` reports them passed rather than skipped.

## Acceptance

- Chart renders with tracing off by default; no OTLP names appear.
- The credential appears only in the Secret.
- `run_gates.py aigateway` green, and the chart tests are NOT skipped.

## Outcome

- **Actual files:**
  - `charts/aigateway/values.yaml` — the `tracing` stanza, off, with the in-cluster collector
    address and the UI-hostname warning stated at the config site.
  - `charts/aigateway/templates/_helpers.tpl` — `tracingSecretName`, `tracingHasSecret`.
  - `charts/aigateway/templates/configmap.yaml` — endpoint / service name / attributes + the
    `fail` guard.
  - `charts/aigateway/templates/secret-tracing.yaml` (new) — the headers Secret.
  - `charts/aigateway/templates/deployment.yaml` — the conditional `envFrom.secretRef`.
  - `tests/unit/test_chart_render_tracing.py` (new) — 11 tests.
  - `.github/workflows/aigateway-tests.yml` — `azure/setup-helm@v5` in the `test` job.
  - No `values.schema.json` exists for this chart, so no schema rule was added — which makes
    the template `fail` the ONLY guard rather than a backstop, and it is tested accordingly.

- **Gates:** `run_gates.py aigateway` **ALL GREEN**. Full suite **4250 passed, 58 skipped**.
  `verify_chart_wiring.py` **112/112**. `helm lint` clean.

- **Verification beyond the gates:**
  - **Five mutations, five killed:** endpoint dropped from the ConfigMap; headers leaked INTO
    the ConfigMap; Secret referenced unconditionally; the `fail` guard disabled; unset
    `serviceName` rendered as `""`.
  - **Rendered and read by eye** in the real production shape (in-cluster collector, no
    credential): the three OTLP vars appear in the ConfigMap, headers absent. With a credential
    set, `grep -c` finds it exactly **once** in the whole manifest — in the Secret.

- **Deviations:**
  - **This unit also fixes its own gate.** The issue asked where the assertion should live.
    Investigating showed `aigateway-tests.yml` has no helm, so a pytest chart test would have
    skipped silently in CI — asserting nothing while reporting green. That is not hypothetical:
    it is what happened to `OME-1131`'s 12 engine chart tests and to the pre-existing
    `test_chart_render_runner_pool.py`, now filed as **`OME-1189`**. A test that cannot run is
    not a deliverable, so `azure/setup-helm@v5` is part of this unit rather than a follow-up.
  - **`OME-1131` recorded a wrong fact, corrected on that issue.** It claims the engine chart is
    "not gated by `charts.yml` at all"; `charts.yml` lists
    `apps/screamingface-engine/deploy/helm/**` explicitly in both path filters. I had read the
    first few entries of the list rather than all of them.
  - **Previews deliberately untouched.** aigateway's preview Applications carry INLINE values in
    the ArgoCD Application rather than a values file, so they would need the stanza set
    separately. Default-off means they get nothing; whether previews should trace at all is an
    owner call (they are short-lived and would add per-PR noise to a shared backend).
  - **Not verified against a real collector.** Nothing here has exported a span to SigNoz; the
    chart is correct by render. The end-to-end acceptance needs the values set in
    `OpenMined/infrastructure`, which I cannot reach.

- **What turns it on** — four lines in `kubernetes/apps/sf-aigw/values/dev.yaml`:

  ```yaml
  tracing:
    enabled: true
    endpoint: http://signoz-otel-collector.signoz.svc.cluster.local:4318
    serviceName: aigateway
    resourceAttributes: deployment.environment=dev
  ```
