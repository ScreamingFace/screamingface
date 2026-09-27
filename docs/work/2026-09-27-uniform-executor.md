---
ticket: OME-1387, OME-1388   # parent epic OME-1086
stack: screamingface-engine, url4
status: in_progress
started: 2026-09-25
finished:
---

# uniform-executor — one executor for every engine request

## Intent

The engine had two executors: the worker pool (url4 expressions from the NATS run queue, one
child process per run, with events) and the optional node tier (mount calls in a separate
Deployment, with its own capacity, timeouts and spill rule, and no events). This unit makes
the worker pool the only executor. Every request becomes a run on the same queue, in the same
kind of child process, with the same events. After a parity gate, the node tier is removed.

The spec is `apps/screamingface-engine/docs/plans/uniform-executor/` (`00-overview.md`,
`erd.md`, `contracts.md`, `test-plan.md`, `prd/01`–`05`).

## Planned changes

- PRD 01: one shared JetStream stream `url4-events` in place of one stream per run.
- PRD 02: sync `GET /?q=` with no WebSocket.
- PRD 03: warm child pool in the worker (`worker/warm_pool.py`).
- PRD 04: mount calls as `shape=direct` runs; mounts in `/openapi.json`;
  `packages/url4` gets a public direct-call API (`url4.peer.dispatch_direct`).
- PRD 05: remove the node tier (source, chart, tests, CI), after the DC-H1 parity gate.
- Chart defaults sized to today's dev/staging/prod (`events.maxBytes` 1 GiB,
  `events.replicas` 1, `runnerPool.warmChildren` 2).

## Test plan

- `test-plan.md`: unit and integration cases per PRD (EVT-*, SYN-*, WCP-*, MNT-*, DC-*).
- kind suite `tests/kind/` (K1–K12, MNT-26) on a real cluster.
- Latency harness `scripts/bench/sync_latency.py`, cases B1–B4 (report only).
- Parity gate `measurements/parity-gate.md`, checked by `scripts/parity_gate_check.py`.

## Acceptance

- The parity gate passes (all 5 items).
- The card gates pass for `screamingface-engine` and `url4`.
- The kind suite passes.
- The chart renders against the real dev, staging and prod values with no values change.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** 200+ files in `apps/screamingface-engine`, 8 in `packages/url4`,
  `.claude/scripts/check_layering.py`, `.github/scripts/verify_chart_wiring.py`.
  Findings and fixes F1–F11 are in `implementation-notes.md`.
- **Commits:** 35 on `OME-1387-uniform-executor`; `git log origin/main..HEAD`.
- **Gates:** see the PR body (card gates, integration, kind suite, chart renders).
- **Deviations:**
  - This was exploratory work, so this ledger was written after the code, not before it
    (sdlc rule 1). The spec in `docs/plans/uniform-executor/` was written first.
  - Two tests this branch added were changed after the append-only gate flagged them, with
    owner approval: a ruff format (`packages/url4` `test_direct_dispatch.py`) and a rename
    (`tests/integration/test_run_queue_wakeup.py` → `test_run_queue_wakeup_nats.py`).
  - Rollout (owner, 2026-09-27): the App and worker delete legacy per-run streams at startup,
    in place of the manual `purge-legacy-streams` step (D7). This changed the branch's own
    integration test for that startup error and rewrote kind case K11.
  - Mount exposure (owner, 2026-09-27): dev, staging and prod now serve every model and data
    mount; accepted with no chart switch (PRD 04 §6).
  - Review fixes before PR: the Garage StatefulSet keeps main's selector (it is immutable and
    all three environments bundle Garage); the App Service selects `component: control-plane`;
    a direct run reaches only a recorded mount.
  - Filing (owner, 2026-09-27): the two leaves were filed with the `linear` CLI at the owner's
    request, in place of the card's Linear-MCP-only transport (the MCP was not authenticated).
  - Known limits, not fixed: the pre-PR review reports that in local mode, direct runs skip
    the shared fair-share gate (not checked; local mode only);
    `runnerPool.workerSlots: 1` needs `warmChildren` ≤ 1 (the render fails naming both);
    PR previews need a larger JetStream store (OpenMined/infrastructure change, not in this PR).
