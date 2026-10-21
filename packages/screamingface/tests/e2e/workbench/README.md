# E2E notebook workbench

Reviewable notebooks executed by pytest against a live target. Design:
[`docs/spec/2026-10-16-e2e-notebook-workbench.md`](../../../../../docs/spec/2026-10-16-e2e-notebook-workbench.md).

## What it proves

`test_notebook[<target>-<stem>]` passes only when **all** of these hold:

1. The notebook runs top to bottom and its own `assert`s hold, score band included.
   `SCORE_BAND` is set by hand per scenario in the `parameters` cell.
2. The notebook's `WORKBENCH_RESULT` payload is well-formed (`result_check.py`): it has every
   key the notebook declares in `workbench.required_result`, `trace_ids` is a list, and each id
   is 32 lowercase hex characters. A missing payload, a non-list `trace_ids`, or a malformed id
   is a failure reason. Only well-formed ids go on to the chain check.
3. The trace chain is complete (`TraceChain.missing` / `TraceChain.reasons` in `evidence.py`).
   The notebook's `workbench-result` cell prints `WORKBENCH_RESULT={"trace_ids": [...]}`, and
   the check runs **per trace id**: every reported id must appear in every one of the target's
   required hops. On both targets those are `engine` and `aigateway`. Each gap is a reason that
   names the hop and the id, for example `aigateway: trace <id> absent`. A required hop with no
   configured log source is a reason too (`<hop>: no log source`).
4. When `aigateway` is required, each id must also appear on at least one aigateway line that
   carries a `gateway_call_id` (`aigateway: trace <id> on no line carrying gateway_call_id`
   otherwise). So a gateway that logs the trace id but emits no call ids fails. This is the
   workbench's version of correlation-ladder rung 3. The rung needs at least two identified
   lines in its own window. The workbench needs one per id, and it ties the line to this run by
   the trace id rather than by a time window, so another run's identified lines in a shared log
   cannot satisfy it.
5. Inside the aigateway request window (first to last line carrying a `gateway_call_id`, over
   the hop's whole text, not only the matched lines, from `harness.trace_evidence.unattributed_gateway_lines`), no line lacks a
   `gateway_call_id`. Startup and shutdown lines outside that window are not counted.

If no trace id is reported, the test fails (from the result check). It never passes on an empty
chain, and the chain check adds no second reason for that case. Engine lifecycle lines are
collected into `trace.json` but not yet required.

The notebook always builds `sf.Client(engine_url=ENGINE_URL, scoreboard_url=SCOREBOARD_URL)`
and raises if `SCOREBOARD_URL` is empty, so it can never fall back to the hosted leaderboard
(spec §3.1). `local` injects its own Scoreboard (`:9106`). `replay` has no Scoreboard and
injects an unused loopback placeholder (`http://127.0.0.1:9`); the notebook never calls the
leaderboard there.

## Running it

```sh
just screamingface workbench           # replay: free, keyless (docker + prepared ifeval assets)
just screamingface workbench local     # local: SPENDS real tokens
```

From `packages/screamingface`, plain pytest works too:
`SCREAMINGFACE_TEST_E2E=1 uv run pytest tests/e2e/workbench -v -rs`. CI runs the replay target
as part of `screamingface-e2e-replay.yml` and uploads the bundles as the `workbench-evidence`
artifact, on pass and on fail.

The lane is selected by environment variables. pytest CLI options are not used, because a
non-initial conftest cannot register them when the invocation is `pytest tests/e2e`.

| Variable | Meaning |
|---|---|
| `SCREAMINGFACE_WORKBENCH_TARGET` | `replay` (default) or `local`. `local` also needs `SCREAMINGFACE_TEST_PAID=1` and `OPENROUTER_API_KEY`. |
| `SCREAMINGFACE_WORKBENCH_OUT` | Bundle root. Default: a pytest tmp dir. Printed in the terminal summary. |
| `SCREAMINGFACE_WORKBENCH_REQUIRE_ALL` | `1` turns every workbench skip (no docker, no assets, no key) into a failure, so an all-skipped run is never green. |

The replay target goes through the usual e2e gate (`SCREAMINGFACE_TEST_E2E=1` + docker).

The local target has the layout of `just local-stack-notebooks`: `screamingface up` brings the
Gateway (:9105) and Scoreboard (:9106) on a fresh data dir, and a separate Engine
(`harness.stack.EngineProcess`, synced with the `inspect` extra, on a free port) serves ifeval
against that Gateway. Its hops are `engine.log` and the `gateway`-tagged lines of `runtime.log`.
It needs prepared ifeval assets; from `apps/screamingface-engine`:
`uv run --extra benchmarks python -m screamingface_engine.benchmarks.prepare --root <assets> --bundle ifeval`.

`test_local_boot.py` boots that stack for real with no key (gate: `SCREAMINGFACE_TEST_E2E=1`
only, no docker) and asserts the Engine lists ifeval. It spends nothing, so it also runs in the
CI replay lane (`screamingface-e2e-replay.yml`, keyless). It binds the fixed loopback ports
9105 (Gateway), 9106 (Scoreboard) and 9108 (the runtime's own Engine, unused), plus one free
port for the inspect Engine, so a runtime already up on those ports makes it fail. The run needs
the SDK's `runtime` extra; `just screamingface workbench` and the CI step pass `--extra runtime`.

If `up` or the Engine fails partway, the target still tears down what it started: `down` runs
once `up` was invoked, and the Engine is stopped once its start was attempted.

## What is verified, and what is not

| Check | Key needed | Status (2026-10-16) |
|---|---|---|
| Unit tests (runner, evidence, bundle, targets, builder, result check, `REQUIRE_ALL`) | none | pass |
| `test_notebook[replay-quickstart]`: notebook + engine/aigateway chain on the replay stack | none | pass locally; CI runs it on every PR |
| `test_local_boot.py`: real `screamingface up` + inspect Engine boots and lists ifeval | none | pass locally (needs prepared assets) |
| `test_notebook[local-quickstart]`: the notebook itself on `local` | `OPENROUTER_API_KEY` + `SCREAMINGFACE_TEST_PAID=1` | **not run yet**: needs one paid run |

So on `local`, the stack wiring is checked without a key, but the notebook's evaluate call, the
score band, and the trace chain through the real Gateway have not been exercised.

## Evidence bundle

Each notebook writes a bundle, whether it passes or fails:

```
<out>/
  summary.md                    # one row per notebook: target | notebook | outcome | trace ids | reasons
  <target>/<notebook>/
    executed.ipynb              # the run with outputs, tracebacks included
    trace.json                  # per hop: found (every id), missing_ids; verdict, reasons, result
    logs/<hop>.txt              # the log lines matching the trace ids (engine, aigateway | runtime)
```

With `--junitxml`, each `test_notebook` entry also carries the properties `trace_ids`
(comma-joined) and `bundle` (the bundle path).

Secrets are redacted before anything leaves the test, by one redactor (`redaction.py`):
the bundle, the failure reasons (`verdict.py` raises them without a traceback, so `-l` cannot
re-print the raw error), the JUnit properties, and, through the lane's report hook in
`conftest.py`, every report's traceback, captured output and properties on the terminal and in
JUnit. Masked whole: `sk-…`, JWT-shaped tokens, `Bearer …`/`Basic …`, `ghp_…`/`github_pat_…`,
`glpat-…`, `AIza…`, `hf_…`, `AKIA…`, `xox?-…`, PEM private keys. Masked by name, keeping the
name: URL userinfo passwords, query parameters such as `?api_key=…&token=…`, `Authorization` /
`Proxy-Authorization` with any scheme (`Token …`, `ApiKey …`, `Digest …`), and assignments,
headers or mapping entries whose name ends in key, token, secret, password, credential(s), auth
or sig (`OPENROUTER_API_KEY=…`, `x-api-key: …`, `api_key=b'…'`, `"client_secret": "…"`, also
inside escaped JSON or a repr). Left readable on purpose: a bare `key=` (the gateway's cache
key), counts such as `max_tokens=`, and code such as `api_key=os.environ["K"]` or
`load_key()`. Free text with no recognisable shape or name is not detected.

Not redacted: live logging (`log_cli`, off by default and in CI) and the pytest warnings
summary are written outside the report hook. Do not turn on `log_cli` (`-o log_cli=true`) for
this lane where the output is published, and do not put secrets in warning messages.

## Adding a notebook

1. Add a builder function in `build_notebooks.py` and register it in `_BUILDERS`. Give it a
   `parameters`-tagged cell holding the defaults (the runner injects overrides after it) and a
   `workbench-result`-tagged cell that prints the trace ids.
2. Declare which targets it supports in the notebook metadata, for example
   `{"targets": ["replay", "local"]}`. On any other target the notebook skips.
3. Regenerate the notebooks and commit them:
   `uv run python tests/e2e/workbench/build_notebooks.py`.
   `--check` exits 1 on drift.

## Why the notebooks are generated

The `.ipynb` files under `notebooks/` are build output. They are committed without outputs, and
`test_build_notebooks` checks that they are byte-identical to what the builder renders. The
replay recipe has to be exactly the candidate the golden recorded. Rendering it from the golden
file means a hand-edited copy can never drift from it. Generated files also keep diffs small
and reviewable.
