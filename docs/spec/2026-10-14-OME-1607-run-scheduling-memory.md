# Run scheduling and run memory: how it works, where it breaks (OME-1607)

Status: draft for owner review, 2026-10-14.
Refs: OME-1607 (task) under OME-1314 (E23 · platform capacity).
Plan: `docs/plan/2026-10-14-OME-1607-runner-child-memory.md`.

## 1. Problem

On aks-dev and aks-prod, large judged benchmark runs (`draco-3pass`: 100 Cases, about 7,400 judge
calls) die in the runner child with `MemoryError`, and the notebook then shows "waiting" forever.
Each user can run several evaluations in parallel, the parallelism is set per deployment, and the
benchmark kinds differ by about 1,000× in model calls. A fix must hold for every configuration and
every benchmark kind, not only for `draco-3pass`.

## 2. How a run is scheduled today

| Layer | What happens | Bound | Where |
|---|---|---|---|
| SDK | `sf.evaluate` starts one Run per Candidate; at most 8 in flight; a 503 is retried (3 tries, `Retry-After` ≤ 30 s) | `_MAX_CANDIDATES_IN_FLIGHT = 8` | `_evaluation/runner.py:72`, `_core/retry.py:38-46` |
| App admission | Token, identity, WebSocket attach (async needs one, else 428), duplicate topic (409), then `_admit_or_raise`: fleet queue depth and per-caller in-flight cap, else 503 | depth 10,000; caller cap 8 (not in the chart) | `adapters/queue_runner.py:590-635`, `rest/routes.py:705-830` |
| Queue | WorkQueue stream `url4-runq`; caller hashed into 16 buckets; one durable pull consumer per bucket; explicit ack; `ack_wait` 60 s; `max_deliver` 2 | `max_ack_pending` per bucket (prod pins 4) | `runner_queue.py:71-173, 471-503` |
| Worker claim | A pod pulls `slots − active` messages, round-robin over buckets, 2 per visit | `workerSlots` (4) | `worker/loop.py:263-313`, `runner_queue.py:480-482, 797` |
| Warm pool | Idle + running children ≤ slots; READY 60 s, ACK 10 s; one retry before ACK | `warmChildren` | `worker/warm_pool.py:163-437` |
| Supervisor | One child per Run; heartbeat `in_progress`; hard wall = deadline + grace; classify exit; publish a terminal frame if the child did not; then ack | `RLIMIT_AS` 2 GiB per child | `worker/supervisor.py:354-1169`, `worker/exec_wrapper.py:25` |
| IO share | Child IO budget = `max(1, capacity // (active + spawning))`, fixed at spawn | `worker_io_capacity` 4 | `worker/supervisor.py:904-919` |
| Inside the Run | Cases run one at a time (`iterate`, concurrency 1); every Case result is kept and passed to the aggregate as one array; judged Benchmarks mark Cases in the aggregate with 4 seats | `CASE_GRADING_CONCURRENCY = 4` | `benchmarks/protocol.py:269-300`, `shared_grading/benchmark_aggregation.py:99, 404-440` |
| Pod resources | request = slots × 256 Mi + 128 Mi + warm excess; limit = slots × 1 Gi + 256 Mi (4,352 Mi); no CPU limit | chart `runnerPool.*` | `templates/deployment-runner.yaml:252-259` |

The per-run charge (1 Gi) was copied from the old Runner Job. It was never measured on a real
workload; the only measurements are an idle child and no-model probe runs
(`uniform-executor/implementation-notes.md:274, 290-292`).

Deployed (`OpenMined/infrastructure`, dev = prod): 2 runner pods × 4 slots, `maxAckPending: 4`,
chart defaults for memory, tenant nodes `D4as_v5` (dev, 4 CPU) and `D8as_v7` (prod, 8 CPU).

## 3. Measured evidence (local kind, exact replay of a failing `draco-3pass` run)

All replays were cache hits through a keyless identity (no spend). Memory was sampled every second
per child process.

1. **Address-space reservations exhaust `RLIMIT_AS`.** At run start VSZ goes 218 → 1,884 MiB in
   3 s while RSS is about 300 MiB. The cause is two reservations that are never used: pyarrow's
   default pool (mimalloc) reserves a 1,024 MiB arena on its first allocation, and numpy/OpenBLAS
   reserves about 32 MiB per node CPU (192 MiB on 6 CPUs; about 256 MiB on prod nodes). The run
   died at VSZ 2,045 MiB with RSS 459 MiB. With `ARROW_DEFAULT_MEMORY_POOL=system` and
   `OPENBLAS_NUM_THREADS=1` the same imports take 339 MiB instead of 1,566 MiB, and the run
   succeeds.
2. **Live memory grows with every judge call.** RSS grows about 3.5–4 MiB/s (about 35 KB per
   call) until the end. glibc `mallinfo2` shows the growth is memory IN USE (107 → 226 MiB), not
   fragmentation (free-but-held stays 5–30 MiB); glibc tuning (`MALLOC_ARENA_MAX`, mmap/trim
   thresholds) did not change the slope. Live GC objects grow 274k → 618k, with one
   `GenerateConfig`, `ChatMessage…`, `OperationUsage`, `OperationCache` and `OperationAccounting`
   per model call. The referrer chain is
   `GenerateConfig → inspect ModelEvent → inspect Transcript._events → contextvars Context`.
   Cause: `benchmark_aggregation.py:427` creates one asyncio Task per Case up front and keeps the
   `tasks` list for the whole aggregate. Each finished Task keeps its Context; the Context keeps
   the inspect Transcript that inspect created lazily in that Task (the engine never binds one);
   the Transcript keeps every judge `ModelEvent`, each with the full report prompt.
   `INSPECT_TRANSCRIPT_BOUNDED=1` does not help: it keeps the last 100 events per Transcript, and
   one Case has fewer than 100.
3. **The client never learns that the child died.** The supervisor's terminal frame uses
   `source_for(topic)` = `/trace/<topic>` (`worker/supervisor.py:1143`). The SDK ends a Run only
   on a `Terminated` from the root node `/trace/<topic>/node/root` (`_engine/contract.py:295`).
   The failed frame is in NATS; the SDK ignores it.

## 4. Edge cases found

| # | Edge case | Effect today | Severity |
|---|---|---|---|
| E1 | Native libraries reserve address space (mimalloc 1 GiB, OpenBLAS per CPU) | `RLIMIT_AS` is mostly gone before work starts; worse on bigger nodes | high (prod outage cause) |
| E2 | Aggregate keeps every Case Task and its inspect Transcript | peak memory = Cases × judge calls × prompt size | high |
| E3 | Supervisor terminal frame has the transport source | client hangs on `child_exited`, `oom_killed`, `killed`, `timed_out`, `worker_draining` (every rollout) and a stop of a running Run | high |
| E4 | `MemoryError` kills the child's own NATS reader | the child cannot publish its terminal; only the supervisor frame (E3) exists; exit 1 is reported as `child_exited`, not as memory | medium |
| E5 | Pre-start terminal (queue expiry, launch failure, cancel while queued) | SDK raises "run root was never identified (URL4 mismatch)", a misleading error | medium |
| E6 | Memory is not part of claiming; slots are equal-weight | 4 heavy Runs on one pod can exceed the pod limit; a cgroup OOM kills the largest child (or the worker) | high once E1/E2 are fixed less often, but still possible |
| E7 | App caller cap (8) > `maxAckPending` (prod 4) | 4 admitted Runs wait unclaimed; the claim-time deadline counts the queue wait | medium |
| E8 | 16 buckets, caller hashed | two callers in one bucket share one allowance; at the 30-user target collisions are certain | medium |
| E9 | IO share fixed at spawn | the first Run keeps the full budget after siblings arrive; pod IO is oversubscribed | low |
| E10 | No death signal for children | a worker crash leaves orphan children running while the Run is redelivered | low |
| E11 | Slow child start (CPU pressure, tracing) | READY timeout 60 s → spawn failure → the claim keeps retrying (observed with a diagnostic) | low |
| E12 | A crash loses the whole Run | no per-Case checkpoint; a redelivery or rerun starts at Case 1 | medium (time, not money: cache) |
| E13 | Several structures hold one record per model call for the Run (`OperationAccounting` etc.) | small per call, but grows with calls | low |

## 5. Requirements for the fix

R1. A Run's peak memory depends on the work in flight (seats, IO budget), not on the number of
Cases or judge calls. A `draco` (5 passes) Run and an `inspect-gsm8k limit=2` Run both fit one slot.

R2. The per-child limit counts memory that is used (resident), not address space that is reserved,
and it is set from ONE chart value per slot, so every derived number (pod limit, child limit,
quota math) stays consistent when `workerSlots`, `replicas` or `maxAckPending` change.

R3. A Run that exceeds its limit dies alone, ends on the client with a specific, permanent error
(`memory_budget_exceeded`, naming the limit and the chart value), and is not redelivered.

R4. Every terminal frame the worker writes ends the Run on the client.

R5. Admission and claiming agree on the per-user parallelism: a Run the App admits is a Run a
worker may claim.

R6. Each benchmark kind has a measured peak per slot, recorded with the method, so the chart
default is evidence, not a copy.

R7. No change to the executor's isolation invariants (one child per Run, kill-always, WC-H4: an
over-budget Run dies alone and its siblings finish).

## 6. Out of scope (proposed follow-ups under OME-1314)

- Memory- or weight-aware claiming (E6): a pod claims a heavy Run only with free headroom.
- Per-Case checkpoint and streaming aggregate (E12).
- Fairness without bucket collisions (E8).
- Dynamic IO share (E9) and orphan handling (E10, `PR_SET_PDEATHSIG`).
- SDK: a clear error for a pre-start terminal (E5, `client-sf` landing).
- url4 `iterate` creates every row Task up front (`packages/url4/.../iteration.py:85-115`); measure
  whether the Case phase of inspect-solver Benchmarks retains the same way (`url4-engine` landing).
