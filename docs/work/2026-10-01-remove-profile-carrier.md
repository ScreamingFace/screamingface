---
ticket: OME-1449
stack: screamingface-engine
status: in_progress
started: 2026-10-01
finished:
---

# remove-profile-carrier — remove the retired selector carrier

## Intent

Complete Stage D of `OME-1138` by trimming the obsolete Profile selector carrier after Engine and
AIGateway ingress rejection has shipped. New and retained runtime paths become structurally
selector-less: no schedule argument, queue/environment key, request-scope field or outbound header
remains. The owner confirmed that no legacy `AIGATEWAY_PROFILE` queue messages remain, so no
compatibility reader or transition detector is required.

The shared URL4 port is a separate package leaf, `OME-1450`, coordinated in this landing. This
ledger owns only the Engine implementation and its documentation/status closeout.

The approved specification and plan are
`docs/spec/2026-09-09-OME-1138-converge-connections.md` and
`docs/plan/2026-09-09-OME-1138-converge-connections.md` (Stage D S6/S9).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/ports.py`, `adapters/inprocess.py`,
  `adapters/queue_runner.py`, and `runner_queue.py` — remove the `profile` scheduling contract.
- `apps/screamingface-engine/src/screamingface_engine/job_env.py`, `runner/main.py`, and
  `worker/supervisor.py` — remove `AIGATEWAY_PROFILE` from process and queue handling.
- `apps/screamingface-engine/src/screamingface_engine/request_scope.py`, catalog, connections, and
  world connector modules — remove profile state and outbound `X-Profile` forwarding.
- Engine unit tests and docs — replace compatibility-carrier assertions with absence contracts
  while preserving existing ingress-refusal tests unchanged.
- OME-1398 task/ledger and the OME-1138 plan/umbrella ledger — record the merged UI/docs work and
  this final Stage D carrier landing.

## Test plan

- Add structural contract tests first that reject a `profile` schedule parameter, the
  `AIGATEWAY_PROFILE` constant, profile-bearing request-scope/catalog/connection objects, and
  outbound `X-Profile` rendering.
- Preserve and run the existing Engine ingress-refusal suites to prove every nonblank selector is
  still rejected before scheduling or upstream I/O.
- Run focused queue, scope, catalog, connection and connector suites, then the complete
  `screamingface-engine` quality gate.

## Acceptance

- Runtime source has no Profile selector carrier or forwarding path.
- Public Engine ingress still declares and enforces `400 x_profile_unsupported`.
- Selector-less identity, tracing, cache and answer-seed propagation remain green.
- OME-1398 tracked status matches Linear Done and OME-1138 names only the actual remaining work.
- All declared `screamingface-engine` gates pass.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** removed the Profile selector from Engine scheduling adapters, queue/env codecs,
  request scope, credentials/callers and outbound catalog/connections/world headers; added one
  private retired-key scrub shared by the in-process, cold-child and warm-child boundaries; updated
  the affected tests and current Engine/OME-1138 docs; added
  `tests/unit/test_profile_carrier_retirement.py`; removed the obsolete carrier compatibility suite.
- **Commits:** this commit — `refactor(engine): remove retired profile carrier`.
- **Gates:** focused migration regressions 10 passed; direct full suite 4357 passed / 67 skipped /
  13 deselected; configured Engine gate passed Ruff, Ruff format, Pyright, layering and parallel
  coverage tests; `git diff --check` passed. The final pre-commit review found an ambient
  `AIGATEWAY_PROFILE` leak at all three run-environment boundaries; a new RED test reproduced it,
  the shared scrub fixed it, 52 focused boundary/runner tests passed, and both configured gates were
  rerun green. Re-review plus mutation probes confirmed each boundary is covered and found no
  remaining runtime finding.
- **Deviations:** the append-only check was intentionally skipped for the final configured Engine
  gate. The owner had explicitly authorised this contract retirement after confirming no legacy
  queue messages remain; the approved transition necessarily rewrites old signature/fixture tests
  and deletes compatibility-carrier assertions. The first unskipped run stopped only on that policy
  check; every executable gate then passed with `--skip-append-only`.
