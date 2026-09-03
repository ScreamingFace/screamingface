---
ticket: OME-1092
stack: screamingface-engine
status: in_progress
started: 2026-09-03
finished:
---

# OME-1092 — the chart renders a valid runner Deployment, and can declare its own queue

## Intent

Two deployment blockers, both found by manually deploying this stack to a kind cluster on
2026-09-03. Either one alone makes the chart unusable.

**B1 — the chart cannot be installed on any cluster.** The runner-pool template's drain-timing
guard ends with `{{- end -}}`. The trailing `-}}` trims the newline after `end`, so
`apiVersion: apps/v1` is glued onto the end of the preceding YAML COMMENT line and disappears
into it. `helm upgrade --install` then refuses the whole release with "error validating data:
apiVersion not set". Reproduced here from the untouched branch: `helm template` exits 0,
renders 8 documents, and the runner Deployment has no `apiVersion`.

Nothing could catch it. `helm lint` and `helm template` both SUCCEED — neither validates a
manifest — and the chart's own render test parses with `yaml.safe_load_all` and looks documents
up by `kind` + `metadata.name`, all of which still work on a document missing only its
`apiVersion`. The one field that vanished was the one field nothing asserted.

**B2 — the chart cannot express its queue's replica count.** OME-1088 added
`Settings.run_queue_replicas` and OME-1089/1090 wired both composition roots to it; this is the
chart half. Without it a single-node broker — which is exactly what this chart's own bundled
NATS subchart ships — refuses the stream with `ServerError 10074` and every run is refused
while the worker's claim loop retries forever.

## Planned changes

- `deploy/helm/templates/deployment-runner.yaml` — `{{- end -}}` → `{{- end }}` (B1); render
  `URL4_CLOUD_RUN_QUEUE_REPLICAS` into the worker's explicit env (B2).
- `deploy/helm/templates/configmap.yaml` — render `URL4_CLOUD_RUN_QUEUE_REPLICAS` for the App
  (B2). Both halves declare the same stream, so both must read the same value.
- `deploy/helm/values.yaml`, `values.schema.json` — `config.runQueueReplicas`, default **1**
  (owner decision, 2026-09-03): it matches the single-node subchart the chart actually bundles,
  so the default install works.
- `tests/unit/test_chart_render_document_identity.py` — NEW file (tests are append-only).

## Test plan

- Every rendered document declares a non-empty `apiVersion` — the regression, asserted across
  ALL documents rather than the one template that broke, so the same one-character slip
  anywhere fails here instead of at `helm upgrade` time.
- Every rendered document declares a `kind` and a name, for the same reason.
- The runner-pool Deployment specifically declares `apps/v1` — the generic sweep would also
  pass if the pool stopped rendering at all.
- The identity check holds under a non-default drain configuration, since the guard block whose
  `end` caused the defect is conditional on those values.
- The replica count reaches BOTH the App ConfigMap and the worker's env, and follows the value.

## Acceptance

- `helm template` renders no document lacking an `apiVersion`.
- `URL4_CLOUD_RUN_QUEUE_REPLICAS` is present in both halves and follows `config.runQueueReplicas`.
- `run_gates.py screamingface-engine` green.

## Outcome

- **Actual files:** as planned, plus one typing repair (see Deviations).
  - `deploy/helm/templates/deployment-runner.yaml` — `{{- end }}` (B1) with an `INVARIANT:`
    comment naming the trap; `URL4_CLOUD_RUN_QUEUE_REPLICAS` in the worker env (B2).
  - `deploy/helm/templates/configmap.yaml` — `URL4_CLOUD_RUN_QUEUE_REPLICAS` (B2).
  - `deploy/helm/values.yaml`, `values.schema.json` — `config.runQueueReplicas`, default 1.
  - `tests/unit/test_chart_render_document_identity.py` — NEW.
  - `tests/unit/test_chart_render_queue_replicas.py` — NEW.
  - `tests/unit/test_worker_metrics.py` — EDITED, one import (see Deviations).
- **Commits:**
  1. `fix(engine): bind nats.errors explicitly in the worker metrics test`
  2. `fix(engine): the runner Deployment keeps its apiVersion`
  3. `feat(engine): the chart renders the queue's replica count to both halves`
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` — ALL GATES GREEN.
  RED was witnessed for both blockers before either fix: the identity test failed with exactly
  `['Deployment/url4-cloud-url4-cloud-runner']`, and the replica tests failed on all four
  rendering assertions.
- **Deviations:**
  1. **B1 was reproduced from the untouched branch before being fixed.** `helm template` on
     `origin/OME-1092-chart-cutover` exits 0, renders 8 documents, and the runner Deployment
     has no `apiVersion` — confirming both the defect and that a render-only gate cannot see
     it. The new test therefore asserts the property across EVERY rendered document, not just
     the template that broke.
  2. **A third instance of the `nats.errors` latent bug.** `test_worker_metrics.py` reaches
     `nats.errors.Error` through a bare `import nats`, in a deliberate error-injection path.
     Had the transitive import ever changed, the injection would have raised `AttributeError`
     and the test would still have seen an exception — passing for the wrong reason. Now three
     confirmed sites (`runner_queue.py`, `test_worker_claim.py`, here); a repo-wide sweep is
     worth its own ticket.
  3. **The rebase onto the fixed OME-1091 needed `git rebase --onto`.** A plain
     `git rebase OME-1091-...` tried to replay OME-1091's ORIGINAL commits — their patch-ids
     no longer matched after conflict resolution during that branch's own rebase, so git could
     not detect them as already applied, and it produced six spurious conflicts.
     `git rebase --onto <new-parent> <old-parent>` replays only this branch's own six commits.
     This is the rule for every rewritten stacked parent, not a one-off.
  4. **One conflict resolved by DROPPING imports, deliberately.** `test_runners_factory.py`:
     this branch retires the k8s adapter, so `K8sJobRunner`, `Mapping` and `Any` became unused
     while `cast`, `JetStreamPublisher` and `RunQueue` are still needed by the typing fix from
     OME-1090. Verified by counting real usages rather than by eye.

## Follow-ups surfaced (not in this unit)

- **The chart's CI gate still cannot catch B1's class.** `charts.yml` and the engine lane both
  run `helm lint` + `helm template`, neither of which validates a manifest. The new unit test
  closes it for this repo, but adding `helm template ... | kubectl apply --dry-run=client -f -`
  to the charts lane would catch it for every chart at once.
- A repo-wide sweep for `import nats` + `nats.<submodule>` access (three sites found here).
