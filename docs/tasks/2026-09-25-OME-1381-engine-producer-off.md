---
id: OME-1381
linear_url: https://linear.app/openmined/issue/OME-1381/refuse-x-profile-at-engine-ingress-and-stop-producing-selector-bearing
status: in_progress
type: task
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1138
related: [OME-1377]
blocked_by: []
created: 2026-09-25
closed:
---

# Refuse X-Profile at Engine ingress and stop producing selector-bearing runs

This is Stage D step 2 of `OME-1138`: Engine producer-off.

- **Refusal at ingress.** A nonblank `X-Profile` gets a value-free, non-retryable
  `400 x_profile_unsupported` before any schedule, queue publication, catalog or gateway I/O,
  or connection mutation. The refusal covers execution, catalog, model parameters, connections
  and the sync mounts.
- **No selector on new work.** New schedule calls and queue messages carry no selector.
- **No ambient inheritance.** A worker no longer inherits an ambient `AIGATEWAY_PROFILE` for a
  message without the field.
- **Legacy messages still honoured.** A message that still carries the field is honoured and
  forwarded until the drain proof.

AIGateway stays on `HONOUR`. This build is the rollback floor for the later gateway reject.

## Progress

- 2026-09-25: owner decision — no separate census. The dev evidence and the absence of
  first-party callers that send `X-Profile` are enough to proceed. Issue filed under `OME-1138`,
  related to `OME-1377`. Ledger: `docs/work/2026-09-25-OME-1381-engine-producer-off.md`.
- 2026-09-25: implementation and tests ready for review; not committed.
- 2026-09-26: owner review — changes required. Fixed:
  - the connection routes now refuse at the route boundary, ahead of body validation (422) and
    the unconfigured-service 503;
  - OpenAPI declares the catalog 400s as problems and the deprecated header on the connection
    routes;
  - the no-echo check covers response headers;
  - stale docs and the short test secrets.

  The owner accepted the five re-expressed prior tests (Confidence-Gate exception) and approved
  the breaking-change classification. The census waiver goes into the tracked spec and plan
  through a separate docs landing under `OME-1377`, ahead of this one.

  Engine gates with `--skip-append-only` are all green: `3954 passed, 23 skipped`, coverage
  94.48%.
- 2026-09-26: owner decision — everything lands as one PR.
  - The census waiver is recorded in the tracked spec and plan in this landing, with no separate
    `OME-1377` landing.
  - Rebased onto `origin/main` `69971220`.
  - One breaking commit and one PR, with `Refs: OME-1381, OME-1377`.
  - The issue stays In Progress.
