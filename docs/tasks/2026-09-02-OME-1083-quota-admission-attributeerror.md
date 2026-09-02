---
id: OME-1083
linear_url: https://linear.app/openmined/issue/OME-1083/fix-attributeerror-in-quota-admission-that-blocks-every-run-from
status: in_progress
type:
priority: urgent
labels:
  - screamingface-engine
  - agentic
  - autonomous
created: 2026-09-02
closed:
---

# Fix AttributeError in quota admission that blocks every Run from scheduling

Every Run currently fails to start in the `aks-dev-eastus` cluster: `sf.evaluate(...)`
returns `Could not start the Run: Internal Server Error`. Confirmed live in the `sf-fusion`
App pod's logs — `K8sJobRunner._limitrange_defaults()`
(`apps/screamingface-engine/src/screamingface_engine/adapters/k8s.py:230`) reads
`item.defaultRequest`, but `kubernetes.client.V1LimitRangeItem` exposes that field as
`default_request` (snake_case) — `defaultRequest` is only its JSON wire name. The resulting
`AttributeError` is raised outside the `except ApiException` guard in
`_refresh_quota_if_stale()`, so it propagates uncaught through `schedule()` to the REST
layer as a bare 500, on every single run in any namespace whose `LimitRange` declares a
`defaultRequest` (confirmed: `sf-fusion`).

Regression introduced by `ed1c67b7` (OME-1065, #808). CI didn't catch it because the unit
test double, `FakeLimitRangeItem` (`apps/screamingface-engine/tests/unit/_k8s_fakes.py:38-41`),
mirrors the bug's spelling (`defaultRequest`) instead of the real client's `default_request`.

Fix: `item.defaultRequest` → `item.default_request` at k8s.py:230, plus correcting
`FakeLimitRangeItem`'s field name (and its call site,
`tests/unit/test_runners_k8s.py:512`) so the regression test actually exercises the real
client's attribute shape.

No spec/plan needed — this is a one-line correctness fix reverting a typo to match the real
kubernetes client library's attribute naming; the SDLC unit is ledger → RED → GREEN → gates.
