# OME-908 — Fair scheduling of concurrent Engine runs

- **Linear:** https://linear.app/openmined/issue/OME-908/fair-schedule-concurrent-engine-runs-so-one-large-benchmark-run-doesnt
- **Landing:** `apps/screamingface-engine`
- **Status:** approved and implemented. The owner approved this spec in session on 2026-08-26
  (decision points resolved below); implementation is PR #750. Post-approval amendments are
  dated inline.
- **Related:** OME-907 (cache prefill misses on first-time runs), OME-931 (sequential Case
  admission — the origin of the per-Case serial shape), OME-886 (gateway admission telemetry).

## Problem

Reported by Irina: one full DRACO run blocks a second concurrent run. The second run makes
little or no progress until the first run drains. Full DRACO is about 20,000 model calls.

Verified facts (file and line as of 2026-08-26):

1. **One run presents a standing, wide queue.**
   - DRACO runs 100 Cases. The shared protocol admits Cases one at a time
     (`benchmarks/protocol.py:101`, `concurrency=1`, from OME-931).
   - Inside a Case, the criteria map runs 8 rows by default (`url4.dag.nodes.DEFAULT_MAP_CONCURRENCY = 8`).
     Each row holds 5 judge calls in parallel (`JUDGE_PASSES = 5`, `draco/exam.py:211` and
     `draco/definition.py:95`).
   - The engine passes no run-wide I/O cap, so URL4 clips the run at its default of 32
     concurrent fetches (`url4.dag.DEFAULT_RUN_CONCURRENCY = 32`; the engine calls
     `url4.dag.run(url4, self._io, observer=bridge)` with no `concurrency` argument,
     `runner/executor.py:751-758`).
   - So one DRACO run keeps up to 32 gateway requests in flight for the whole grading phase.
     The judge is `openrouter/google/gemini-3.1-pro-preview` (`draco/exam.py:49`). Every judge
     call therefore lands on one provider key: `openrouter`.

2. **The bottleneck is one small FIFO queue.**
   - The gateway admits at most `AIGW_PROVIDER_MAX_CONCURRENCY = 4` concurrent calls per
     provider (`aigateway/config.py:111`).
   - The limit is one `asyncio.Semaphore` per provider, on `app.state`
     (`aigateway/core/concurrency.py:76-105`). Waiters wake in FIFO order. The slot is held
     across the overload-retry loop (`aigateway/routes/chat_dispatch.py:172`).
   - Two concurrent DRACO runs demand 64 in-flight calls against 4 slots: 16:1 oversubscription
     on one FIFO queue.

3. **The gateway cannot be fair by itself today.**
   - No request field says which run a call belongs to. The queue has no class to be fair to.
   - The engine, in contrast, owns run identity: it admits runs (`InProcessJobRunner`,
     `DEFAULT_MAX_CONCURRENT_RUNS = 32`, `adapters/inprocess.py:47`) and serializes each run's
     env for its runner.

4. **Secondary amplifiers (mode dependent).**
   - The engine's gateway client times out at `AigatewayConfig.timeout_s` — 60 s by default
     (`runner/connector.py:66`) but 600 s in the deployed `url4.toml` (`url4.toml:52`).
   - URL4 classifies a timeout as transient and retries (`url4/peer/server.py:495`); judge calls
     retry twice (`draco/exam.py:216`, `retry=2`). A retry joins the back of the FIFO queue,
     behind the other run's fresh calls. On the deployed 600 s timeout this rarely fires; on a
     60 s configuration it converts "slow" into "no progress".
   - Cache hits do not contend: a hit returns at the gateway's cache stage, before any provider
     slot is acquired (`aigateway/routes/chat.py:292-345`). OME-907 says first-time runs miss
     the prefill, so cold runs pay full contention.

5. **One alternative locus is not yet excluded.**
   - In the k8s mode, each run is its own Job. Runner resources are injectable
     (`adapters/k8s.py:353`). If the cluster fits only one benchmark Job at a time, run B sits
     `Pending` until run A's Job exits. That failure looks identical to queue starvation from
     the caller's seat. The first work item must separate the two (Layer 0 below).

Concurrency classification (naming the shapes): starvation under a FIFO queue with no
per-class state; oversubscribed producer-consumer against a bounded downstream; a retry loop
that re-joins the back of the queue (a livelock risk when the client timeout is short).

## Fairness promise (what this design commits to)

- Let `C` be the downstream call capacity the engine controls, and `N` the count of active runs.
- Each active run can hold at least `C / N` in-flight downstream calls.
- Capacity not used by one run flows to runs that demand it (work-conserving).
- One active run can use all of `C`. A solo run is not slower than today.
- The fairness unit is one run (one topic). All runs have equal weight in this version.
- Not promised: per-user quotas, priority lanes, completion-time ordering, and cross-process
  exactness in k8s mode (see Limits).

## Design space (what was considered)

| # | Option | Named pattern | Verdict for V1 |
|---|---|---|---|
| 1 | Engine fair scheduler over run dispatch | Max-min fair share at the edges | **Adopted**, split by mode (below) |
| 2 | Per-run fair share of provider slots at the gateway | Fair queueing (per-class) | **Adopted as companion ticket**, not in this unit |
| 3 | Aging / anti-starvation on the FIFO | Bounded wait via aging | Rejected: keeps the queue class-less; option 1 is smaller and stronger |
| 4 | Chunked yielding by large runs | Cooperative yield | Subsumed by option 1 (a budget is a continuous yield) |
| 5 | QoS lanes (batch vs interactive) | Priority classes | Deferred: a product decision, needs product input |
| 6 | Raise the ceiling (overrides, workers) | Capacity increase | Complementary ops action; not fairness; bounded by the upstream account |
| 7 | Cache prefill (OME-907) | Demand reduction | Complementary; a hit bypasses the queue entirely; tracked in OME-907 |
| 8 | Distributed fair queue | Shared-state scheduler | Deferred: no multi-replica need today; revisit with scale-out |

Why engine-side shaping is enough for a first fix: with per-run budgets `b_i`, a FIFO server
gives each run a share near `b_i / Σ b`. Two DRACO runs with equal budgets get near 50/50
service even though the queue itself stays FIFO. The gateway companion (option 2) then makes
the share exact and work-conserving at the true bottleneck. The gateway already receives the
caller identity header on every engine call (`runner/connector.py:_headers`), so the companion
needs no new contract — only a fair waiter queue keyed by an existing header.

## Recommended design — three layers

### Layer 0 — measure, then confirm the locus (must run first)

The Linear issue requires this and the analysis above agrees.

- Engine side: per-run downstream dispatch counters (in-flight, granted, waiting, timeouts,
  retries) surfaced through the existing run telemetry (`screamingface_engine.metrics`,
  span events). Cheap: one counter set on the run's I/O wrapper.
- Ops side (no code): a checklist run against the hosted cluster —
  1. count gateway pods and uvicorn workers (each process holds its own semaphores; the math
     changes with the product);
  2. inspect runner Job `Pending` events and resource quota during a two-run experiment;
  3. read openrouter 429 and Retry-After rates for the window.
- Exit condition: the experiment shows run B's calls waiting at the gateway semaphore (not a
  Pending Job, not quota). If the locus is cluster capacity, this ticket stops and the fix is
  runner resources or quota (ops), not scheduling.

### Layer 1 — per-run downstream budget (this unit's implementation)

One mechanism, two modes, at the seams both runners already share: per-run env.

**New env contract.** `job_env.URL4_CLOUD_IO_CONCURRENCY` (integer, optional). When set, the
run executes `url4.dag.run(..., concurrency=<value>)`. When absent, the run keeps today's
behavior (URL4 default 32). This is a run-scoped knob, so it follows the same path as
`URL4_CLOUD_EXTRA_MODELS` and the cache policy env: written by the runner adapter at schedule
time, read by `runner/main.build_executor`, applied by `Url4Executor`.

**K8s mode — static budget.** `Settings.runner_io_concurrency` (int, default 16). The
`K8sJobRunner` writes it into each Job's env. Rationale for 16: four times the default 4-slot
ceiling, so one provider stays saturated with headroom for cache hits and for runs that touch
two or three providers. A static budget is not work-conserving across Job completions: capacity
freed by a finished Job is reclaimed only by runs that start later. That limit is accepted for
V1 and is the reason Layer 2 exists.

**Local mode — dynamic, work-conserving.** `InProcessJobRunner` owns one shared
`FairShareGate` with capacity `Settings.local_io_capacity` (default 32). Each run's executor
receives an I/O wrapper that asks the gate for a permit per fetch, instead of URL4's per-run
`BoundedIOLayer`. The gate is a fewest-in-flight scheduler over active runs (each grant goes to the waiting
run holding the fewest permits, ties by the least-recently-served run with the tie line rotating on
every grant — equal-weight max-min fairness; amended 2026-08-26: an earlier draft named this
"deficit-round-robin", which is a different mechanism — no deficit counters exist; amended 2026-08-27
after PR review: a fixed arrival tie-break starves a later run whenever an earlier run's wait queue
never empties — the benchmark-backlog shape this spec exists to protect — so each grant now sends the
run to the back of the tie line):

- Permit grant is a synchronous critical section (no `await` between check and grant — the same
  discipline `url4.dag.executor._run` documents for its memo table).
- A permit is held only across the fetch itself, never across compile or scope building.
- A waiter cancelled while queued is removed from its run's queue; the next waiter is woken
  (no lost wakeup). A waiter cancelled in the instant after its grant — `set_result` has
  run, `Task.cancel` lands before the resume — unwinds into `CancelledError` instead of
  taking ownership, and that unwind returns the permit (added 2026-08-27 after PR review:
  the original text assumed a done future's refusing `cancel()` meant the task would
  resume with the grant; asyncio defers the cancellation via `_must_cancel` instead).
- A permit is released in a `finally` on every path: success, error, cancellation.
- When a run finishes or is stopped, its queue entry and permits are released at once; its
  unused share is available to the remaining runs immediately.
- Cache-hit-heavy runs still consume permits (hits pass through the wrapper), which is correct:
  permits bound total downstream pressure, and a solo run still gets the full capacity.

With capacity 32 and two active runs, each run is bounded near 16 in flight; a solo run gets
all 32 — the same ceiling it has today. Equal weights only; the gate takes no weight input in
V1 (a weight field is a deliberate non-goal until a product need exists).

### Layer 2 — gateway fair semaphore (companion ticket, out of this unit)

Replace the per-provider FIFO `asyncio.Semaphore` with a round-robin waiter queue keyed by the
caller identity header the gateway already reads, plus per-class slot-wait telemetry. Exact
work-conserving max-min at the bottleneck; works for every engine replica; no contract change.
A separate ticket per the cross-cutting rule (one sub-issue per app) — the ticket text is
drafted in the work ledger (2026-08-26), filing pending the owner (Linear writes are
owner/MCP actions). This unit does not touch `apps/aigateway`.

### Layer 3 — ops guidance (documentation only in this unit)

Document in the engine chart and README:

- `AIGW_PROVIDER_MAX_CONCURRENCY_OVERRIDES` already exists for per-provider ceilings
  (`aigateway/config.py:118`). An `openrouter` raise is an owner decision bounded by the
  account's real limits.
- Runner resources must let at least two benchmark Jobs co-schedule, or Layer 1 is moot.
- `timeout_s` in `url4.toml` should stay far above the worst fair-share wait (see math below).

## Capacity math (why the numbers are what they are)

- Downstream slots per gateway process: 4 (default). With `W` gateway processes the effective
  ceiling is `4W`.
- Cold full DRACO: ~20,000 judge calls. At `S = 10..30 s` per call and 4 slots, a solo run
  needs `20000 × S / 4 ≈ 14..42 h`. The run deadline is 16 h (`Settings.job_deadline_s`,
  `config.py:103`). So a cold solo run is already near the deadline at the slow end. This has
  two consequences: (a) fairness must not slow a solo run — Layer 1 is work-conserving for
  exactly this reason; (b) OME-907's prefill matters more than any scheduler, because a hit
  skips the queue entirely.
- Worst fair wait per call, two equal runs, 16 in flight each, 4 slots, `S = 30 s`: about
  `(32 / 4) × S = 240 s`. Below the deployed 600 s timeout with margin; above a 60 s local
  default if a deployment lowers it. The spec therefore pins `timeout_s` guidance in Layer 3.

## Invariants (the contract tests pin)

1. A run's permit count never exceeds its fair share while other runs wait.
2. A solo run reaches full capacity (work-conserving).
3. A completed or stopped run releases its share before the next event is processed.
4. No permit is held across anything but a fetch.
5. Absence of the new env leaves `url4.dag.run` behavior byte-identical to today.
6. Run admission (32) and Case admission (`concurrency=1`) are unchanged.
7. The gate introduces no cross-run ordering: each run's URL4 expression, results, and
   revisions are untouched. This is an operational scheduling choice, like OME-931 — benchmark
   revisions do not move.

## Test strategy

- **Gate unit tests (deterministic, event-driven):** contending fake fetches under a fixed
  capacity; assert service-count ratios within bounds; solo run saturates; cancelled waiter
  removed and successor woken; error path releases the permit; run completion hands the share
  over on the next admission decision.
- **Plumbing tests:** env present → `url4_run` receives the value; env absent → the call shape
  is unchanged (pin the kwarg absence); `K8sJobRunner` manifest carries the env on every Job
  (amended 2026-08-26, implementation review: `runner_io_concurrency` is a required setting
  with default 16, so no "unset" branch exists — and an explicit entry on every Job beats a
  stale `envFrom` copy, the same invariant `EXTRA_MODELS` carries); local mode injects the
  shared gate; deployed mode does not.
- **Integration (local spine):** two in-process runs through the mock gateway with a slow
  endpoint; both progress concurrently and both complete; a solo run's completion order and
  frame counts stay unchanged against a recorded baseline.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine`.

## Decision points for the design session

- **D0 — locus:** accept the Layer 0 exit condition, or redirect to ops (cluster capacity).
- **D1 — default on:** ship Layer 1 enabled by default (k8s 16, local 32 dynamic), or behind
  `None` (off) for one release. This spec recommends on, with one setting to revert.
- **D2 — the 16:** confirm or adjust after Layer 0 numbers (openrouter override and worker
  count move it).
- **D3 — deadline:** whether cold full DRACO at the slow end justifies a batch deadline bump
  or depends on OME-907 instead.
- **D4 — companion split:** approve the gateway fair-semaphore sub-ticket (cross-cutting rule:
  one epic, one sub-issue per app).
- **D5 — weights:** confirm equal weights for V1.

## Out of scope

- Any `apps/aigateway` code (Layer 2 is a separate ticket).
- QoS lanes, per-user caps, priorities, weighted tenants.
- A cross-process scheduler (option 8) and any change to `packages/url4`.
- Benchmark revisions, Case admission order, and the Client's 8-candidate fan-out.

## Acceptance criteria

1. Layer 0 evidence exists (counters plus the ops checklist) and names the locus.
2. Two concurrent local runs each hold a bounded, near-equal share of downstream calls, and
   both complete; the invariant tests pass deterministically.
3. A solo local run's dispatch ceiling and completion behavior are unchanged from main.
4. K8s Jobs carry `URL4_CLOUD_IO_CONCURRENCY` on every Job. (Amended 2026-08-26,
   implementation review: the setting is required with default 16, so "when unset" is
   unreachable — and an explicit entry on every Job is what keeps a stale ConfigMap copy from
   reaching a Job through `envFrom`.)
5. The full `screamingface-engine` gate suite passes.
6. The companion ticket and the ops note exist before this unit closes.

## Decisions (D0–D5) — recorded 2026-08-26

The owner approved this spec in session on 2026-08-26. The resolutions below are recorded
from that approval and the implementation review:

- **D0 — locus:** the code-level analysis (Problem §1–4) was accepted as the locus evidence;
  the ops checklist was not run. Residual: if the symptom recurs, run the Layer 0 checklist
  before re-touching the scheduler.
- **D1 — default on:** Layer 1 ships enabled (k8s 16 static, local 32 dynamic), with one
  setting to revert (`config.runnerIoConcurrency: 32`).
- **D2 — the 16:** confirmed from the code-verified capacity math; revisit alongside the D0
  residual if openrouter overrides or gateway worker counts change.
- **D3 — deadline:** no batch deadline bump; consequence (b) holds — OME-907 prefill is the
  lever that matters at the slow end.
- **D4 — companion split:** approved; ticket text drafted in the work ledger, filing pending
  the owner.
- **D5 — weights:** equal weights for V1.

## Acceptance criteria — resolution (recorded 2026-08-26)

1. Met by equivalent evidence: the verified code analysis names the locus; dispatch counters
   shipped totals-only (`screamingface_engine_fair_share_*`) — per-run labels were dropped
   for cardinality discipline (topics are unbounded and mintable), and timeout/retry counters
   plus span events were not added. The ops checklist is the D0 residual above.
2. Met: `test_fair_share_gate.py` (14 invariants) and the two-run interleave test in
   `test_runner_io_concurrency.py` pin it deterministically.
3. Met at the dispatch-ceiling level (solo saturation is pinned at gate level and through the
   executor pair); the plan's recorded-baseline frame pin was not implemented — deviation
   recorded in the work ledger. A solo run's path differs from main only by the wrapper's
   permit acquire/release around each fetch.
4. Amended — see the criterion above (unconditional write).
5. Met: the full gate suite is green (the two in-place test modifications carry an explicit
   owner approval, recorded in the work ledger).
6. Partial: the ops note exists (engine README "Fair scheduling"; chart runner-block comment
   added 2026-08-26); the companion ticket is drafted, not yet filed (owner action).
