---
ticket: OME-1870
stack: screamingface-engine
status: done
started: 2026-11-10
finished: 2026-11-10
---

# runner-pool-autoscaling — scale the runner pool on claimable queue demand

## Intent

The runner pool is a fixed Deployment (prod: 2 pods x 4 slots). When every slot is busy, a new
user's runs wait in the NATS queue until a slot frees, and nothing adds capacity. This unit gives
the pool an opt-in horizontal autoscaler: the App measures the CLAIMABLE demand on the queue, serves
it on an internal JSON endpoint, and the chart renders a KEDA ScaledObject that keeps
`replicas = ceil(demand / workerSlots)` between a min and a max. Default off: the render is unchanged
until an environment turns it on. First problem of the "UX over cost" capacity work (divide and conquer).

Spec: `docs/spec/2026-11-10-runner-pool-autoscaling.md`.
Plan: `docs/plan/2026-11-10-runner-pool-autoscaling.md`.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/runner_demand.py` (new): readings, pure
  `claimable_demand`, `RunnerDemandSampler`.
- `apps/screamingface-engine/src/screamingface_engine/runner_queue.py`: `RunQueue.bucket_readings()`.
- `apps/screamingface-engine/src/screamingface_engine/adapters/queue_runner.py`: expose the readings.
- `apps/screamingface-engine/src/screamingface_engine/config.py`: `runner_demand_sample_s`,
  `runner_demand_stale_s`.
- `apps/screamingface-engine/src/screamingface_engine/app.py`: `_install_runner_demand_sampler`.
- `apps/screamingface-engine/src/screamingface_engine/ops.py`: `GET /runner-demand`.
- `apps/screamingface-engine/src/screamingface_engine/metrics.py`: `_RunnerDemandCollector`.
- Chart: `values.yaml`, `values.schema.json`, `templates/deployment-runner.yaml`,
  `templates/scaledobject-runner.yaml` (new), `templates/NOTES.txt`, `README.md`.
- `.claude/scripts/check_layering.py`: list `runner_demand` in `CONTROL_PLANE`.
- CI: add the new real-NATS test to the conformance job in `screamingface-engine-tests.yml`.

## Test plan

- See the plan's "Test plan (RED first)". New test files only; no existing test changes.

## Acceptance

- Disabled (default): `helm template` output is identical to `origin/main` for the default values.
- Enabled: one ScaledObject targets `<fullname>-runner`; the Deployment has no `spec.replicas`.
- The scenario (2 users saturate 2x4 slots, a 3rd user queues n runs) yields demand `8 + min(n, 4)`
  and therefore 3 replicas; held-back runs of a capped bucket never add a pod.
- No sample or a stale sample answers 503, never a confident 0.
- `run_gates.py screamingface-engine` green; kind walkthrough recorded in Outcome.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus three extra new test files:
  `test_app_runner_demand_queue_capability.py`, `test_queue_runner_bucket_readings.py`,
  `test_run_queue_bucket_readings.py`. Built by the `tiered-build` workflow (run
  `wf_501401b6-a00`, 4 waves, Haiku implementers, Opus design review), then the owner-approved
  cleanups below by hand.
- **Commits:** one local commit on `runner-pool-autoscaling` (see `git log`); not pushed, no PR,
  no Linear issue yet.
- **Gates:** `run_gates.py screamingface-engine` (append-only check included) ALL GREEN;
  `run_gates.py repo` ALL GREEN. With autoscaling off, `helm template` is byte-identical to
  origin/main (archived chart, pinned `auth.jwtSecret`). `verify_chart_wiring.py` 145/145.
  `tests/integration/test_runner_demand_nats.py` passed against a real `nats:2.10-alpine -js`
  (not skipped).
- **Design review (ACCEPT-WITH-FIXES):** F1 README gauge names, F2 shared code placement (now
  identical to `OME-1869`'s `BucketReading` / `_reading_of` / `_consumer_infos` /
  `bucket_readings`), F3 extra protocol branch, F7 dangling "D4" reference: fixed by the workflow.
  F4 (route read the sampler twice) and F5 (needless defensive code) fixed by hand on owner
  request 2026-11-10: `fresh()` now returns `(demand, sampled_at, age_s)` from one read; the
  constructor `ValueError`, the `stale_s` property, an `assert` and the broker-value clamps are
  gone (two new-file tests that pinned them removed). F6: owner decision 2026-11-10, the two
  sampler settings stay code defaults with no chart value; the chart README says so.
- **Kind walkthrough (2026-11-10, kind `sf-prod`, image `local-2fe3e8d82279`, KEDA 2.20.2):**
  stub gateway (catalog/admission forwarded to aigw, completions canned after 45 s; no provider
  call), three identity edges: user-a bucket 03, user-b bucket 0f, user-c bucket 00. Pool 2 slots
  per pod, autoscaling min 2 max 4. Sample log every 5 s.
  - KEDA read `/runner-demand` at once (`0/2 (avg)`).
  - A×2 + B×2: demand 4, 2 pods (no scale). PASS.
  - A×2 more: 3rd pod at once. Cause: the 16 durable consumers were 20 days old with
    `max_ack_pending` 4; the new pin 2 did not change them (the code needs a consumer delete and
    re-make for that). The signal read the broker's real cap 4, so the scale was CORRECT.
  - A×2 more at the real cap 4: queued 2, claimable 0, demand 6, no new pod. PASS (negative case).
  - C×2 (empty bucket): submit 20:41:20, 4th pod created and Ready 20:41:30, C's runs running
    20:41:36 (about 16 s submit to running). PASS.
  - Scale-down: demand fell 20:55:53 (8→6), 20:56:54 (→4), 20:59:42 (→2). 4→3 at 21:00:49
    (300 s after the first drop), 3→2 at 21:01:50 (60 s step). Timing PASS.
  - FINDING: the ReplicaSet removed a BUSY pod while idle pods existed. A5/A6 were stopped by the
    drain after the chart default `drainGraceS: 30` ("the worker is draining; the run was
    stopped"). Prod pins 57600 s, so there the runs finish and the pod waits in Terminating. The
    invariant "scale-down never interrupts a run" needs `drainGraceS` >= the longest run; the
    chart does not enforce it. The pod-deletion-cost follow-up removes most of this risk.
  - 10 runs: 8 ok, 2 stopped by the finding above. The stub refused one `POST /v1/embeddings`;
    runs still passed. Each run made its 24 model calls one at a time (1088 s = 24 x 45 s).
  - Side work: the Colima disk was 100 % full; host build cache (25 GB) and old host images were
    removed. `up.sh` stopped at the aigw migration (disk full); release `aigw` rev 6 is `failed`,
    the old aigw pod still serves.
- **Docs after the walkthrough:** spec infra prerequisite 7 and the chart README now say: pin
  `maxAckPending` to the value the existing consumers have.
- **Sample interval (owner, 2026-11-10, after PR-open):** `runner_demand_sample_s` default 5 s ->
  15 s, one sample per KEDA poll. Stale stays 30 s (= the 2 x floor). Worst-case scale-up reaction
  grows by up to 10 s. The kind walkthrough ran with 5 s.
- **Deviations:** the queue runner exposes `reads_buckets` so the composition root installs the
  sampler only over a queue that can read buckets (review F3). `OME-1869` (PR #1737)
  carried the same shared code and merged first (2026-11-10). This branch rebased onto it: the
  conflicts were `runner_queue.py` (kept `main`'s copy; the file now equals `main`) and the CI
  conformance lists (kept both integration tests).
- **PR #1738 review (sergio-bershadsky, CHANGES_REQUESTED, 2026-11-11):**
  - R1 BLOCKER, fixed: the HPA's cluster-default 10 % tolerance stalls scale-up (3 pods x 4 slots
    at demand 13 = 1.083, no 4th pod; from 10 pods every +1 step is inside the band). The chart
    now renders `behavior.scaleUp.tolerance: "0"` (value `runnerPool.autoscaling.scaleUp.tolerance`,
    default 0, schema number >= 0). Scale-down keeps the cluster default. Needs Kubernetes >= 1.35
    (`HPAConfigurableTolerance` beta); new infra prerequisite 8. Kind proof (k8s 1.37, KEDA 2.20.2,
    dummy pool + static `{"demand": 13}`, target 4): without the field the HPA held 3 (average
    4334m); with it, "New size: 4; reason: ... above target". New test file
    `test_chart_render_runner_scaleup_tolerance_and_drain.py` models the HPA rule at 3x4/13, 8/35 and 9/39.
  - R2, fixed (owner chose the render check): with autoscaling on, the chart refuses
    `drainGraceS < config.jobDeadlineS`. Spec D5 now states the condition. Owner-approved test
    change: the existing file's `_ENABLED` fixture gets drainGraceS 57600 /
    terminationGracePeriodSeconds 57625, and its expected scaleUp dict gets `"tolerance": "0"`
    (`.claude/test-change-approvals/OME-1870.json`).
  - R3, fixed: an all-unbound (or empty) sample now answers 503 `{"status": "unbound"}`, never a
    200 with demand 0. `RunnerDemandSampler.bound()` follows the last sample. A partly unbound
    sample still answers 200. New test file `test_runner_demand_route_unbound.py`.
