# Review fixes — units 1–3

**Status:** approved for implementation (owner, 2026-09-22).
**Input:** six independent reviews of `sf-refactory` (`f09685e0..7251fcec`).
**Rule:** this document is the rubric for the fix round. Each fix has an id (`FX-n`) and
cites the review finding it closes. Each fix starts with a failing test, unless it is marked
*docs* or *chart-render*.

## 1. Owner decisions for this round

| Id | Decision | Source |
|---|---|---|
| RD1 | Identity on the sync surface uses **the same trust model as the ensemble path today**: Envoy's SecurityPolicy sets `X-User-Email`, and the App trusts it. Do not add a new verification step in the App. Document the trust model where the code reads the header. | owner, fix round Q1 |
| RD2 | Readiness is **drain-only**. It fails when the world fails to build and when the pod drains. It does **not** fail under saturation; saturation is handled by `503` + `Retry-After`. `/metrics` moves to its own port with its own NetworkPolicy rule. | owner, fix round Q2 |
| RD3 | The in-flight cap stays **`max_inflight_per_worker × workers`** with one process per pod. `workers` is a multiplier only; document it. | owner, fix round Q3 |
| RD4 | Commits on `sf-refactory`, no Linear issue. | owner, fix round Q4 |

These decisions amend the earlier plan:

- PRD-03 §6, "Gray failure" row: the mitigation changes from "readiness reflects in-flight
  saturation" to "503 shedding plus the in-flight gauge and 503 counter". **Reason:** when a
  busy pod leaves the Service, its load moves to the other pods. That can take all pods out of
  rotation (a cascade).
- test-plan §4, state transitions: *saturated* is still **ready**. *Draining* is **not ready**.
- contracts C1/C2, trust: the App trusts the edge-set `X-User-Email`, as the ensemble path
  does. This is a known, accepted property, not a new gap.

## 2. Design changes that more than one fix uses

### 2.1 A request deadline travels in the request scope

`RequestScope` gains `deadline: float | None` (a `time.monotonic()` value). The sync producer
sets it to `start + request_timeout_s`. The run producer sets `None`. The connector reads it:

- It does not start a transport retry when `deadline - now < backoff + per_attempt_timeout`.
- It gives each attempt a timeout of `min(configured_timeout, deadline - now)`.

**Why:** the retry is the only place that can know "is there time for one more attempt". The
wrapper cannot see it, and a second call that the wrapper then cuts off is billed and useless.

### 2.2 The node tier decides the response after url4 returns

`_SpillSend` only **buffers** (start and body). `NodeTier._dispatch` calls
`await spill.finish()` **after** `inner(...)` returns, so the finish runs **outside** url4's
`asyncio.timeout`. The spill write has its own bound, `spill_timeout_s` (default 4 s). If the
bound expires, the result is `502 artifact_spill_failed`.

The finish also applies the one status remap the sync surface needs: url4 answers `500` for a
permanent `ResolutionError`. On a direct hit, that error always comes from the downstream
(aigateway or a data provider). So a `500` whose `error.code` is **not** a url4 `ErrorCode`
value becomes `502`. A `500` with a url4 code stays `500`.

The timeout ladder becomes:

| Layer | Budget |
|---|---|
| App → node forward | `request_timeout_s + spill_timeout_s + 1` = **35 s** (derived, not a second literal) |
| Node request (url4 wrapper) | **30 s** |
| Node spill write | **4 s**, after the request budget |
| Node → aigateway, per attempt | **min(28 s, time left)** |

### 2.3 A route that matches only known mounts

A catch-all `Mount("/")` is a FULL match for every path. It therefore changes the answer on
existing engine routes (405 becomes url4's 404). Replace it, in both shapes, with one Starlette
`BaseRoute` subclass, `NodeMountRoute`, in `world/serving.py`:

- `matches()` returns `Match.FULL` only when the path is in the known mount set (and, in local
  mode only, when the path equals the eval path). Otherwise it returns `Match.NONE`.
- Starlette then gives its normal answers for everything else: 405 for a wrong method on an
  engine route, 307 for a trailing slash, and the engine's own 404.

The same class carries the ordering assertion. The App and local mode use one install function.

### 2.4 One writer for url4's error envelope

`world/wire.py` holds the ASGI type aliases and one `send_url4_error` function. The node tier,
the forwarder and local mode use it. The control plane may import `world`, so the forwarder can
use it too.

### 2.5 Node pods get their own `instance` label

The App Service and the App Deployment select `{name, instance}`. The node pods also have both,
so the App Service sends public traffic to them. The node pods keep `name: url4-cloud`
(aigateway admits by that name), but use `instance: <release>-node`. Nothing in the App changes.
So there is no selector change on a live object, and no outage on upgrade.

**Risk:** if the aigateway NetworkPolicy outside this repo also matches `instance`, it denies
the node tier's calls. The chart README must state the label set that the node tier needs.

## 3. Fix batches

The batches run in order. B5 changes only chart files, so it can run in parallel with B1–B4.

### B1 — node tier (`world/node_tier*`, `world/connector.py`, `request_scope.py`, `artifacts/signing.py`)

| Fix | Closes | Change |
|---|---|---|
| FX-1 | NT-H1 | Deadline in scope (§2.1); connector retry bound and per-attempt timeout. |
| FX-2 | NT-H2 | Spill runs after url4 returns (§2.2), with its own `spill_timeout_s`. |
| FX-3 | NT-H3 | 500 → 502 remap for non-url4 codes (§2.2). |
| FX-4 | NT-M1, HL-M2 | Drain-only readiness (RD2): not ready once shutdown starts. |
| FX-5 | HL-M1 | `/metrics` on its own port (`URL4_CLOUD_NODE_METRICS_PORT`, default 9110), served by a second uvicorn server or `prometheus_client.start_http_server`. Remove `/metrics` from the mount port. |
| FX-6 | NT-M2 | The per-request log line runs inside `run_scope`, so it carries `origin=sync` and `trace_id`. |
| FX-7 | NT-M3 | Histogram buckets up to 40 s, for example `(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 15, 20, 25, 30, 35, 40)`. |
| FX-8 | NT-M4, SF-7, HL-H1 | `build_node_tier` refuses a filesystem artifact store (`NodeTierError`), unless `allow_local_store=True` (tests and local only). |
| FX-9 | NT-M5 | `build_node_tier` refuses an empty signing key when a store exists; the spill signs **before** it writes. |
| FX-10 | NT-M6, FW-L1 | `verify_artifact_signature` returns `False` for a non-ASCII or non-hex `sig`; it never raises. |
| FX-11 | NT-M9, HL-M5 | The node tier's own hard-cap default is 64 MiB (`NODE_DEFAULT_RESULT_HARD_CAP_BYTES`). Remove the extra body copy. |
| FX-12 | NT-L1 | The wrapper sets `Retry-After` on url4's overload 503 to `retry_after_s`. |
| FX-13 | NT-L3 | `NodeTierSettings.validate()` at boot: fail when `max_inflight < 1`, or when `aigateway_timeout_s >= request_timeout_s`. |
| FX-14 | NT-L4, FW-L2 | `world/wire.py` (§2.4); starlette `Headers` replaces `_CaseInsensitiveHeaders`. |
| FX-15 | NT-L5 | One-phase construction: build the world first, then `NodeTier(...)` with every field. Remove the `assert inner is not None` and the private writes. |
| FX-16 | NT-L6 | A store-construction error marks readiness failed, like every other build error. |
| FX-17 | NT-L7 | A bad `X-Answer-Seed` answers `400` with the engine code `malformed_header`. |
| FX-18 | NT-L9 | The connector logs `model call cancelled` on `CancelledError`, then re-raises. |
| FX-19 | U1-M2 | The connector's logger keeps its pre-refactor name `screamingface_engine.runner.connector`. Restore the test constant to that name. |
| FX-20 | NT-M8 | New T1 variant: the aigateway stub waits on a two-party barrier, so the two requests really overlap. |
| FX-21 | card rule | Split `node_tier.py` (885 lines) into a package, each file ≤ 450 lines: `settings.py`, `metrics.py`, `send.py` (observed + spill), `tier.py`, `serve.py`. Keep the import path `screamingface_engine.world.node_tier`. |
| FX-22 | NT-M7 | *docs*: the module docstring states the trust model (RD1) and names the NetworkPolicy. |
| FX-23 | NT-L2 | *docs*: `workers` is a multiplier (RD3). |

### B2 — App side (`rest/forwarder.py`, `app.py`, `local.py`, `runner/main.py`, `logs.py`)

| Fix | Closes | Change |
|---|---|---|
| FX-30 | FW-H1, SF-2 | Local mode: when the run env's `URL4_CLOUD_EXTRA_MODELS` names a route that the shared node does not serve, the run builds its own per-run world, as before. Use one helper, `world.factory.shared_world_serves(io, env) -> bool`. |
| FX-31 | FW-M1, SF-3 | `NodeMountRoute` (§2.3) replaces `Mount("/")` in the App and in local mode. |
| FX-32 | FW-M3 | One install function for both shapes, and it asserts the order. Remove the `forwarder=` parameter of `create_app`. |
| FX-33 | FW-M2 | `httpx.Timeout(forward, connect=2.0)`. `ConnectTimeout` and `PoolTimeout` take the connection-error branch (one retry, then 503). |
| FX-34 | FW-L3, HL-M3 | The forward budget comes only from `Settings.node_forward_timeout_s`. Remove `FORWARD_TIMEOUT_S`. |
| FX-35 | FW-L4 | Remove `_rewrite_location` and the two prefix parameters. Keep `identity_resolver` as the one test seam; its docstring says so. |
| FX-36 | FW-L5 | Node unreachable: code `upstream_unavailable`, as a named constant. |
| FX-37 | FW-L6 | Drop `server` and `date` from the relayed headers. |
| FX-38 | SF-7, HL-H1 | `_build_artifact_reader` refuses a filesystem store when `node_base_url` is set. |
| FX-39 | U1-M4, SF-5 | `logs.py` prints `origin=` only when it is not `run`. Ensemble log lines are then the same as on `main`. |
| FX-40 | U1-M3 | Restore the pre-refactor order for a malformed `ANSWER_SEED`: parse it before the world is built, keep the empty-world early return, and keep the summary `None`. |
| FX-41 | FW-L9 | *docs*: fix the stale deferred-import comment in `local.py`. |
| FX-42 | FW-L8 | *docs*: C8 lists what local sync calls do not get (no ladder, no fair-share gate on sync calls). |
| FX-43 | FW-M3 test gap | New test: in the deployed shape, `/token`, `/ws`, `/healthz` and `/artifacts/{id}` still reach the engine, and a declared mount reaches the forwarder. |

### B3 — world config and guard (`world/config.py`, `world/factory.py`, `world/serving.py`)

| Fix | Closes | Change |
|---|---|---|
| FX-50 | U2-1 | The guard treats a Starlette `Mount` route as a prefix (`path` and `path + "/…"`). |
| FX-51 | U2-2 | The read-side-only world uses `outbound=StaticIOLayer()` and returns `node.aclose` as its teardown. |
| FX-52 | U2-3 | Reject a `[data]` route under `{eval_path}/` (url4's reserved qualifier namespace). Guard mounts against each other too. |
| FX-53 | U2-4 | Providers: allow only `value` and `file`; the error names the kind from one shared tuple. |
| FX-54 | U2-5 | New AC5 tests: a GET literal (`/healthz`) collision, and an assertion that names both sides. Fix the false wording "the mount would never answer" for method-only overlaps. |
| FX-55 | U2-6 | One `_shelf_label`. `node_mount_paths` and `benchmarks.registry` share one data-route accessor. |
| FX-56 | U2-7 | `serving.py`: `isinstance(io, Url4Node)` instead of duck typing; remove the dead `except ValueError`; no eval-path check for a non-node world. |
| FX-57 | U2-11 | The guard warns (not fails) when a `[holdings]` collection name equals an engine `/v1/<name>` literal. |
| FX-58 | U2-10 | Tests: `file` providers for holdings and identities, and the fallback from a named identity to the default. |

### B4 — unit 1 hardening (`request_scope.py`, tests, `check_layering.py`)

| Fix | Closes | Change |
|---|---|---|
| FX-60 | U1-H1 | New T2 test: `_ModelEndpoint.__slots__` equals an exact allowlist, and a sentinel scan finds no scope value on the handler, the world or module globals after a call. |
| FX-61 | U1-M1 | Keep the autouse scope fixture, and add the marker `no_default_scope` that turns it off. New tests, with the marker, prove each producer binds a scope: the run path, the node tier and local sync. |
| FX-62 | U1-M5 | New test: a url4 fan-out expression (two model calls) under two concurrent run envs; every outbound call carries its parent's identity. |
| FX-63 | U1-M6 | New golden variant with identity and profile in the env; assert the outbound header subset. |
| FX-64 | U1-L1 | One trace carrier. The connector reads the trace from `trace_scope`; the sync producer binds `trace_scope`, not a scope field. |
| FX-65 | U1-L2 | `RequestScope.__post_init__` freezes `identity_headers` with `MappingProxyType`. `cache` is copied with `model_copy()`. |
| FX-66 | U1-L3 | `origin` has no default. |
| FX-67 | U1-L4 | Move `request_scope_from_env` next to its sibling in `request_scope.py`; `runner.main` re-exports it. |
| FX-68 | U1-L5 | The world log line no longer parses the caller's cache policy. |
| FX-69 | U1-L7 | Remove the stale re-export docstring in `runner/executor.py`. |
| FX-70 | U1-L9 | `check_layering.py` exemptions match on the path relative to the package, not the file name. |
| FX-71 | U1-L8 | *docs*: amend the PRD-01 risk row. The layering check covers `src/`; tests are not layered. |

### B5 — chart (`deploy/helm/**`, `verify_chart_wiring.py`, chart tests, chart docs)

| Fix | Closes | Change |
|---|---|---|
| FX-80 | SF-1, HL-C1 | Node pods: `instance: <release>-node` (§2.5). New checks: no Service or Deployment selector matches another Deployment's pod template. |
| FX-81 | HL-H2 | The App pod gets the `checksum/artifact-signing` annotation when the node tier is on. |
| FX-82 | HL-M1, RD2 | Separate `metrics` port (9110), and a second NetworkPolicy ingress rule for it with configurable peers (`node.metrics.scrapeFrom`, default: none). |
| FX-83 | HL-M3 | Render the App's `URL4_CLOUD_NODE_FORWARD_TIMEOUT_S` as `requestTimeoutS + spillTimeoutS + 1`. Render the node's `URL4_CLOUD_NODE_SPILL_TIMEOUT_S`. Template `fail` when `aigatewayTimeoutS >= requestTimeoutS`, or when the grace period is not larger than `preStop + requestTimeoutS + spillTimeoutS`. |
| FX-84 | HL-M4 | The node pod renders `podLabels` **before** the chart-owned labels. |
| FX-85 | HL-M5 | The node pod renders `URL4_CLOUD_RESULT_HARD_CAP_BYTES` from `node.resultHardCapBytes` (default 64 MiB). |
| FX-86 | HL-H1 | Template `fail` when `node.enabled` is true and the artifact backend is not `s3`. `node.enabled` defaults to **false**; `values-cloud.yaml` turns it on. |
| FX-87 | HL-L5 | No duplicate `app.kubernetes.io/component` key on node objects. |
| FX-88 | HL-L9 | A `startupProbe` on `/livez` covers the world build. |
| FX-89 | HL-M7, HL-L1, HL-L10, HL-L11 | *docs*: chart README and NOTES cover the node tier, its label set, S3, the signing key (`existingSecret` for GitOps) and web tools off. Remove the `config_digest`-on-the-node claim. Use `curl --get --data-urlencode` in the example. |
| FX-90 | HL-L7 | Render tests: the NetworkPolicy peer does not match node pods; the App Service does not select node pods. |

## 4. Not in this round

| Item | Why |
|---|---|
| A live NetworkPolicy smoke test (T15) | kind's default CNI does not enforce NetworkPolicy, so a kind test cannot prove it. FX-80 and FX-90 cover the selector logic at render time. A real-cluster check stays an operator step in the chart README. |
| A node-level `401` on a missing identity (NT-M7) | RD1: same trust model as today. The App already refuses a request with no identity. |
| A public url4 API for read-side parsing (U2-8) | It changes `packages/url4`. Record it as a follow-up. |
| Renaming `RunnerRequestError` (U1-L6) | The rename touches many modules and changes nothing at run time. |
| Hiding the mount set from callers with no identity (FW-L11) | The mount names are already public on `/v1/models`. |
| An in-flight gauge that excludes shed requests (NT-L8) | url4 owns admission and the wrapper cannot see it. The gauge help text says "requests inside the tier, including shed ones". |

## 5. Exit criteria

- Every `FX-n` has a test, or is marked *docs* or *chart-render* and is checked by review.
- `uv run .claude/scripts/run_gates.py screamingface-engine` is green.
- The integration suite is green, and `helm lint` passes with the default values and with `values-cloud.yaml`.
- A design review of each batch, against this document, finds no unresolved Critical or High finding.
