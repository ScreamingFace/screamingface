# Test plan: uniform executor

Cross-cutting test strategy. Each PRD owns its own TDD table. This file gives the rules, the
risk model, the environments, the measurement harness and the exit criteria for each phase.

## 1. Risk model (highest first)

| ID | Risk | Impact | Likelihood | Owner PRD | Main tests |
|---|---|---|---|---|---|
| R1 | Clients see sequence gaps in the shared stream and fail runs | H | H | 01 | EVT-C1, EVT-1..EVT-6 |
| R2 | A mount call reaches the eval path (D1 broken) | H | L | 04 | MNT-1, MNT-7, MNT-20 |
| R3 | A run executes twice (warm hand-off retry, redelivery) | H | M | 03, 04 | WRM-7, MNT-26 |
| R4 | One run's OOM kills other runs after the warm change | H | M | 03 | WRM-C2, WRM-8 |
| R5 | The reaper stops a run that a sync caller waits for | H | H | 02 | SYN-2 |
| R6 | Mount status codes change for existing callers | H | M | 04 | MNT-C2, MNT-9 |
| R7 | Warm phase reads per-run data (wrong identity or profile for a run) | H | M | 03 | WRM-4 |
| R8 | The events store fills and drops frames of live runs | M | M | 01 | EVT-11, EVT-12 |
| R9 | `/openapi.json` misses mounts | M | M | 04 | MNT-18, MNT-19 |
| R10 | Node tier removal breaks the chart or the signing secret | M | L | 05 | DEC-2, DEC-3 |

## 2. TDD ground rules (for the implementing agent)

- **RED first.** Write the test. Run it. See it fail **for the right reason**: an assertion on
  the missing behavior, not an import error or a broken fixture. A test that passes at once
  proves nothing. Fix the test.
- **GREEN minimal.** Make the smallest change that passes. Do not build ahead of the next test.
- **REFACTOR on green only.** Keep every test green.
- **CHAR tests first** on existing code. They pass on today's code by design. They are the
  safety net, not a RED step. Commit them before the first delta test.
- One behavior per test. The test name states the behavior.
- Never weaken an assertion, add a sleep or retry, or skip a test to get green. If a test is
  flaky, suspect a real race first.
- The expected value in a test comes from the PRD, the `erd.md` invariants, or a CHAR table.
  It never comes from the output of the code under test.

## 3. Test levels

| Level | What | Where | Needs |
|---|---|---|---|
| unit | logic, invariants, route order, state tables | `tests/unit/` | nothing |
| unit (url4) | `dispatch_direct`, `describe_routes` | `packages/url4/tests/` | nothing |
| unit (chart) | `helm template` render asserts | `tests/unit/test_chart_render_*.py` | `helm` |
| integration | real JetStream, real child processes, fake gateway | `tests/integration/` | NATS at `URL4_CLOUD_TEST_NATS_URL` (default `nats://localhost:4222`, JetStream on). Tests skip when NATS is not reachable. `[existing tests/integration/test_worker_spine.py:27-46]` |
| integration (linux) | `RLIMIT_AS` behavior | `tests/integration/` | Linux; `skipif(sys.platform != "linux")` `[existing test_worker_child_memory_cap.py:31-36]` |
| e2e (kind) | whole chart on a local cluster, chaos | `tests/kind/` (new) | kind, kubectl, helm, docker `[stated ans:Q4]` |

Local NATS for integration: `docker run -d --name nats-js -p 4222:4222 nats:2.10-alpine -js`.
`[existing .github/workflows/screamingface-engine-tests.yml conformance job]`

## 4. Quality gates (every phase)

Run from `apps/screamingface-engine/`: `[existing .claude/sdlc.local.md:71-82]`

```sh
uv run ruff check && uv run ruff format --check
uv run pyright
python3 ../../.claude/scripts/check_layering.py
uv run pytest --cov=screamingface_engine --cov=url4.streaming --cov-fail-under=80 -q
```

For `packages/url4` changes, also run that package's own test command.
Chart: `helm lint deploy/helm` and the chart-render tests.

## 5. Kind environment (new) `[stated ans:Q4]`

**Location.** `apps/screamingface-engine/deploy/kind/` `[proposed]`

| File | Content |
|---|---|
| `kind-config.yaml` | one control-plane node, one worker node; `extraPortMappings` not needed (port-forward) |
| `values-kind.yaml` | engine chart values: `config.runner=queue`, `runnerPool.replicas=2`, `runnerPool.workerSlots=2`, `runnerPool.warmChildren=2`, bundled `nats.enabled=true` with `nats.fullnameOverride`, bundled `garage.enabled=true` and `artifactStorage.backend=s3`, a fixed `artifactSigning.signingKey`, the chart value that sets `URL4_CLOUD_AIGATEWAY_BASE_URL` pointed at `http://aigw-stub:8080` (find the key in `deploy/helm/values.yaml`; do not invent one), and a `url4.toml` with two stub models, one endpoint mount and one data mount |
| `aigw-stub/` | a small FastAPI app + Dockerfile. `POST /v1/chat/completions` returns a fixed completion with an `_aigw.usage_accounting` block. Env `STUB_LATENCY_MS` (default 200) and header `X-Stub-Fail: 429|500|hang` for fault injection. `GET /v1/models` returns the two stub models. |
| `up.sh` | create the cluster; build and `kind load` the engine, benchmark and stub images; `helm install` the stub and the engine; wait for rollout |
| `down.sh` | delete the cluster |

**Test runner.** `tests/kind/` with pytest marker `kind` (add it to `pyproject.toml`). A
fixture port-forwards the App Service. Tests use `httpx` and `websockets`. Chaos uses
`kubectl`. `[proposed]`

**Kind suite (must be green for the parity gate):**

| ID | Case | PRD |
|---|---|---|
| K1 | Async run with WebSocket: frames 1..n, no gap, result | 01 |
| K2 | Sync `GET /?q=` with no WebSocket → 200 | 02 |
| K3 | Mount call → 200; `/openapi.json` lists both mounts | 04 |
| K4 | Mount call with a 1.5 MiB stub reply → 303 → artifact fetch 200 | 04 |
| K5 | Mount call with `X-Stub-Fail: hang` → 504 and `Terminated(stopped)` on the subject | 04 |
| K6 | 50 concurrent mixed runs → every subject gap-free; no per-topic stream exists | 01 |
| K7 | Kill one runner pod during a run → redelivery → one terminal frame | 01, 03 |
| K8 | A run that allocates past its budget → `oom_killed`; its siblings finish | 03 |
| K9 | `kubectl rollout restart` of the runner pool during runs → drain; idle warm children die first | 03 |
| K10 | Restart the NATS pod during a run → gap-free frames, or `failed/stream_failed` | 01 |
| K11 | the new App deletes a legacy stream at startup after an upgrade from the previous chart version (was: `purge-legacy-streams` after a drained upgrade; changed 2026-09-27, D7) | 01 |
| K12 | Events store near full (small `events.maxBytes`) → gauge > 0.8 | 01 |

**CI.** Add an optional job `kind-e2e` to `.github/workflows/screamingface-engine-tests.yml`,
started by label `run-kind` and by a nightly schedule. It does not block every PR, because a
kind job takes minutes. `[proposed]`

## 6. Measurement harness (report only) `[stated ans:Q3]`

**Tool.** `apps/screamingface-engine/scripts/bench/sync_latency.py` `[proposed]`. It runs
against the kind port-forward with `STUB_LATENCY_MS=200`.

**Cases.**

| Case | Path | When |
|---|---|---|
| B1 | mount call through the node tier (`node.enabled=true`) | phase 0 only (baseline) |
| B2 | `GET /?q=` sync single-model, cold spawn | phase 0 |
| B3 | `GET /?q=` sync single-model, warm children | after PRD 03 |
| B4 | mount call as a direct run, warm children | after PRD 04 |

Each case: 300 sequential requests, then 300 at concurrency 8. Record p50, p95, p99, max, and
the error count. Also record: frames per run for an 8-model ensemble expression (to check
`events.maxMsgsPerSubject`), the RSS of one idle warm child, and
`worker_handoff_latency_s` / `worker_child_boot_s` from `/metrics`.

**Output.** `docs/plans/uniform-executor/measurements/<YYYY-MM-DD>-<case>.md` with the raw
JSON next to it. The numbers block nothing. `[stated ans:Q3]`

## 7. Phases and exit criteria

The implementing agent works in this order. Each phase ends with every quality gate green.

| Phase | Work | Exit criteria |
|---|---|---|
| 0 | Kind environment (§5), measurement harness (§6), baseline B1 and B2, all CHAR tests of PRD 01–05 | kind `up.sh` works from a clean machine; B1/B2 reports exist; every CHAR test green on the current code |
| 1 | PRD 01 shared events stream | all EVT tests green; K1, K6, K10, K11, K12 green |
| 2 | PRD 02 sync without WebSocket | all SYN tests green; K2 green |
| 3 | PRD 03 warm child pool | all WRM tests green; K7, K8, K9 green; B3 report exists |
| 4 | PRD 04 mount call as direct run (url4 API first) | all MNT tests green; K3, K4, K5 green; B4 report exists |
| 5 | PRD 05 parity gate, then removal | DEC-1 passes on the gate record; removal merged; DEC-2..DEC-8 green; the whole kind suite green |

**Stop rules.** Stop and ask the owner when: a CHAR test shows behavior that contradicts a
PRD; a GREEN step needs a change outside the files a PRD names; MNT-8 shows that url4 cannot
report a direct call without a DAG; or the parity gate needs a "not applicable" row with no
clear reason.

## 8. Test index (counts)

| PRD | CHAR | Delta tests | Scenarios (H/E/D) |
|---|---|---|---|
| 01 shared events stream | 3 | 19 | 4 / 3 / 13 |
| 02 sync without WebSocket | 3 | 11 | 3 / 3 / 7 |
| 03 warm child pool | 4 | 21 | 4 / 0 / 12 |
| 04 mount call as direct run | 4 | 26 | 5 / 3 / 14 |
| 05 node tier decommission | 1 | 9 | 2 / 1 / 6 |

## 9. Not tested (with owner and revisit condition)

| Item | Reason | Detection in production | Revisit when |
|---|---|---|---|
| More than one App replica | out of scope (ans:Q1) | the chart pins 1 replica | the OME-890 NATS interest gate is planned |
| Real provider latency | stub gateway only | `worker_handoff_latency_s`, `mount_calls_total` | the first aks-dev deploy |
| JetStream with more than 1 replica | kind runs single-node NATS | NATS server metrics | `events.replicas > 1` is set in an environment |
| macOS `RLIMIT_AS` | Linux-only tests | n/a (production is Linux) | never |
