# OME-1064 — Implementation plan: Runner Job capacity

Spec: `docs/spec/2026-09-01-OME-1064-runner-capacity-admission.md`

Six units. Each is one Linear issue, one branch, one PR. Units 1 and 2 are independent and
can run in parallel; unit 4 must merge with or after unit 3; unit 6 is blocked on unit 3.

---

## Unit 1 — `OME-1059` · Surface un-startable Runner Jobs (engine)

**Ship first.** No infrastructure dependency, and it alone removes the silence.

### Files

- `apps/screamingface-engine/src/screamingface_engine/adapters/k8s.py` — `_map_status`,
  `_terminal_status`, `_read`
- `packages/url4/src/url4/streaming/interfaces/jobs.py` — extend the `JobStatus` literal
- `apps/screamingface-engine/src/screamingface_engine/ws/bridge.py` or the run supervisor —
  producer-side watchdog
- `apps/screamingface-engine/src/screamingface_engine/config.py` — `run_start_grace_s`
- `apps/screamingface-engine/deploy/helm/` — expose the grace as a chart value

### Approach

1. Add an `unschedulable` member to `JobStatus`. Every `match`/branch over `JobStatus` must be
   updated — pyright will list them; treat that list as the blast radius.
2. `_read` currently reads only the Job. To distinguish the two shapes it must also see the
   Pod (label selector `RUNNER_LABELS`) or the Job's events. Prefer the **Pod**: one list call,
   no event-TTL dependency. A Pod in `Pending` with condition
   `type=PodScheduled, status=False, reason=Unschedulable` → `unschedulable`. **No Pod at all**
   past a short grace, with the Job still active, is the quota case → also `unschedulable`.
3. Watchdog: per attached topic, if zero frames have been published after `run_start_grace_s`
   (default 120s), call `status()`; on `unschedulable`, publish a typed `ai.url4.error`
   (`run_unschedulable`, carrying the Kubernetes reason string) and terminate the run.

### Tests (RED first)

- `_map_status` returns `unschedulable` for a Pending+Unschedulable Pod.
- `_map_status` returns `unschedulable` for an active Job with no Pod past the grace.
- `_map_status` still returns `scheduled` for an active Job whose Pod exists and is Pending
  **within** the grace — the N5 regression guard.
- Watchdog publishes the typed error and terminates, via the existing fake
  `BatchV1JobsClient` seam.
- A run producing frames normally is never failed by the watchdog.

### Risks

Widening `JobStatus` touches the shared `packages/url4` port, so it fans out into every
adapter (`inprocess`, mocks, test doubles). Land the port change and the adapter updates in
one commit so no intermediate state fails typecheck.

---

## Unit 2 — `OME-1067` · Narrow the disconnect blast radius (SDK)

Independent. Highest value per line changed.

### Files

- `packages/screamingface/src/screamingface/_engine/transport.py` — `cancel_active`,
  `_sweep_after_disconnect` (sync `:240-281`, async `:350-371`, `:484-493`)
- `packages/screamingface/src/screamingface/_evaluation/runner.py` — the failure branches at
  `:382-389` and `:416-427`

### Approach

Split one method into two intents: `cancel_run(token)` for a single lost stream, and the
existing sweep for client shutdown / explicit abort. `_sweep_after_disconnect` calls the
former with only the affected token. Guard: never cancel a run already in a terminal state.

### Tests (RED first)

- One stream lost past its budget fails exactly one candidate; siblings complete.
- A candidate already terminal is not cancelled by a sibling's disconnect.
- Explicit abort still stops every owned run — pins the existing guarantee.
- Report distinguishes "stream failed" from "aborted".

---

## Unit 3 — `OME-1065` · Quota-aware admission (engine)

### Files

- `apps/screamingface-engine/src/screamingface_engine/adapters/k8s.py` — `_schedule_blocking`
- new `apps/screamingface-engine/src/screamingface_engine/adapters/quota.py` — the reader and
  the fit calculation
- `apps/screamingface-engine/src/screamingface_engine/adapters/factory.py` — wiring
- `apps/screamingface-engine/deploy/helm/templates/` — Role gains `get`/`watch` on
  `resourcequotas`

### Approach

1. `QuotaHeadroom` reads the namespace ResourceQuota (`status.used` / `status.hard`), cached
   ~2s behind a monotonic clock. Injected as a port so tests need no cluster.
2. The Pod's charge is computed from the **rendered manifest** plus LimitRange defaults —
   derive it from `_manifest()` rather than restating the numbers, so the two cannot drift.
   The runner sets no `limits.cpu`; the LimitRange supplies 500m. Omitting this makes the
   arithmetic wrong by 500m per Pod.
3. Reservation counter: increment on admit, decrement when the run reaches a terminal state or
   is stopped. Compare `used + reserved + this_pod` against `hard`.
4. Not fitting on **any** constrained dimension → raise `JobRunnerAtCapacity(active, limit)`.
   The REST edge already maps it (`rest/routes.py:198-208`); no change there.
5. Any failure to read the quota (absent, RBAC denied, API error) → log once and proceed as
   today. Unit 1's detection is the backstop.

### Tests (RED first)

- At the ceiling → `JobRunnerAtCapacity`; REST returns 503 with `Retry-After`.
- Below the ceiling → 202 and the Job is created byte-identically to today (N1).
- A Pod spec omitting `limits.cpu` is charged the LimitRange default, not zero.
- Each of the five dimensions binds independently.
- Concurrent `schedule()` calls between refreshes cannot jointly overshoot.
- Quota unreadable → schedule proceeds, no exception escapes.
- Reservation is released on terminal status and on `stop()`.

### Risks

The reservation counter is the subtle part: a leaked reservation permanently reduces capacity.
Tie release to the same lifecycle hook that already drives run teardown rather than adding a
parallel path, and add a reconciliation against observed quota usage on each refresh.

---

## Unit 4 — `OME-1066` · Honour 503 backpressure (SDK)

**Merges with or after Unit 3.** Alone it is untestable against a real Engine.

### Files

- `packages/screamingface/src/screamingface/_engine/transport.py` — submission path
  (`:596-613` sync, `:661-678` async), `permanent` at `:872`, retry ladder at `:40`
- `packages/screamingface/src/screamingface/_evaluation/runner.py` — queued-state progress
- SDK settings — the wait budget

### Approach

1. Parse `Retry-After` (delta-seconds); absent or unparseable → existing full-jitter
   `_reconnect_delay` (`:72-77`).
2. Retry under a **total wait budget**, not an attempt count — a queued run may legitimately
   wait minutes behind a large evaluation. Configurable; expiry raises an error naming cluster
   capacity.
3. Waiting for capacity must not trigger `cancel_active()` (depends on Unit 2's split).
4. Emit a queued state so `progress=True` shows *queued*, not apparent hang. This is what
   distinguishes the fix from the bug.

### Tests (RED first)

- 503 + `Retry-After: 5` → retries after ~5s.
- 503 without the header → jittered backoff.
- Budget expiry → error naming capacity, not a generic transport failure.
- A waiting candidate does not cancel siblings.
- Non-503 5xx keeps today's behaviour.
- Progress surface shows queued.

---

## Unit 5 — `OME-1058` · Capacity (infra repo, owner decision)

Lands in `OpenMined/infrastructure`, not this monorepo. Blocked on an owner decision between
the three options in the issue. Recommendation on the issue: enable user-pool autoscaling
**and** rely on Unit 3 for demand bounding; treat a second node as a later throughput decision
taken on evidence.

Also update the `docs/ledger.md` deferral trigger, which is stated in node **memory** terms
while both real signals were **CPU**.

---

## Unit 6 — `OME-908` · Fair ordering (engine)

Blocked on Unit 3. After admission exists, order the queue per identity (the Engine already
receives `identity` on `schedule()`). Re-measure gateway per-provider contention at that point;
it was not the constraint in this incident.

---

## Gates

Per unit, in its own worktree and branch `OME-N-<desc>`:

```
uv run ruff check && uv run pyright && uv run pytest
```

Engine and SDK units run their own path-filtered CI lane
(`screamingface-engine-tests.yml`, `screamingface-tests.yml`). Unit 1 also touches
`packages/url4`, so `url4-tests.yml` gates it too. Unit 3 touches the Helm chart, so
`charts.yml` gates it as well.

## Verification of the whole epic

Reproduce the incident shape: two concurrent evaluations against `sf-fusion` at its current
ceiling. Expected after units 1–4: the second evaluation reports queued candidates and
completes, or fails with a message naming capacity — never a silent stall, and never a
sibling-induced failure of completed work.
