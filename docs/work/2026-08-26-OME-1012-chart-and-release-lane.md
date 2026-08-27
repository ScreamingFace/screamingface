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
- **Post-review CI fix (2026-08-27).** The `charts.yml` "Render report-intake's cloud values"
  step went red on the PR while every local gate was green. The review pass had hardened
  `values-cloud.yaml` by moving the blanket private ranges out of `config.allowedNetworks` and
  turning `networkPolicy.enabled` on with an empty peer list — both correct, both guarded by the
  chart's own render refusals — but did not add the matching placeholders to the CI step it also
  owns. Fixed by passing three more `--set` placeholders, and an `AIDEV-NOTE` now says why the
  fix belongs in the workflow rather than in `values-cloud.yaml`: putting a real default back
  would defeat the guard the hardening exists to create.

  This is the same shape as plan §11 conflict 5 (chart defaults tripping the chart's own guard),
  reintroduced in the *other* values file while fixing a security concern in it. It also exposed
  a gap in how the gates were verified: `run_gates.py` and `verify_chart_wiring.py` both pass
  without exercising the `helm template` steps `charts.yml` runs separately, so "all gates green"
  locally did not mean the chart lane was green.
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

## 2026-08-27 — closing the chart and deployment gaps

Five gaps, plus one latent break found while closing them. The chart was not restructured; every
change is additive except two renamed references.

### 1. `values.schema.json`

New: `charts/report-intake/values.schema.json`, following `apps/screamingface-engine/deploy/helm`'s
(the repo's only prior one). Helm validates the coalesced values against it before any template
runs, so the two layers had to be separated rather than stacked:

- **The schema types the VALUES.** Types, ranges, three enums (`image.pullPolicy`, `service.type`,
  the rate limit's `unit`), URL scheme patterns on the two endpoints the ConfigMap always renders,
  `minimum: 1` on the four `anonRate` fields mirroring `config.py`'s own `Field(ge=1)`, and
  `additionalProperties: false` at every level. That last one is the half that earns its keep:
  `config.authmode`, a `gateway.hostnames` block copied from the engine chart, a stale key left
  behind after a template was deleted — each installs silently today, `Settings` is
  `extra="ignore"`, and the pod then runs on a default while the values file says otherwise.
- **The templates keep refusing the COMBINATIONS.** Not one conditional refusal is duplicated as a
  schema `if/then`, and this is the "must not contradict" requirement taken literally rather than
  loosely: the schema runs FIRST, so a conditional there does not add a check, it REPLACES the
  template's paragraph with `must be at least 1 item`. Two of those paragraphs are asserted by
  `verify_chart_wiring.py` by their words (`503`, `unauthenticated write`, `OME-976`,
  `X-Forwarded-For`, `admits every source`), so duplicating them would have broken existing checks
  as well as degrading the message. Verified: `turnstile.existingSecret` and
  `linear.existingSecret` must stay unconstrained — `values-cloud.yaml` ships the first EMPTY on
  purpose, and the verifier sets the second empty to prove the `OME-976` refusal fires.

Three values are deliberately left untyped beyond `string`, each with a `$comment` naming the
authority instead: `config.authMode` (the template's `fail` explains what each mode *is*, and the
verifier already compares the rendered value to `config.py`'s `AuthMode` literal via its AST),
`config.ticketSink` (`config.py` keeps it a plain string so adding an adapter is one registry line —
an enum here would re-add exactly the coupling that docstring refuses), and `config.deliveryTimeoutS`'s
upper bound (arithmetic over `retry.CLAIM_GRACE` and `store.STORAGE_TIMEOUT_S`; a third copy could
drift into refusing a legal value, and `main._check_delivery_timeout` already refuses the bad one).

### 2. `BackendTrafficPolicy` — spec §7's edge rate limit

New: `templates/backendtrafficpolicy-public.yaml` and `gateway.public.rateLimit`
(`enabled`/`requests`/`unit`/`sourceCIDRs`), off in `values.yaml`, on in `values-cloud.yaml` at 20
requests per hour per client address. `_helpers.tpl` gained `report-intake.publicRouteName`, and
`httproute-public.yaml` now renders its name from it — the same reason `identityRouteName` exists,
since a second object now targets that route by name. The rendered name is unchanged.

**`type: Global`, not `Local`, and that is not a preference.** Envoy's local rate limit does not
support `Distinct` matching (Envoy Gateway's own local-rate-limit doc says so outright), so the
only thing a Local policy could express is one shared bucket per proxy instance — which is what
`config.anonRate` already is, one layer out. A per-caller limit is `Global` with
`sourceCIDR: {value: 0.0.0.0/0, type: Distinct}`, and `Global` needs the Redis-backed rate-limit
service.

**Two prerequisites this chart can neither install nor check, and both fail OPEN.** They are named
in the template, in both values files, in the chart README and in DEPLOYMENT.md, with the
`kubectl get backendtrafficpolicy … status.conditions` check that detects the first:

1. Envoy Gateway's rate-limit service. Missing, the policy is not Accepted and the hostname serves
   unlimited.
2. A `ClientTrafficPolicy` on the Gateway with `clientIPDetection`. Missing, the address Envoy
   buckets on is the LOAD BALANCER's, so `Distinct` collapses the internet into a handful of
   buckets — the exact failure the object exists to fix. Not rendered here on purpose:
   `ClientTrafficPolicy` targets the **Gateway**, which this chart does not install and which
   other services attach to.

`sourceCIDRs` is a list and IPv4-only by default, which means **an IPv6 caller matches no rule and
is unlimited**. Said out loud rather than papered over: `::/0` is not in the default because a
`sourceCIDR` the installed Envoy Gateway rejects makes the whole policy not-Accepted, taking the
IPv4 limit with it — fail-open, on the one hostname that accepts unauthenticated writes.

Two new render refusals: the rate limit without `anonymous.enabled` (the policy would target a
route that does not exist — attaching to nothing, limiting nothing, still reporting Accepted), and
an empty `sourceCIDRs` (each entry is one rule, so empty is a policy with no rules). Deliberately
NOT added: a refusal of `anonymous.enabled` WITHOUT this policy. Spec §7 is satisfied by a
Cloudflare rule on the hostname, and making the policy mandatory would force a Redis dependency on
a deployment that already has an edge limit.

### 3. The Linear sink credential

**Already wired, by OME-1009's chart pass** — `linear.existingSecret` / `existingSecretKey`, the
Deployment's unconditional `secretKeyRef` with `optional: true`, the two `fail` guards, and the
`verify_chart_wiring.py` assertions for both. Re-verified against `config.py` rather than assumed:
the four `REPORT_INTAKE_LINEAR_*` names the chart renders are exactly the four fields it declares,
and the equality check that would catch any drift is green from both sides. Nothing to add; the
only change in this area is `values.schema.json` typing the block without constraining
`existingSecret`, for the reason above.

### 4. `dev-build-report-intake.yml`

New, mirroring `dev-build-aigateway.yml` (the closest sibling — same stack, same single-image
shape). Immutable `main-<shortsha>` on GHCR and ACR plus `main-<full sha>` on ACR, never `:latest`,
`SOURCE_DATE_EPOCH` pinned to the commit's timestamp, its own cache scope `dev-report-intake`. The
verifier gained the pair of checks aigateway-ui's lane already had — that the dev lane pushes the
same repository the chart and release lane name, and that every tag is a `main-` one — and the
existing "every dev-build lane has its OWN cache scope" check now covers five lanes.

### 5. `DEPLOYMENT.md`

New, in `apps/aigateway/DEPLOYMENT.md`'s voice: artifacts, prerequisites, the two hostnames and why
one route with `jwt.optional: true` is an identity bypass rather than a simplification, the
install-time values with where each comes from (including the `kubectl`/`az` commands that produce
the Pod CIDR and the mesh data plane's label), the Secrets, the four Cloudflare dashboard actions,
the edge rate limit's prerequisites, `queue` vs `linear` with rule 9 stated plainly, the three
`report-intake queue` commands with their exit codes, the smoke checks, a refusal-by-refusal table,
and operations notes.

**The brief's "eight install-time values the chart refuses to render without" is off by two, and
the runbook says the accurate thing.** Measured by rendering `values-cloud.yaml` eight times with
one flag dropped each time: SIX stop the render (`gateway.parentRef.name`, the Cloudflare team and
audience, `turnstile.existingSecret`, `config.allowedNetworks`, `networkPolicy.clientPodNames`) and
TWO do not — `database.existingSecret` defaults to the NAME `report-intake-db` with no object
behind it, and `networkPolicy.clientNamespace` defaults to the release namespace, which silently
admits nobody when the mesh gateway lives elsewhere. Both are worse to discover than a refusal, so
the table lists all eight and marks which is which.

### 6. Found and fixed: `release-report-intake.yml` could not render

Not in the brief. `release-report-intake.yml`'s "Render" step still passed the FIVE `--set`
placeholders it was written with, while the review pass that emptied `config.allowedNetworks` and
`networkPolicy.clientPodNames` in `values-cloud.yaml` added three to `charts.yml` only. Confirmed by
running it: the step fails today, so the next `report-intake-v*` tag would have published nothing.
Fixed by bringing the two sets into line.

The interesting half is why it survived: `charts.yml` runs on every PR touching the chart and
`release-report-intake.yml` runs only on a tag, so the lane that drifted is structurally the one
that cannot notice. `verify_chart_wiring.py` now asserts the two lanes carry an IDENTICAL set of
`--set` keys, keyed off the `charts.yml` step (the one that stays current). This is the same shape
as the post-review CI fix recorded above — a values-file hardening that did not reach every lane
rendering that file — caught the second time by a check rather than by a red tag.

### Verification

- `verify_chart_wiring.py`: **86/86** (was 78/78). Eight new checks: the edge rate limit's
  presence, its target, `Global`, `Distinct` on every rule; the two dev-lane checks; the
  lane-parity check; and the bare-install check extended to `BackendTrafficPolicy`.
- **Every new check was verified by breaking it, and reverted.** `type: Local`, `type: Exact`,
  the policy re-targeted at the identity route, the policy switched off in `values-cloud.yaml`, the
  dev lane's repository renamed, its cache scope duplicated onto `dev-scoreboard`, and a dropped
  `--set` in the release lane. The first version of the presence check aborted the script with a
  traceback when the policy was absent — the same failure the first pass over this chart already
  paid for — so the three dependent reads were made tolerant and now report four named FAILs.
- **The schema was verified by breaking values, not by reading it**: `config.authmode` (rejected as
  an additional property), `--set-string config.port=9109` (`got string, want integer`),
  `unit: hour` (`must be one of 'Second', 'Minute', 'Hour', 'Day'`). Both new template guards were
  triggered deliberately and print their own paragraph, not a schema error.
- `helm lint` clean; `helm template` green for `values.yaml`, for `values-cloud.yaml` with the
  `charts.yml` placeholder set, and for the release lane's now-matching set.
- App gates in `apps/report-intake`: `pytest`, `ruff check`, `ruff format --check`, `pyright`.
  No Python changed in this pass — `test_chart_environment.py` scans `*.yaml`/`*.tpl` under
  `templates/`, so a new template and a new `.json` leave it green, and it was re-run to confirm
  rather than reasoned about.

### Deviations

1. **`values.schema.json` is not named in plan §10.** The brief says it is; §10 names
   `apps/aigateway-ui/charts/aigateway-ui/` as the layout pattern and that chart has no schema.
   Built anyway — the gap is real and the engine chart is the house precedent — but the plan was
   not amended, since this is an addition to §10's deliverable rather than a change to a frozen
   contract.
2. **Two files outside `apps/report-intake/` were edited beyond the workflows**:
   `.claude/skills/working-in-this-repo/SKILL.md`'s report-intake row said the release lane "lands
   with OME-1012" and named no dev lane, and `charts.yml`'s comment claimed all eight install-time
   values are render failures. Both are now accurate. Repo `CLAUDE.md` was not touched.
3. **No `linear.enabled` flag was added and no repo rule was amended.** Rule 9 is named in
   DEPLOYMENT.md as governing the selection and left to the owner, exactly as
   `delivery/linear_sink.py` and the chart already do.
