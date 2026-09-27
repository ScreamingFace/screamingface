# PRD: Warm child pool

**Source:** prompt, ans:Q1, ans:Q3 · **Priority:** P1 (latency for simple requests; no gate per ans:Q3)
**Lifecycle:** existing (characterize + delta)
**Owner:** unassigned

## 1. Summary and the flows it serves

This is a component PRD. No user flow drives it. It serves every run: async, sync (PRD 02)
and mount calls (PRD 04).

Each worker keeps child processes that are already started: Python has loaded url4 and the
engine, NATS is connected, and the world is built. On a claim, the worker sends the run to a
warm child over a pipe. The child runs **one** run and exits. The worker starts a new warm
child.

## 2. Background and constraints

- "uniform and reliable" `[stated prompt]`
- Scope includes warm children. `[stated ans:Q1]`
- No latency gate. Measure and report only. `[stated ans:Q3]`
- The child process per run is the isolation mechanism: `RLIMIT_AS` per child, a kill that
  always works, a separate env per run. This must not change.
  `[existing worker/exec_wrapper.py:1-26; docs/work/2026-09-02-OME-1089-runner-worker.md:14-20]`
- Entities: RUN_SPEC, WARM_CHILD (`erd.md` §3, §4).

### 2.1 Current behavior

- `_spawn_child` runs `python -m screamingface_engine.worker.exec_wrapper <budget>` with
  `env=_child_env(...)`, stdout and stderr piped. `[existing worker/supervisor.py:730-786]`
- `exec_wrapper` sets `RLIMIT_AS` and `execvpe`s `screamingface-engine run`. `[existing worker/exec_wrapper.py:25-26]`
- The worker forwards child stdout (INFO) and stderr (WARNING) to its log. It does not use
  stdin. `[existing worker/supervisor.py:967-990]`
- `_io_budget()` = `max(1, io_capacity / (active + spawning))`, computed at spawn.
  `[existing worker/supervisor.py:751-766]`
- The hard wall is `deadline_s + stream_grace_s + 30 s`; SIGTERM, then SIGKILL after 10 s.
  `[existing worker/supervisor.py:788-873]`
- `_classify` maps exit results to terminal frames. `[existing worker/supervisor.py:875-933]`
- Child boot: `params_from_env(os.environ)` → `observation_factories(os.environ)` →
  `build_executor(os.environ, ...)` (world not built yet) → traceparent → `JetStreamPublisher`
  → `run_scope` → `run_and_reclaim`. `[existing runner/main.py:614-647]`
- The world is built lazily on the first `execute`. A bad config or an unreachable gateway
  becomes a `Terminated(failed)` frame on the topic. `[existing runner/executor.py:987-1000; runner/main.py:373-376]`
- `request_scope` and trace scope bind inside the run task, not at import.
  `[existing runner/executor.py:844-895]`

**Delta.**

1. New child flag: `screamingface-engine run --warm`. The child does all per-process work,
   then signals READY, then reads one RUN_SPEC from stdin.
2. A control pipe on fd 3 carries `READY` and `ACK` lines. Stdout and stderr keep their log
   role.
3. The supervisor keeps up to `warm_children` warm children (chart value
   `runnerPool.warmChildren`, range 0..workerSlots; chart default 2 since 2026-09-26, the app
   default stays `workerSlots` — owner decision, implementation-notes F7–F11). Idle plus
   running children never exceed `workerSlots` (F8), and a claim takes a warm spawn in flight
   before it spawns its own (F9). With 0, the
   supervisor spawns on claim and still uses the same READY/spec protocol. So there is one
   code path.
4. `io_concurrency` is computed at hand-off.
5. The hard wall starts at hand-off (ACK), not at spawn.

## 3. Scenarios and acceptance criteria

### 3.1 Happy path

- **WC-H1.** Given a worker with 2 free slots and `warmChildren=2`, when it starts, then 2
  children reach `warm` state, and `screamingface_engine_worker_warm_children` reads 2.
  `[stated ans:Q1]`
- **WC-H2.** Given a warm child, when the worker claims a run, then it writes the RUN_SPEC to
  that child's stdin, receives `ACK` on fd 3, and it does **not** start a new process for this
  run. `[stated ans:Q1]`
- **WC-H3.** Given the child finished the run and exited 0, then the worker starts a
  replacement warm child, and the next run goes to a different pid. `[existing OME-1089 isolation]`
- **WC-H4.** Given a warm child, when a run allocates past the `RLIMIT_AS` budget, then the
  child dies alone with 137, the worker publishes `Terminated(failed, oom_killed)`, and the
  other children live. `[existing worker/exec_wrapper.py; test_worker_child_memory_cap.py]`

### 3.2 Error paths

The answers state no error behavior for this component. All error paths are derived (§3.3).

### 3.3 Derived scenarios (risk order)

| ID | Title | Tag | I×L |
|---|---|---|---|
| WC-D1 | The warm phase never reads a per-run key | [proposed — gap §per-element/process-state] | H×H |
| WC-D2 | Child dies after the spec write but before ACK | [proposed — gap §per-connection/sync] | H×M |
| WC-D3 | World build fails during the warm phase | [existing runner/main.py:373] | H×M |
| WC-D4 | Warm child dies while idle | [proposed — gap §per-element] | M×M |
| WC-D5 | Repeated warm failures back off | [proposed — gap §cross-cutting/resilience] | M×M |
| WC-D6 | READY never arrives | [proposed — gap §per-connection/sync] | M×M |
| WC-D7 | Drain kills idle warm children at once | [existing worker/loop.py:204-289] | M×M |
| WC-D8 | Hard wall starts at ACK | [proposed] | M×M |
| WC-D9 | Oversized or malformed RUN_SPEC | [proposed — gap §per-flow/boundary] | M×L |
| WC-D10 | `warmChildren=0` uses the same protocol | [proposed] | M×M |
| WC-D11 | Cancel arrives while the child is assigned but not yet ACKed | [proposed — gap §per-flow/cancel] | M×L |
| WC-D12 | Config change rolls the pool | [existing deploy/helm/templates/deployment-runner.yaml checksum annotations] | L×M |

- **WC-D1.** Given the warm phase runs with a process environment in which every per-run key
  (`job_env.WRITTEN_BY_APP` keys and `IO_CONCURRENCY`) is a sentinel that raises when read,
  when the child boots to READY, then no sentinel is read.
- **WC-D2.** Given the worker wrote a RUN_SPEC, when the child exits before it writes `ACK`,
  then the worker hands the same run to a new child once. If that also fails before ACK, the
  worker publishes `Terminated(failed, spawn_failed)`. The run never runs twice, because no
  code runs before ACK.
- **WC-D3.** Given `url4.toml` names an unreachable gateway, when the warm child builds the
  world, then it still sends `READY` with `world:"error"`. When it receives a RUN_SPEC, then it
  publishes `Started` and `Terminated(failed)` with the build error, as today.
- **WC-D4.** Given a warm child exits while idle, then the worker counts
  `screamingface_engine_worker_warm_spawn_failures_total`, and it starts a replacement.
- **WC-D5.** Given 5 warm spawns in a row fail, then the delay between attempts grows 1 s,
  2 s, 4 s, … up to 30 s. A claim that finds no warm child spawns on demand and waits for READY.
- **WC-D6.** Given READY does not arrive in `warm_ready_timeout_s` (default 60 s), then the
  worker kills the child and counts a warm failure.
- **WC-D7.** Given the worker gets SIGTERM, then it SIGTERMs every idle warm child at once,
  it starts no new warm child, and running children follow today's drain rules.
- **WC-D8.** Given a child sat warm for 10 min, when it receives a run with a 60 s deadline,
  then the hard wall is 60 + 60 + 30 s from ACK, not from spawn.
- **WC-D9.** Given a RUN_SPEC line over 1 MiB, or JSON that does not parse, or
  `spec_version` "3", then the child writes an error on stderr and exits 2 before ACK. The
  worker applies WC-D2 once, then publishes `Terminated(failed, spawn_failed)` or
  `unsupported_spec_version`.
- **WC-D10.** Given `warmChildren=0`, when the worker claims a run, then it spawns a child,
  waits for READY, writes the RUN_SPEC and waits for ACK. The run succeeds.
- **WC-D11.** Given a cancel (`url4.runctl.<topic>`) arrives between spec write and ACK, then
  the worker kills the child, and it publishes `Terminated(stopped, cancelled)` once.
- **WC-D12.** Given the ConfigMap for `url4.toml` changes, then the pod rolls (checksum
  annotation), and every warm child uses the new world.

## 4. Non-functional requirements

- **Latency (report only).** Measure claim → ACK (`handoff`) and spawn → READY (`boot`) in
  phase 0 (cold) and after this PRD (warm). `[stated ans:Q3]`
- **Memory.** Each idle warm child holds a built world. Phase 0 measures its RSS and reports
  `warmChildren × RSS` against the pod memory request. `[proposed]`
- **Observability.** New metrics `[proposed]`:
  - `screamingface_engine_worker_warm_children` (gauge)
  - `screamingface_engine_worker_warm_spawn_failures_total` (counter)
  - `screamingface_engine_worker_handoff_latency_s` (histogram, claim → ACK)
  - `screamingface_engine_worker_child_boot_s` (histogram, spawn → READY)
- **Security.** The RUN_SPEC holds the caller identity and the profile, like today's env. It
  goes over a private pipe, never to a log. A test asserts that the worker never logs the
  RUN_SPEC. `[proposed]`

## 5. Out of scope

- Reusing one child for more than one run. `[existing OME-1089 isolation]`
- Capacity classes or reserved slots. `[stated ans:Q8]`
- A latency gate. `[stated ans:Q3]`

## 6. Open questions

None.

## 7. TDD plan

Order: core-out. The child protocol comes first (its failure modes are the risk), then the
supervisor pool. Linux-only tests keep the `skipif(sys.platform != "linux")` rule of
`test_worker_child_memory_cap.py`, and they run in the kind job (Linux) as well.

| # | Test (RED) | Level | Source | Risk | GREEN note |
|---|---|---|---|---|---|
| WRM-C1 | CHAR `classify_exit_table` (all rows of `_classify`) | unit | [existing supervisor.py:875] | H×M | passes today |
| WRM-C2 | CHAR `child_oom_fails_alone_with_137` | integration (linux) | [existing test_worker_child_memory_cap.py] | H×M | passes today |
| WRM-C3 | CHAR `bad_world_becomes_terminated_failed_on_topic` | unit | [existing runner/main.py:373] | H×M | passes today |
| WRM-C4 | CHAR `runner_pool_rolls_on_config_checksum_change` (chart render: checksum annotation changes when `url4.toml` changes) | unit (chart) | [existing deployment-runner.yaml — WC-D12] | L×M | passes today |
| WRM-1 | `warm_child_sends_ready_then_reads_one_spec_then_exits` | integration | [stated ans:Q1 — WC-H2] | H×H | `run --warm`; fd 3 control pipe; stdin spec |
| WRM-2 | `spec_env_equals_message_env_codec` (property: decode(encode(m)) == m) | unit | [proposed — erd §3] | H×M | one codec for RUN_MESSAGE and RUN_SPEC |
| WRM-3 | `params_from_mapping_matches_params_from_env` | unit | [proposed] | H×M | refactor `params_from_env(os.environ)` to take a mapping |
| WRM-4 | `warm_phase_reads_no_per_run_key` (sentinel env) | unit | [proposed — WC-D1] | H×H | move per-run reads after ACK; `os.environ.update(spec.env)` after ACK |
| WRM-5 | `supervisor_hands_off_to_warm_child_without_exec` | unit | [stated ans:Q1 — WC-H2] | H×H | pool of `WarmChild`; claim uses one |
| WRM-6 | `child_never_reused_after_assignment` | unit | [existing OME-1089 — WC-H3] | H×M | state table: assigned never → warm |
| WRM-7 | `death_before_ack_retries_once_then_spawn_failed` | unit | [proposed — WC-D2] | H×M | retry counter per run |
| WRM-8 | `warm_oom_still_fails_alone` | integration (linux) | [existing — WC-H4] | H×M | `exec_wrapper` unchanged; keep fd 3 inheritable |
| WRM-9 | `world_error_in_warm_phase_surfaces_after_spec` | unit | [existing runner/main.py:373 — WC-D3] | H×M | store the error; publish on spec |
| WRM-10 | `idle_death_counts_failure_and_replaces` | unit | [proposed — WC-D4] | M×M | watch idle `proc.wait()` |
| WRM-11 | `warm_spawn_backoff_1_2_4_to_30s` | unit | [proposed — WC-D5] | M×M | injectable clock |
| WRM-12 | `ready_timeout_kills_child` | unit | [proposed — WC-D6] | M×M | `warm_ready_timeout_s` |
| WRM-13 | `drain_kills_idle_warm_children_first` | unit | [existing loop.py:204 — WC-D7] | M×M | hook in the drain event |
| WRM-14 | `hard_wall_counts_from_ack` | unit | [proposed — WC-D8] | M×M | start timer at ACK |
| WRM-15 | `bad_spec_exits_2_before_ack` (size, JSON, version) | unit | [proposed — WC-D9] | M×L | bounded `readline(1 MiB)` |
| WRM-16 | `zero_warm_children_uses_same_protocol` | unit | [proposed — WC-D10] | M×M | spawn → READY → spec |
| WRM-17 | `cancel_between_spec_and_ack_stops_once` | unit | [proposed — WC-D11] | M×L | cancel handler knows `assigned` state |
| WRM-18 | `io_concurrency_computed_at_handoff` | unit | [proposed] | L×M | move `_io_budget()` call |
| WRM-19 | `run_spec_never_logged` | unit | [proposed — §4 security] | M×L | no log call with spec content |
| WRM-20 | `warm_metrics_exposed` | unit | [proposed — §4] | L×M | `worker/metrics.py` |
| WRM-21 | `chart_renders_warm_children_and_bounds` | unit (chart render) | [proposed] | L×M | `runnerPool.warmChildren`, schema 0..workerSlots |

**Refactor notes.** Keep `_classify` untouched. Put the READY/ACK protocol in one small
module that both sides import, so the line format has one owner. Put it at
`screamingface_engine/child_protocol.py` with stdlib imports only: the run child must not
import `worker/` (it pulls in the serving half), and `check_layering.py` must accept the new
module in both categories.
