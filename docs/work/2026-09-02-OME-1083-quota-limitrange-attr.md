---
ticket: OME-1083
stack: screamingface-engine
status: done
started: 2026-09-02
finished: 2026-09-02
---

# OME-1083 — Fix AttributeError in quota admission that blocks every Run from scheduling

## Intent

Every `sf.evaluate(...)` call currently fails with "Could not start the Run: Internal Server
Error" in the `aks-dev-eastus` cluster. Confirmed live (via `firecall-connect` k8s access) in
the `sf-fusion` App pod's logs: `K8sJobRunner._limitrange_defaults()`
(`adapters/k8s.py:230`) reads `item.defaultRequest`, which does not exist on the real
`kubernetes.client.V1LimitRangeItem` — that client exposes the field as `default_request`
(snake_case); `defaultRequest` is only its JSON wire name. The `AttributeError` is raised
outside the `except ApiException` guard in `_refresh_quota_if_stale()`, so it propagates
uncaught through `schedule()` to the REST layer as a bare 500 on every run.

The deeper defect is one level up: the module's own narrow structural `Protocol`
(`_LimitRangeItem` at `adapters/k8s.py:117-123`) declares the property as `defaultRequest`
— the wire name, not the Python attribute name — so the implementation that duck-types
against it is "correct" relative to a Protocol that itself does not describe the real
object. `core_client_factory()` hands the real `CoreV1Api` to this Protocol through
`cast(CoreV1QuotaClient, ...)` (`adapters/factory.py:60`), and `cast()` is a type-checker
no-op — it never verifies the real client actually satisfies the Protocol, so pyright's gate
could not catch the mismatch. The unit-test fake, `FakeLimitRangeItem`
(`tests/unit/_k8s_fakes.py:38-41`), was written against the same wrong Protocol, so it also
agrees with the bug. On top of that: no existing test ever passes a non-`None`
`default_request` through `_limitrange()`'s test helper — every LimitRange test exercises
only the `default` (limits) accumulation, never `default_request` (requests) — so that whole
branch of `_limitrange_defaults()` had zero coverage before this bug shipped.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/adapters/k8s.py`
  - `_LimitRangeItem.defaultRequest` (Protocol property, line ~123) → `default_request`
  - `_limitrange_defaults()`'s `item.defaultRequest` (line ~230) → `item.default_request`
  - Add a `WHY:` anchor at the Protocol declaration naming the client/wire-name trap, so the
    next person adding a k8s-model Protocol property does not repeat it.
- `apps/screamingface-engine/tests/unit/_k8s_fakes.py`
  - `FakeLimitRangeItem.defaultRequest` field → `default_request` (matches the corrected
    Protocol; this is a test-double correction, not a behavior weakening — the prior fake
    agreed with the bug, not with the real dependency it stands in for).
- `apps/screamingface-engine/tests/unit/test_runners_k8s.py`
  - `_limitrange()` helper's `FakeLimitRangeItem(..., defaultRequest=default_request)` call
    site → `default_request=default_request`.
  - New test exercising the previously-uncovered `default_request` (requests-defaulting)
    path against the REAL `kubernetes.client.V1LimitRangeItem`/`V1LimitRangeSpec`/
    `V1LimitRange`/`V1LimitRangeList` objects — not the local fake — so this exact class of
    Protocol/real-client drift is caught even if the fake drifts again later.

## Test plan

- RED: add a test that builds a real `kubernetes.client` LimitRange chain with
  `default_request={"cpu": "100m", "memory": "128Mi"}` and asserts the runner's admission
  charge folds that default into `requests.cpu`/`requests.memory` for a Pod spec that sets
  no explicit request on those dimensions. Confirm it fails on unfixed code with the exact
  production `AttributeError`.
- GREEN: apply the attribute rename (Protocol + implementation); confirm the new test passes
  and every prior test in `test_runners_k8s.py` still passes after the fake/call-site rename.
- Boundary already covered by existing suite: `default` (limits)-only LimitRange,
  quota-headroom refusal/acceptance, concurrent reservation race, quota-unreadable
  degrade-open, no-quota degrade-open — all untouched, all must stay green.

## Acceptance

- `_limitrange_defaults()` reads the real kubernetes client's attribute names for both
  `default` and `default_request`.
- A test exists that would have caught this exact bug against the real client shape, not
  only the hand-rolled fake.
- All `screamingface-engine` gates green (ruff, ruff format, pyright, check_layering, pytest
  with coverage floor).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** matches planned:
  - `apps/screamingface-engine/src/screamingface_engine/adapters/k8s.py` — `_LimitRangeItem.defaultRequest` → `default_request` (Protocol property + `WHY:` anchor); `_limitrange_defaults()`'s `item.defaultRequest` → `item.default_request`; docstring clarified.
  - `apps/screamingface-engine/tests/unit/_k8s_fakes.py` — `FakeLimitRangeItem.defaultRequest` → `default_request` (+ docstring anchor); `FakeCoreV1`/`FakeLimitRangeList` widened from the concrete `FakeLimitRange` type to the structural `_LimitRangeView` Protocol so a real `kubernetes.client.V1LimitRange` type-checks through the same seam.
  - `apps/screamingface-engine/tests/unit/test_runners_k8s.py` — `_limitrange()` helper's `defaultRequest=` kwarg → `default_request=`; new regression test `test_limitrange_default_request_is_read_from_the_real_kubernetes_client_shape` built from the real `kubernetes.client` LimitRange types.
  - `docs/work/2026-09-02-OME-1083-quota-limitrange-attr.md` (this ledger).
- **Commits:** `1faeb2f9` — fix(screamingface-engine): read the k8s client's default_request attribute, not defaultRequest
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine --skip-append-only` — ruff check ✓, ruff format --check ✓, pyright ✓, check_layering.py ✓, `pytest --cov=screamingface_engine --cov=url4.streaming --cov-fail-under=80` ✓ (41/41 in `test_runners_k8s.py`, full suite green). ALL GATES GREEN.
- **Deviations:**
  - Append-only test check (`run_gates.py`'s automated pre-check) flagged the `_limitrange()` helper's kwarg rename at `test_runners_k8s.py:512` as a prior-test edit and correctly HARD-STOPPED. Per sdlc rule 8 (95% Confidence Gate) this was surfaced to the user explicitly via `AskUserQuestion` before proceeding — approved ("Yes, proceed") — and the gate was re-run with `--skip-append-only`. No test assertion or expected value changed; only a fixture kwarg was renamed to match the corrected `FakeLimitRangeItem` field, which itself was corrected to stop mirroring the bug's wrong attribute spelling. Confirmed pre-approved in the OME-1083 ticket description filed earlier in this session.
  - Widened `FakeCoreV1`'s `limitranges` parameter and `FakeLimitRangeList.items` from `list[FakeLimitRange]` to `Sequence[_LimitRangeView]` (not originally itemized in Planned changes) — required for the new regression test to type-check while passing a real `kubernetes.client.V1LimitRange` through the fake client seam; no behavior change, strictly a widening (every prior caller passing `FakeLimitRange` still type-checks, since it already structurally satisfies `_LimitRangeView`).
