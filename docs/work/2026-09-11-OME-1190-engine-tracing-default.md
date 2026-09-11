---
ticket: OME-1190
stack: screamingface-engine
status: done
started: 2026-09-11
finished: 2026-09-11
---

# OME-1190 — Default engine tracing ON so ArgoCD ships it without an infra-repo change

## Intent

`OME-1131` shipped the `tracing` stanza off by default, and turning it on needs four lines in
`kubernetes/apps/sf-url4-cloud/values/dev.yaml` inside `git@github.com:OpenMined/infrastructure`
— which this account cannot reach (full `repo` scope, but `OpenMined` is not among its orgs).

Owner decision: default it ON in the chart. Helm merges chart defaults **under** the infra
values file, so ArgoCD deploys it with no infra change, and an operator can still override.

## Design decisions

**D1 — this is only defensible because NEITHER chart in this repo is published, and that is a
sunset condition, not a permanent state.** `release-screamingface-engine.yml` says OCI Helm
publishing is DEFERRED until the NATS dependency is pinned and vendored (`OME-567`); aigateway's
`chart:` job only lints and renders. So these charts are consumed solely by ArgoCD from this
repo — our deployment config, not an artifact strangers install.

A cluster-specific internal DNS name as a *published* chart default would be plainly wrong.
The values file says so at the field, naming `OME-567` as the trigger to revisit.

**D2 — the namespace tag lives in the TEMPLATE, not in `values.yaml`.** Helm does not template
values files, so `{{ .Release.Namespace }}` written there renders as that literal string and the
backend would show every service reporting `deployment.environment={{ .Release.Namespace }}`.
The default is therefore applied where templating actually happens.

**D3 — previews get tagged rather than excluded.** Defaulting on means `sf-preview-pr-*`
namespaces export too. Their spans would otherwise be indistinguishable from dev's: a direct
OTLP export carries the app's OWN Resource, and the k8s collector's namespace enrichment applies
to the LOGS it scrapes, not to spans an app posts itself. So `OTEL_RESOURCE_ATTRIBUTES` defaults
to `deployment.environment=<release namespace>`.

Tagging beats excluding: a preview that exports under its own environment name is *useful*
(you can watch a PR's traces), whereas a namespace-prefix check in a helper would put cleverness
in the chart that nothing else there does.

**D4 — `serviceName` keeps its absent-when-unset rule, and that asymmetry is deliberate.**
An empty `OTEL_SERVICE_NAME` would override the code's own default with a blank `service.name`,
which in a tracing backend is indistinguishable from an unconfigured service. There is no
meaningful chart-level default for it — the code already has the right one. `resourceAttributes`
differs precisely because the chart DOES know something the code cannot: which namespace it is
being installed into.

## ⚠️ Modifies a prior test — Confidence-Gate item, owner-approved

`test_unset_descriptive_values_are_ABSENT_rather_than_empty` (merged in #908) asserts that an
unset `resourceAttributes` renders no key. D3 makes that false on purpose.

Handled by SPLITTING the test rather than weakening it:

- the `serviceName` half keeps its original assertion verbatim (D4), and
- the `resourceAttributes` half becomes a new test asserting the namespace default.

Net assertions go UP, not down. Recorded here because rule 5 makes editing a prior test a
decision to be named rather than a diff to be slipped through — the owner approved the
behaviour change that forces it.

## Planned changes

- `deploy/helm/values.yaml` — `enabled: true`, the in-cluster endpoint, the sunset note.
- `deploy/helm/templates/configmap-runner-env.yaml` — the namespace-derived attribute default.
- `tests/unit/test_chart_render_tracing.py` — split per the note above, plus tests for the
  new defaults and for the fact that an operator override still wins.

## Test plan

- The DEFAULT render (no `--set` at all) now emits `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at the
  in-cluster collector — the inverse of the old "off by default" test, which must be updated
  rather than left asserting the opposite.
- `OTEL_RESOURCE_ATTRIBUTES` defaults to `deployment.environment=<namespace>`, and differs
  between two releases installed into different namespaces (proving it is derived, not fixed).
- An explicit `resourceAttributes` still wins.
- `serviceName` unset is still ABSENT (D4).
- Still no Secret by default, and the pod still references none.
- `tracing.enabled=false` still renders no OTLP names at all — the off switch must keep working.

## Acceptance

- `helm template` with no arguments produces a runner env pointed at the real collector.
- `run_gates.py screamingface-engine` green.

## Outcome

- **Actual files:**
  - `deploy/helm/values.yaml` — `enabled: true`, the in-cluster endpoint, the `OME-567` sunset
    note, and a comment at `resourceAttributes` explaining why its default lives in the template.
  - `deploy/helm/templates/configmap-runner-env.yaml` — the namespace-derived attribute default.
  - `tests/unit/test_chart_render_tracing.py` — 12 tests → **17**.

- **Gates:** `run_gates.py screamingface-engine --skip-append-only` **ALL GREEN** — ruff
  check/format, pyright, `check_layering.py`, pytest+coverage.

- **The append-only gate fired, and that is the point of it.** Rule 5 makes editing a prior
  test a Confidence-Gate decision. The decision was named BEFORE the work (see the ⚠️ section
  above and `OME-1190`'s description), the owner chose the behaviour that forces it, and the
  override is the sanctioned `--skip-append-only` rather than a weakened assertion. Net
  assertions went UP: 12 → 17.

  What actually changed in prior tests:
  - `test_tracing_is_off_by_default_…` → `…is_ON_by_default_…` (the behaviour inverted on
    purpose), with a NEW `test_the_off_switch_still_works` preserving the old property under an
    explicit `enabled=false`.
  - `test_unset_descriptive_values_are_ABSENT_rather_than_empty` SPLIT: the `serviceName` half
    kept verbatim, the `resourceAttributes` half replaced by three stronger tests.
  - Two refusal tests now pass `tracing.endpoint=` explicitly, because the chart ships an
    endpoint and `enabled=true` alone no longer produces the empty-endpoint state they test.

- **Verification beyond the gates — four mutations, four killed:**
  - namespace attribute hardcoded to `sf-fusion` instead of derived → killed
  - the default made unconditional so an operator override is ignored → killed
  - default endpoint swapped to the SigNoz **UI** hostname → killed
  - the `enabled` guard forced true so the off switch stops working → killed

- **Deviations:**
  - **`{{ .Release.Namespace }}` cannot go in `values.yaml`.** Helm does not template values
    files; written there it renders as that literal string and every service reports the
    template source as its environment. A test pins this (`assert "{{" not in preview`).
  - **The default render's namespace is `default`** when `helm template` is called with no
    `-n`. Harmless — ArgoCD always supplies one — but it means the bare-render test asserts the
    endpoint rather than the attribute, and the attribute has namespace-specific tests instead.
  - **This change has a sunset condition, not an indefinite life.** It is defensible only while
    the chart is unpublished (`OME-567`). Stated at the field, in the ticket, and here.
  - **aigateway's equivalent is NOT in this PR** — it needs `OME-1184` (#919) merged first,
    since that is what adds the stanza this would default. No stacked PRs in a squash repo.
