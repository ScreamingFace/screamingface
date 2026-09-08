---
ticket: OME-1119
stack: screamingface-engine
status: done
started: 2026-09-07
finished: 2026-09-07
---

# OME-1119 — Propagate the traceparent from the engine to aigateway

## Intent

Rung 2 of the correlation ladder. `OME-967` made the client originate a traceparent and the
engine already **adopts** it — the control plane forwards it into the runner as
`job_env.TRACEPARENT` (`adapters/k8s.py:591`, `adapters/inprocess.py:155`) and the run's own
frames carry it. But the engine sends **nothing onward**: the header set aigateway received
during the audit was `Host, Accept, Accept-Encoding, Connection, User-Agent, X-User-Email,
X-Profile, Content-Length, Content-Type` — no `traceparent`, on any of three client paths.

The consequence is that the trace stops at the engine. A user quoting the `trace_id` from
`CandidateResult` (`OME-1121`) can find the engine's half of the story and nothing about the
model calls, which is where the interesting failures live.

## Design decisions

**D1 — There are TWO trace sources here, not one.** The issue reads as though one mechanism
covers all three client paths. It does not:

- `runner/connector.py` is **run mode**. Its trace is the run's `TraceContext`, computed by
  `url4.streaming.lifecycle.run` and handed to `Url4Executor.execute(url4, trace=root_ctx)`.
- `catalog/aigateway.py` and `rest/routes.py` are **control plane**, serving inbound HTTP.
  There is no run and no `TraceContext`; their trace is whatever the **inbound request**
  carried.

Treating them alike would mean inventing a run context for the control plane or reaching for
a global. They get the same header, from two different origins, and the ledger says so because
the code will look asymmetric to a reviewer who expects one helper.

**D2 — The run's id comes from `TraceContext`, NOT from `logs.RunContext.trace_id`.** This is
the trap in this unit. `logs.py` already has exactly the shape wanted — `run_scope(topic,
trace_id)` bound around the whole run, `current_run_context()` to read it — and using it would
be one line. It is wrong:

```python
# runner/main.py:477
trace_id = parse_traceparent(traceparent)   # None when the caller sent none
with run_scope(params.topic, trace_id):
```

When the caller sends no traceparent, `lifecycle.run` **mints** one (`secrets.token_hex(16)`,
`lifecycle.py:201`) and that minted id never reaches `RunContext`. Reading `RunContext` would
therefore send a traceparent for client-originated runs — making rung 2 pass — and silently
send none for every other run. A hole shaped exactly like a passing test.

`lifecycle.run` computes the authoritative id in both cases and passes it to
`executor.execute`. That is the source.

**D3 — A ContextVar bound in `execute`, not a constructor parameter.** `Url4Executor` caches
its world: `_resolve_world` is `if self._io is None and self._world_factory is not None`, so
`build_aigateway_world` runs **once per executor**, and in serve mode one executor serves many
runs. Threading the trace through `world_factory` → `build_aigateway_world` →
`_ModelEndpoint` would park a per-run value on a process-shared object — precisely the defect
`build_aigateway_world`'s own docstring warns about for `cache`:

> `cfg` is the world, one description of the gateway shared by every run in the process, and a
> per-run value there is a value one run reads out of another's.

A ContextVar is read at *request* time rather than *build* time, so world caching stays
correct and the value cannot outlive its run. It also matches the idiom this exact call site
already uses — `current_retrieval_policy()` at `connector.py:198` and
`operation_call_identity(...)` at `:203`, alongside `model_outcomes`, `grading_accounting`,
`operation_calls` and `logs` itself. Six existing ContextVars; this is the house pattern.

**D4 — The outbound span id is the run's `root_span_id`, not a per-call mint.** W3C says the
`traceparent`'s span-id is the caller's *current* span, and OTel HTTP instrumentation mints a
fresh client span per request. Doing that here would emit a span id that **no exporter ever
publishes**, so once `OME-1130` makes spans real the gateway's parent pointer would dangle.
`root_span_id` is a span `lifecycle` genuinely publishes (`StartedEvent` rides it). Attaching
the per-node span — which `_trace_fields` already resolves for frames — is a Phase 2 concern
and is recorded as a follow-up rather than guessed at now. The rung asserts the trace id half,
which is identical either way.

**D5 — `/v1/providers` also gains `X-Profile`.** Called out in the issue and kept in scope: it
is the same header-assembly defect in the same function, and splitting it would mean touching
that code twice.

## Planned changes

- `src/screamingface_engine/runner/trace_scope.py` (new) — the ContextVar plus
  `run_trace_scope(trace)` / `current_traceparent()`. Its own module rather than a new export
  from `logs.py`: `logs` is the *logging* layer, and a header source parked there would be
  imported by the connector for a value that has nothing to do with logging.
- `src/screamingface_engine/runner/executor.py` — bind the scope in `execute` around the run.
- `src/screamingface_engine/runner/connector.py` — `_headers()` adds `traceparent` when bound.
- `src/screamingface_engine/catalog/aigateway.py` — `_headers(credential)` adds it from the
  inbound request's trace.
- `src/screamingface_engine/rest/routes.py` — the connections path forwards the inbound
  traceparent, plus the missing `X-Profile` (D5).
- `packages/screamingface/tests/e2e/test_correlation_chain.py` — delete rung 2's strict-xfail
  marker. **Trips the append-only gate**, as every rung PR does; see the note below.

## Test plan

RED first, engine-side unit tests before the e2e rung:

- `_headers()` renders a well-formed `traceparent` carrying the bound run's trace id.
- Outside any run scope it renders **no** `traceparent` key at all — not an empty string, not
  a zero id. The control plane must stay byte-identical.
- The id is the run's, not a fresh one: two calls inside one scope carry the same trace id.
- Two sequential runs on ONE cached executor carry **different** trace ids — the regression D3
  exists to prevent, and the one a constructor parameter would fail.
- A run whose caller sent NO inbound traceparent still propagates the minted id — the D2 hole,
  asserted directly rather than inferred.
- `X-Profile` is written after the inbound identity mapping and cannot be displaced by it
  (the existing INVARIANT at `connector.py:796`, re-asserted for the new key).
- The catalog and connections paths each send it from the inbound request.
- Rung 2 of the ladder passes; rungs 3, 4a, 4b stay strict xfails.

## Acceptance

- All three client paths send a `traceparent` carrying the run's / request's own trace id.
- No traceparent is emitted outside a trace scope.
- Rung 2 green, rungs 3/4a/4b still xfail.
- `run_gates.py screamingface-engine` green; the `screamingface` ladder run green.

## Known process consequence

Deleting rung 2's marker modifies a prior test, so the append-only gate flags
`test_correlation_chain.py` — inherent to the ladder from `OME-1105`, and the third PR to hit
it. Raised for a once-and-for-all decision rather than re-approved silently.

## Adjacent finding — NOT fixed here

`run_scope` binds `trace_id=None` for any run whose caller sent no traceparent (D2), so those
runs' process log lines carry `topic=` but no `trace_id=` even though the run has one. That is
`OME-940`'s territory (rung 4a — engine logs the trace id), and fixing it here would widen this
unit past its rung. Recorded on `OME-940` rather than left in a ledger nobody re-reads.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `trace_scope.py` (new), `runner/executor.py`, `runner/connector.py`,
  `connections/port.py`, `connections/aigateway.py`, `rest/connections.py`,
  `catalog/aigateway.py` (comment only), `tests/unit/test_traceparent_propagation.py` (new,
  17 tests), the ladder, ledger + mirror.
- **Commits:** `feat(screamingface-engine): propagate the run's traceparent to aigateway`
  (sha at squash-merge).
- **Gates:** `run_gates.py screamingface-engine` — **ALL GREEN** (append-only, ruff, ruff
  format, pyright, check_layering, `pytest --cov --cov-fail-under=80`): **2366 passed, 5
  skipped**. `run_gates.py screamingface --skip-append-only` — **ALL GREEN**.
  The ladder against the real engine + real aigateway: **2 passed, 3 xfailed** — rung 2
  flipped green, rungs 3/4a/4b still fail as designed.
- **Deviations:**
  - **The scope binds inside `_drive`, not around `execute`'s `yield` — and the first version
    was a real bug.** `Url4Executor.execute` is an ASYNC GENERATOR, and consecutive steps of
    one can be driven from different contexts: `asyncio.ensure_future(gen.__anext__())` runs
    that step in a new Task with a COPIED context. A ContextVar token set in one and reset in
    another raises `ValueError: Token was created in a different Context`, which is exactly
    what `test_runner_summary.py::test_a_cancelled_run_records_stopped` reported. Caught by an
    existing prior test, not by a new one — the append-only rule earning its keep. Moved into
    the `_drive` task, which is one context for its whole life and is where every model call
    actually happens. Restated as a named regression test so the constraint is findable.
  - **The connections path uses `Caller`, not a ContextVar or middleware** (the ledger planned
    a request-scoped ContextVar). `Caller` already IS the per-request object — one instance per
    inbound Engine request — so the value cannot be read by a request that did not carry it,
    with no middleware and no new global. `Caller` gained `traceparent` and `profile`; a single
    `_headers(caller)` at `_request` covers **every** connections call, not just `/v1/providers`.
    The run path still needs a ContextVar because it has no such object — its world is cached
    across runs.
  - **The catalog path deliberately sends NO traceparent**, against the issue's "all three
    paths". `CachedCatalog` coalesces concurrent misses for one credential onto a single
    upstream fetch (`cache.py`'s `_inflight`) and serves it to every waiter — so a catalog call
    is *caused by* whichever caller led the refresh and *consumed by* N others. Stamping the
    leader's trace would put a call in their trace that also served people they never heard of,
    and leave the other N-1 with a gap where a catalog read should be. Both readings are wrong,
    and the wrong one looks right. Documented at the call site; representing it honestly needs
    an OTel span Link, which is `OME-1130`. **This is the one place the issue's premise did not
    survive contact with the code** — flagged rather than quietly satisfied.
  - **The REST edge validates rather than forwards.** `valid_traceparent` on the inbound header,
    with invalid degrading to *absent* — never forwarded as-is (garbage that parses into a trace
    joining nothing) and never an error (a bad trace header must not fail an otherwise valid
    connections request). Same rule `adapters/k8s.py:591` applies to the run path, so a caller
    gets one answer regardless of which Engine surface they enter through.
  - **Rule 5 Confidence-Gate, third consecutive rung PR:** approved on the numbers — test
    functions **5 → 5**, assertions **14 → 14**, one xfail marker deleted, no assertion
    weakened. `--skip-append-only` used, as sanctioned. The standing recommendation to exempt
    this one file rather than re-approve the identical shape twice more is unchanged.
  - Worktree note: the first `git worktree add` ran with a relative path while the shell cwd
    was inside another worktree, nesting it under `OME-1133`'s checkout. Detected before any
    commit (`git ls-files` returned 0), removed, and recreated from an absolute path.
