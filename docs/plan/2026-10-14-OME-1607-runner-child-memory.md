# OME-1607: runs fit their slot for every benchmark kind, and every worker terminal ends the client run

Status: built on one branch at the owner's request (2026-10-14: "fix all the problems in a single
worktree/branch"), so the three-PR stack below became one branch. Decisions taken during the
build are in §6.
Refs: OME-1607 under OME-1314. Spec: `docs/spec/2026-10-14-OME-1607-run-scheduling-memory.md`.
Branch / worktree: `OME-1607-runner-child-memory` / `.claude/worktrees/runner-child-memory`.
Landing: `screamingface-engine` only (code + chart). No `OpenMined/infrastructure` change: Kargo
advances the image pin (ADR-0008) and the chart defaults apply to dev and prod.

## 1. Shape of the delivery

Three PRs in one stack, smallest risk first, so prod gets relief from PR 1 alone:

| PR | Units | Effect alone |
|---|---|---|
| 1 | U1, U2 | clients stop hanging; `draco-3pass` fits the current 2 GiB cap (measured) |
| 2 | U3, U4 | Run memory depends on seats, not on Cases × calls |
| 3 | U5, U6, U7 | one memory knob per slot, resident-memory limit with a clear error, admission = claiming, measured sizing |

Every unit is test-first (RED, then GREEN), then `run_gates.py screamingface-engine`. Existing
tests are not edited (append-only gate); new behavior gets new tests.

## 2. Units

### U1 — every worker terminal frame ends the client run (E3, R4)

- Add an engine constant `ROOT_NODE = "root"` beside the runner's call of
  `url4.streaming.lifecycle.run`, and pass it explicitly there (`node=ROOT_NODE`), so the child and
  the supervisor share one name.
- `worker/supervisor.py:_publish_terminal`: `source=source_for(topic, ROOT_NODE)`.
- Tests (new):
  - Every supervisor-written terminal (`cancelled`, unsupported spec, `queue_expired`, launch
    failure, each `_classify` outcome) has `source == source_for(topic, ROOT_NODE)`.
  - The child's own lifecycle frames and the supervisor frame have the same source (one run, one
    root).
- Not here: E5 (no root frame before start) is SDK behavior → follow-up (`client-sf`).

### U2 — runner children do not reserve unused address space (E1, R7)

- `deploy/helm/templates/configmap-runner-env.yaml`: `ARROW_DEFAULT_MEMORY_POOL=system`,
  `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, with the measured WHY.
  Children inherit the worker env (`warm_pool.py:97-106`, `supervisor.py:201-219`).
- Tests (new):
  - Chart render: the four keys are in the runner env ConfigMap with these values.
  - Linux-only (skips off Linux, like `test_worker_child_memory_cap.py`): a child started through
    the exec wrapper with the runner env, under a 1 GiB `RLIMIT_AS`, imports numpy and pyarrow and
    builds an Arrow table without `MemoryError`.

### U3 — Case grading holds only the Cases in its seats (E2, R1)

`shared_grading/benchmark_aggregation.py:_concurrent_case_results` (Stage 4a/4b). Keep every
behavior its docstring states: results in roll-call order; a raising Case cancels every later Case
before it gives up its seat; no judge call starts after a failure; cancel of the run cancels all.

- Do not create one Task per Case up front. Run at most `seats` Cases plus a small reorder window;
  drop each Task as soon as its result is handed over.
- Give each Case its own inspect Transcript and release it when the Case ends
  (`inspect_ai.log._transcript.init_transcript`), so judge `ModelEvent`s die with their Case. The
  engine never reads inspect transcripts; confirm with a grep before the change.
- Tests (new), with a fake judge that records a large prompt per call:
  - After N Cases, live `ModelEvent`/`Transcript` objects (weakrefs) are ≤ seats + window, for
    N = 10 and N = 100 (the bound does not grow with N).
  - Roll-call order, raise-cancels-later, and run-cancel behavior are unchanged (existing tests
    stay green; add one for the windowed path).

### U4 — per-call accounting does not grow with the Run (E13)

- Pin the owner of the per-call `OperationAccounting`/`OperationUsage`/`OperationCache` objects
  with a referrer test (first suspect: `grading_accounting._Registry`, `grading_accounting.py:42-50`).
- If the Run needs only totals, fold each call into running totals and drop the per-call object.
  If per-call records are part of an output (Report, capture), keep them but compact (no pydantic
  model per call). Decide from the reader, not the writer.
- Test (new): live per-call accounting objects after N calls do not grow with N (or the record
  size per call is bounded and stated).

### U5 — one memory value per slot, enforced on resident memory (E4, R2, R3, R7)

- Chart: `runnerPool.perRunCharge.memoryLimitMi` stays the ONE per-slot number. Derive from it:
  - `URL4_CLOUD_WORKER_MEMORY_BUDGET_BYTES` = the resident limit per child (new meaning: RSS);
  - a new `URL4_CLOUD_WORKER_ADDRESS_SPACE_BYTES` = `RLIMIT_AS` backstop, a stated multiple of
    the resident limit (runaway allocation still dies alone, WC-H4), default 4×;
  - the pod limit (unchanged formula).
  Schema: minimum and a render `fail` if the backstop is below the resident limit.
- Supervisor: a watchdog reads each child's resident memory (`/proc/<pid>/status` VmRSS, or
  PSS from `smaps_rollup`) every 2 s. Above the limit: SIGTERM, `KILL_GRACE_S`, SIGKILL; classify
  `failed / memory_budget_exceeded`, permanent, message names the limit and
  `runnerPool.perRunCharge.memoryLimitMi`. Ack (no redelivery).
- Supervisor: a child that exits non-zero after printing `MemoryError` on stderr (the drain at
  `supervisor.py:1101-1124` already reads it) is classified `memory_budget_exceeded` too, so the
  `RLIMIT_AS` path and the watchdog path report the same cause. The existing test that expects
  `CHILD_EXITED` for its fake child is kept as is (its child prints no `MemoryError` trace); if it
  would change, stop and ask the owner (append-only gate).
- Tests (new): watchdog kills an over-limit fake child, sibling finishes (K8 shape), terminal frame
  code + root source; config/env derivation; chart render and schema failure cases.

### U6 — admission and claiming agree on per-user parallelism (E7, R5)

- Chart: render `URL4_CLOUD_RUN_QUEUE_CALLER_INFLIGHT_CAP` for the App. Default: equal to the
  effective per-caller claim allowance (`runnerPool.maxAckPending`, or its derived value);
  overridable; render `fail` when the cap is above the allowance (Runs the App admits that no
  worker may claim).
- Tests (new): chart render for pinned, derived and overridden values; the failing combination.

### U7 — measured sizing per benchmark kind (R6)

- A repeatable measurement script (kind cluster, keyless replay of recorded URL4 runs, per-child
  RSS/VSZ sampler, per-pod cgroup `memory.current`) under
  `apps/screamingface-engine/docs/plans/uniform-executor/measurements/`.
- Matrix, before and after PR 2, recorded as a dated measurement doc:

  | Scenario | Proves |
  |---|---|
  | `inspect-gsm8k limit=2` | base footprint, no regression |
  | `draco-3pass` 100 Cases | peak does not grow with Cases × calls |
  | `draco` (5 passes) | the longest judged Run fits |
  | an `early_result` Benchmark (IFEval or HealthBench) | per-Case grading path |
  | a multi-attempt Benchmark (`arc_agi_2`) | sibling Attempts inside one Case |
  | one user, `maxAckPending` Runs at once | per-user parallelism, queueing |
  | several users, every slot busy with judged Runs | pod limit holds at full load |
  | a Run forced over its limit | `memory_budget_exceeded`, siblings finish, client ends |

- Set the `perRunCharge` defaults from the measured peak plus a stated margin, and write the
  derivation in `values.yaml`. Tell the infra owners if the per-pod limit changes (their
  `sf-fusion` quota is sized against it), before merge.

## 3. Verification (whole stack)

- `run_gates.py screamingface-engine` and the chart lint/template CI job, per PR.
- On the local kind cluster (`SF_REPO=<worktree> ~/sf-kind/up.sh`): the U7 matrix; acceptance =
  every scenario completes with the chart defaults, the forced breach ends the client run with
  `memory_budget_exceeded`, and no pod restarts.
- Design review of each PR against this plan before it is opened.

## 4. Risks

- U3 touches the cancellation semantics of judged grading (paid calls). Mitigation: keep the
  existing tests green and add the windowed cases; the windowed design must not start a judge
  call after a failure.
- U5 changes the meaning of `URL4_CLOUD_WORKER_MEMORY_BUDGET_BYTES` (virtual → resident). It is
  not set anywhere today except the code default; the new address-space variable keeps the old
  safety property.
- If U7 measures a peak above the current per-slot limit, the pod limit grows and the infra quota
  (`sf-fusion` ResourceQuota) must grow first.

## 5. Follow-ups to propose under OME-1314 (not in this stack)

Memory-aware claiming (E6); per-Case checkpoint and streaming aggregate (E12); bucket collisions
(E8); dynamic IO share (E9); orphan children (E10); SDK pre-start terminal error (E5, `client-sf`);
url4 `iterate` up-front Tasks in the Case phase (`url4-engine`, measure first).

## 6. Decisions taken during the build (2026-10-14)

- **One branch, not three PRs** — the owner's instruction. The commits keep the unit order.
- **U1 — runs that never started keep the transport source.** An existing test pins it
  (`test_worker_claim.py`, queue expiry), and it is correct: no child published a root, so there is
  no root node to name. Only frames for runs whose child started use `RUN_ROOT_NODE`.
- **U4 — kept as is, bounded and stated.** The per-call record is the run's cost-attribution
  ledger (`capture_request_accounting`, payload-free by design). Measured: 2.8 KB per call
  (27 MiB per 10,000 judge calls; `draco` 5-pass ≈ 33 MiB). Restructuring the cost join for that
  is not worth the risk to cost reporting. Revisit if a Benchmark passes ~100k calls per run.
- **U5 — the address-space path keeps `child_exited`.** `test_worker_child_memory_cap.py` (Linux)
  pins the code; the message now names `MemoryError` and the limit. The new resident watch is the
  path that reports `memory_budget_exceeded` (permanent).
- **U6 — dropped.** The SDK waits at most 900 s for admission (`_ADMISSION_BUDGET_S`); `draco`
  runs take 15–38 min. Capping the App's per-caller admission at the queue allowance (prod 4)
  would make a user's 5th–8th Candidate fail after 15 min instead of waiting in the queue and
  running. The queue is the right place to wait; its claim deadline is 16 h.
- **U2 — no Linux-only "import pyarrow under RLIMIT_AS" unit test.** pyarrow arrives with the
  `inspect` extra, which the gate install does not have, so the test would always skip. The kind
  measurement (U7) exercises the real path instead.

### After the branch review (2026-10-14)

- **U3 redesigned on the review's advice.** The first build bounded memory with a start WINDOW
  ahead of the clerk; that cost throughput when one Case is slow and added a path that could
  start a Case after a raise. The shipped design keeps the original scheduling (every Case's task
  started up front, seats bound the hook) and RELEASES each task the moment it finishes — a
  done-callback hands its outcome to the Case's future and drops the task with its context. Same
  memory bound; a new test pins "no Case enters the hook after a raise".
- **Memory watch hardened:** a `/proc` read that raises is an unknown reading, never a kill.
- **Root source also for a redelivered pre-start frame and every failed launch** (the first
  delivery's child, or a raced ACK, may have published the root).
- **Operators see memory stops:** a warning per breach and `terminals_total{code}`.
- **`addressSpaceFactor` default 2** (the code's long-standing 2 GiB at the 1 Gi charge).
- **U7 measured** — `apps/screamingface-engine/docs/plans/uniform-executor/measurements/2026-10-14-OME-1607-run-memory.md`:
  `draco-3pass` peaks at 444 MiB resident / 849 MiB address space with the chart defaults (was:
  died at 459 / 2,045); 4 judged runs at once keep each pod under 790 of 2,304 MiB.
- **Owner-approved append-only exception:** tests created earlier on this branch were updated;
  no test from main changed (gate green with `--base origin/main`).

### Found while verifying, not in this branch (follow-ups)

- **Span times use the wall clock** (`runner/executor.py:405, 579`). On the Colima VM the clock
  was stepped back ~0.11 s every 10 s; a span open across a step got `end < start`, and SDK 0.1.3
  rejects that span and aborts the whole `evaluate` (the run itself succeeded). Engine: end =
  start + a monotonic duration. SDK (`client-sf`): do not abort an evaluation on one bad
  observability span.
- `adapters/max_deliveries.py` publishes `Terminated(max_deliveries)` with the transport source —
  the same client hang as U1 when a delivery's child had published its root.
- From the spec: memory-aware claiming (E6), per-Case checkpoint (E12), bucket collisions (E8),
  dynamic IO share (E9), orphan children (E10), SDK pre-start terminal wording (E5).
