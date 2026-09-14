---
ticket: OME-1042
stack: screamingface
status: done
started: 2026-09-14
finished: 2026-09-14
---

# OME-1042 — Client provider access before evaluation

## Intent

Consume Gateway #932's execution-access discovery field and reject missing required provider configuration before evaluation dispatch. Owner approved proceeding with the Client draft PR on 2026-09-14.

## Planned changes

- `packages/screamingface/src/screamingface/discovery.py`: backward-compatible typed access metadata on ModelDetails.
- `packages/screamingface/src/screamingface/_engine/model_parameters.py`: decode and validate optional access field.
- `packages/screamingface/src/screamingface/_evaluation/model_parameters.py`: reject authoritative missing access before dispatch using the existing details preflight.
- `packages/screamingface/src/screamingface/_evaluation/runner.py`: reuse model admission details during access/parameter preflight.
- New Client regression tests, README guidance, spec, plan and task mirror.

## Test plan

- RED first: sync/async missing access, partial access, configured hosted/BYOK/profileless access, omitted legacy field, malformed metadata, and typed discovery failures.
- Prove zero Candidate dispatch and zero observer events for missing access; test nested required models and no extra discovery requests.
- Preserve existing tests and doctor behavior; run full screamingface gates.

## Acceptance

Only authoritative `missing` produces ProviderConnectionError with provider/model context and an actionable connection hint. Older responses without the field remain unknown and compatible. No new endpoint, provider-specific credentials logic, inference probe, or Engine/Gateway implementation in this PR.

## Outcome

Owner explicitly approved updating the obsolete no-details assertion and affected mock responses on 2026-09-14 via the test-preservation question. New regression tests initially failed (25 RED). Implementation now handles access; correcting new tests to retain existing HTTP 503 PlanningError mapping. Full-suite preparation includes the existing notebook extra, required by connection-panel tests.

- Focused validation: 48 passed, including new access tests, existing parameter preflight and dynamic admission tests. Four request-count assertions updated with owner permission; no parameter/error/dispatch assertions weakened. Initial broad diagnostic run was stopped before completion to include these approved test updates; remaining modules are being checked before final full gates.

- New access matrix: 41 passed (sync/async, local/hosted, generic/Gemini Model ids, configured/legacy unknown, partial/Fusion access, malformed metadata, typed errors, admission reuse).
- Broad diagnostic excluding the slow, unchanged protocol module: 1,449 passed, 23 skipped; only the intended public API snapshot failed. Added changelog and regenerated the additive ModelDetails snapshot using its prescribed workflow. The final gate run includes every test module.
- Test-preservation scope: owner approved obsolete request-count/mock updates; reviewed four assertions and the additive public-surface snapshot. Running the gate runner with `--skip-append-only` records this approved exception; lint, format, typecheck, full test/coverage, notebook, build and distribution gates remain unchanged.
- Wisdom review: provider decisions remain Gateway-owned; no provider branches or local credential inspection in Client. The optional field preserves older responses. Per-evaluation admission reuse avoids duplicate lookups without caching access across evaluations. Discovery API remains non-enforcing; only evaluation rejects missing access. No schema, dependencies, UI rendering or doctor changes.

- Final validation: `uv run .claude/scripts/run_gates.py screamingface --skip-append-only` exited 0, ALL GATES GREEN. Full pytest coverage 95.16% against the unchanged 95% floor. Lint, format, typecheck, notebook, wheel build and distribution checks passed. No test-module exclusion in this final run.
- Actual files: planned discovery/decoder/preflight changes plus runner admission reuse; new access tests; four approved request-count updates; public API snapshot and changelog; README and process artifacts.
- Commit: `fix(screamingface): check provider access before evaluation` (Refs: OME-1042). Draft PR delivery; issue remains In Review until merge.
- Deviations: parameter-free evaluations previously skipped details entirely, so they now perform one lookup per required model. Owner approved the resulting existing-test changes. Gateway #932 remains the runtime prerequisite for authoritative status, but this Client PR may merge independently and preserves legacy omission behavior.

## Follow-up: CI replay discovery route

Intent: repair the authored replay backend after CI reported seven preflight 404s
and three missing-trace failures. Python 3.12/3.13 default checks passed.
Plan: add a loopback regression for the advertised model-details route, then serve
minimal metadata for taped identities only; retain refusal of unknown models and
all existing failure/tracing assertions. No production behavior changes.
Acceptance: regression fails before the fixture fix and passes after; replay cases
and SDK gates pass, or environmental replay limitations are explicitly recorded.

Follow-up outcome: added the missing `/v1/model-parameters` projection to the
FakeGateway only. Taped identities expose configured access and empty capabilities;
untaped/missing identities still fail loudly. All previous assertions remain intact.
Regression command: `uv run --directory packages/screamingface pytest
 tests/e2e/test_fake_gateway_discovery.py -q`: before 1 failed (HTTP 404), 2 passed;
after 3 passed. Combined fixture checks: 17 passed, 7 gated scenarios skipped.
Full SDK gate runner passed lint, format, types, full default test suite with >=95%
coverage, notebooks, build, and distribution validation. Existing owner-approved
append-only exception retained. Docker daemon remained unavailable after a bounded
startup attempt; assets prepared, but full replay confirmation delegated to PR CI.
Wisdom: no production contract, schema, credentials, or error policy changed. Minimal
fixture route restores the actual discovery seam; no weakened assertions or swallowed
errors. The default-lane regression now catches this omission without Docker.
