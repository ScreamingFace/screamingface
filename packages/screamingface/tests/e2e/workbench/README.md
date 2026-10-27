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
   is a failure reason. Only well-formed ids go on to the chain check. The run fails closed on
   more than one `WORKBENCH_RESULT=` line from any cell (no marker wins), and the runner refuses
   a notebook without exactly one `workbench-result` cell before executing it (`runner.py`).
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
| `SCREAMINGFACE_WORKBENCH_DEADLINE_S` | Whole-notebook deadline in seconds (default `600`), across all cells; the per-cell timeout is capped at what is left, so a slow run still writes its bundle before the 30-min CI job ends. |
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

## UI

A local page that launches the lane above and shows its evidence bundles, so you never open
`trace.json` or `executed.ipynb` by hand. It is dev-only (`ui/`, never in the SDK wheel).

**Start it** — one command, from anywhere in the repo:

```sh
packages/screamingface/scripts/workbench-ui            # replay only, free
packages/screamingface/scripts/workbench-ui --paid     # also enable `local` (OpenRouter, spends)
packages/screamingface/scripts/workbench-ui --check    # preflight only
```

It checks `uv`, Docker, the prepared ifeval assets (printing the exact prepare command if they
are missing) and the port, then starts the UI and opens `http://127.0.0.1:9112/?token=…`.
`--port`, `--out` and `--no-open` pass through; bundles default to
`packages/screamingface/workbench-out`. `--paid` takes `OPENROUTER_API_KEY` from the environment,
else reads only the `OPENROUTER_API_KEY` / `OPENROUTER_KEY` line from the repo's `.env` (in a git
worktree, the main checkout's `.env`); nothing else from that file is loaded and the key is never
printed. `just screamingface workbench-ui` runs the same script.

Under the hood it is `PYTHONPATH=tests/e2e uv run --extra runtime python -m workbench.ui --out …`
from `packages/screamingface` (`python -m` imports `workbench` before `__main__` runs, so the
module cannot add `tests/e2e` to `sys.path` itself; `test_entrypoint.py` boots it for real).

**How to test it** (a human, about 5 minutes, keyless; needs docker and the prepared ifeval
assets, as for `just screamingface workbench`):

1. Start the UI as above and open the printed URL. The page shows "Launch a run" with
   `replay` selected; `local` is greyed out with the reason when `OPENROUTER_API_KEY` is unset.
2. Tick `quickstart` and press **Start run**. The run page streams pytest's output, and after
   the `collected 1 item` line shows `running quickstart… 00:07`, ticking every second.
3. Wait for the end (a few minutes on replay). The page reloads with `exit 0` and a PASS
   bundle. Open it: the Trace view (five hops, the span tree from `sdk.evaluate` down to the
   gateway calls), the trace ids, the candidate's score, spend
   (`unknown` or an amount, never `None`), cache hits, cache-saved cost, and the executed
   notebook in a frame.
4. Start another run, press **Cancel run** while it is running and confirm. The page ends
   `cancelled · exit …`. On the finished page, send the cancel again (browser back, resubmit):
   it answers "already finished — nothing to cancel".
5. Start a third run, then press Ctrl-C in the UI's terminal. The UI prints
   `cancelling run … before exit` and exits; `pgrep -f test_notebooks.py` prints nothing.

**Pages**

| Page | Shows |
|---|---|
| `/` | The run form: target (`replay`, or `local` with a "spends real tokens" checkbox), notebooks (none checked = all). The runs found under `<out>/runs/`. Every bundle under `<out>`, newest first: verdict pill (PASS, FAIL, or "unreadable" when `trace.json` is missing or malformed), target, notebook, trace ids, reasons, time. |
| `/runs/<id>` | Status, which notebook is running and for how long (`running quickstart… mm:ss`, from pytest's `collected` line to that notebook's result), the pytest output streamed live, a Cancel button, the live model calls and telemetry counts (see Telemetry), and links to the bundles the run wrote. After the run ends it shows the exit code and the partial output, including when the run crashed or was cancelled. |
| `/bundles/<key>` | Verdict and reasons, the Trace view (see "Reading the Trace view"), per candidate the score, spend (`cost_usd`), cache hits and cache-saved cost, the total spend, one collapsible log excerpt per hop, the Telemetry section (see Telemetry), and the executed notebook. A money value the notebook reported as null (nothing priceable observed), or did not report, shows `unknown`, never `0`; one unknown amount makes the total `unknown`. |

The progress line is derived from pytest's own `-v` lines. `log_cli` stays off: it would print
around the redaction hook (see "Not redacted" below).

A launched run is exactly `pytest -v -rs tests/e2e/workbench/test_notebooks.py` with
`SCREAMINGFACE_WORKBENCH_TARGET`, `SCREAMINGFACE_WORKBENCH_OUT=<out>/runs/<id>` and
`SCREAMINGFACE_WORKBENCH_REQUIRE_ALL=1` set. Two additions:

- Ticked notebooks are selected by exact node id,
  `tests/e2e/workbench/test_notebooks.py::test_notebook[<target>-<stem>]`, never by a `-k`
  substring (which would also select every notebook whose name contains it).
- `--basetemp=<out>/runs/<id>/pytest-tmp`, so a `local` run's work dir, and with it the runtime
  data dir (`pytest-tmp/workbench-target0/data`, holding `runtime.log`) and `engine.log`, stays
  next to its bundles.

The UI never executes notebooks itself. Bundles from an unzipped CI `workbench-evidence`
artifact display the same way: point `out` at it.

**Security model**

- **Loopback only.** The server binds `127.0.0.1`. A request whose `Host` is not
  `127.0.0.1:<port>` or `localhost:<port>` gets 400 (DNS-rebinding guard).
- **Launch token.** Starting or cancelling a run needs the per-launch token from the printed
  URL (form field or `X-Workbench-Token` header). Without it the route returns 403, so another
  site in your browser cannot start a run. No cookies. A page opened without the token is
  read-only.
- **Sandboxed notebooks.** Executed-notebook outputs are untrusted. They render only inside an
  `<iframe sandbox="">` (no scripts, no same-origin, no forms). Every other value is
  HTML-escaped, and a strict CSP plus `X-Frame-Options: DENY` is on every response.
- **Keys.** The UI never accepts or shows a provider key. A `local` run needs the paid
  checkbox and `OPENROUTER_API_KEY` in the UI process's own environment. Otherwise `local` is
  shown disabled with the reason, and a direct POST gets 400. A `replay` run never inherits
  the key (nor `SCREAMINGFACE_TEST_PAID`): both are removed from its environment.
- **Paths.** A bundle key that resolves outside `out` is 404. Symlinked directories are not
  followed.

**One run at a time.** The `local` target binds the fixed ports 9105/9106/9108, so a second
launch while one is active gets 409. The live stream is kept in memory only. After a UI
restart, past runs are rebuilt from `<out>/runs/*` on disk.

**Cancel.** A run is its own session and process group: pytest, the kernel and the separate
inspect Engine. `screamingface up` is **not** in it: it detaches the runtime (Gateway,
Scoreboard) into its own session, and only `screamingface down` stops it, which the `local`
target's fixture teardown runs. So Cancel sends the group SIGINT first, which pytest turns into
a `KeyboardInterrupt` that still runs that teardown. SIGTERM follows after 30 s and SIGKILL
after 15 s more, if anything lingers. When the group needed SIGKILL (teardown may not have
run), or after any cancelled `local` run, the run page says the runtime may still be up and
gives the exact command, for example:

```sh
screamingface down --data-dir <out>/runs/<id>/pytest-tmp/workbench-target0/data
```

(run it from `packages/screamingface` as `uv run --extra runtime screamingface down …`). When
the run's data dir is not found, the runtime's default data dir is named
(`SCREAMINGFACE_DATA_DIR`, else `~/.screamingface`). A cancel sent to a run that already ended
answers 409 "already finished — nothing to cancel".

**Stopping the UI stops its run.** Ctrl-C, SIGTERM or SIGHUP (terminal closed) on the UI
process cancels an active run as above before the UI exits; a paid `local` run never keeps
spending after the UI is gone. A second Ctrl-C (uvicorn's force exit) still cancels it, and a
signal that arrives while the UI waits for the teardown SIGKILLs the run's group at once. The
UI exits with 128 + the signal number. SIGKILL on the UI itself cannot be handled: cancel the
run first.

`test_ui_e2e.py` launches a real `replay` run for `quickstart` through these routes and checks
the bundle is listed PASS, its Trace view (five hops, `url4.run` under the derived
`sdk.evaluate` root, a gateway chat span under `/benchmarks/candidate`), its Telemetry section,
and the run's telemetry stream (gated like the replay lane). The tree assertions need the
engine's span export (unit 6a, OME-1747) on the branch: without it the engine exports no
`url4.run` and the test fails at the tree.
`test_shutdown.py` boots the real entry point with a fake run and signals only the UI process.

### Telemetry

Every notebook run also records its telemetry, and the UI shows it live and afterwards
(spec §3.6, unit 6 plan). There are three capture paths, each redacted before it reaches disk:

- **SDK events.** The notebook's `on_event` recorder (`telemetry_recorder.py`) appends each
  `Started`, `Span`, `Usage`, `Log` and `Terminated` event to `events.jsonl`, live. The result
  cell then writes `report.json` and `accounting.json`.
- **OTel spans.** The lane runs a loopback OTLP/HTTP receiver (`otlp_receiver.py`, session
  scope, `<out>/spans.jsonl`). Both targets point the engine (`screamingface-engine`) and the
  gateway (`aigateway`) at it through `OTEL_EXPORTER_OTLP_ENDPOINT`, with
  `OTEL_BSP_SCHEDULE_DELAY=200`. At bundle time only the spans under the notebook's exact
  trace ids are copied into the bundle's `spans.jsonl`.
- **The engine.** The local in-process runner exports its `url4.run` span tree when an OTLP
  endpoint is set (unit 6a). Without one it exports nothing, which is the default.

Where you see it:

- **Run page, live.** `GET /runs/<id>/telemetry` (SSE) tails the run's `spans.jsonl` and every
  `events.jsonl`. It sends one `call` per span that names a model (model, tokens, cache,
  duration, error), running `counts` (events, spans, calls, tokens, cache hits, cost), and
  `end` once the run has ended and the files are drained. Only complete lines are read.
- **Bundle page, after.** A **Telemetry** section with four views. The span waterfall is
  inline SVG, grouped by service, with repeated siblings folded and paginated. Usage and cost
  come from the SDK usage events and from the report's accounting. Logs have a severity
  filter. Cases come from `report.json`. A missing value shows `unknown`, never `0`, and a run
  with no spans says why (`telemetry.json`).

What a replay run shows (observed 2026-10-22, `quickstart`, run in the UI on port 9114):

- **Live.** The first `counts` frame arrived 4.6 s into the run, with 3 spans. A `call` frame
  (`openrouter/microsoft/phi-4`, cache `hit`, 68 ms) arrived at 7.1 s, with 59 events and
  46 spans counted. That was before pytest reported PASSED (8.7 s) and before the run ended
  (9.0 s). The live count is higher because it covers the whole session file.
- **Bundle.** 59 events and 39 spans, all under the one notebook trace id. The 39 spans include
  `url4.run` (`screamingface-engine`), two gateway `POST /v1/chat/completions` server spans
  (`aigateway`), and the frozen-copy calls. Usage shows one model, `$0`. There are 21 INFO
  logs and 1 case (`scored`, score 1.0, `passed`).
- **Expected gaps on replay.** Every model call is a cache hit, so the gateway emits no
  `chat.completions {provider}` span, and the report's accounting has no model or stage rows
  ("No model rows."). Both appear only on a real dispatch (`local`, paid), which has not been
  run yet.

### Reading the Trace view

The bundle page's **Trace** section (spec §3.8, u8 plan) tells one run's story across every hop.
It is built from the bundle's own files (`trace.json`, `spans.jsonl`, `events.jsonl`,
`recorder.json`, `accounting.json`, `logs/*.txt`; `ui/trace_story.py`) and rendered without
script (`ui/trace_html.py`). The verdict does not change; this is presentation. Top to bottom:

1. **Header.** Trace id (selectable), verdict, wall time, model calls, cache hits, spend, and
   span, SDK event and log-line counts. Spend is `accounting.json`'s total over every model;
   it is `unknown` on replay (the accounting has no model rows), never `$0`. Past 2 000 calls
   the count reads "2000 shown of N".
2. **Trace chain.** Five boxes: notebook (SDK) → engine → aigateway → provider or cache →
   scoreboard, each ok (✓), failed (✗) or not seen (grey, dashed) with its reason, span and
   log-line counts, and latency. On replay, provider is grey "none on replay: served from
   cache" and scoreboard is grey "not instrumented". A failed gateway call turns aigateway ✗
   with the failure code. Under 480px the boxes stack into a column.
3. **Span tree.** One tree across services, nested by `parent_span_id`. Its root is
   `sdk.evaluate`, a client span **derived from SDK events** (dashed, labelled): it is made only
   when exactly one span's parent is outside the bundle and that span is `url4.run`; the span id
   is that parent, the bounds come from `recorder.json`. Otherwise no root is invented and a
   note says why. Five or more same-named sibling leaves fold into "×N"; the path to any error
   starts open and red. 500 rows per page; a page that starts mid-subtree repeats its ancestors.
   A cycle in the parents cannot loop: each span is visited once.
4. **Model calls.** One row per gateway `POST /v1/chat/completions` span, described by its
   engine parent (`/benchmarks/candidate`: model, provider, cache, tokens). Gateway lines join
   a call by the exact `trace_id=` token and the span's time window, labelled "matched by time"
   ("ambiguous" when two windows hold the line, and then shown under both). A failed call's row
   is red.
5. **Checks.** Each rule the verdict applied, from `trace.json`, in plain words (✓ held /
   ✗ not held) with its evidence.
6. **Export.** "Download spans as OTLP/JSON" (`GET /bundles/<key>/trace.otlp.json`, launch token
   required): the spans as received, grouped by service, hex ids and string nanosecond times
   per the OTLP/JSON encoding. The derived client span is not exported. A protobuf
   `json_format.ParseDict` needs the three id fields re-encoded to base64 first (proto3 JSON).

What a replay run shows (observed 2026-10-27, both notebooks, keyless, with 6a applied):

- **`quickstart`.** 39 spans + the derived root (40 tree rows), 59 SDK events, 8 log lines;
  hops notebook, engine and aigateway ✓, provider and scoreboard grey; 2 model calls, both
  cache `hit`, spend `unknown`; `url4.run` under `sdk.evaluate`, both gateway chat spans under
  `/benchmarks/candidate`. The OTLP/JSON download parsed as `TracesData`: 39 spans in 2
  resources (`screamingface-engine` 35, `aigateway` 4), one 16-byte trace id.
- **`debug_failing_run`.** aigateway ✗ "2 of 2 calls failed: upstream_error"; the error path
  from `sdk.evaluate` down to `/benchmarks/candidate` is open and red; both call rows are red
  with `upstream_error`.

Known gaps (follow-ups B3, B8 in the plan): scoreboard is not instrumented; gateway spans carry
no attributes, so a call's model, cache and status come from its engine parent. In the failing
fusion both member calls sit under one failed `/benchmarks/candidate`, so both rows show that
span's model and the error, though only one member failed. The replay gateway's log lines
carry no timestamp at all (aigateway's log format, `aigateway/logs.py` `_FORMAT`, has none, and
the replay harness writes its raw stdout), so on replay no line can join a call by time (the
note "… carries no timestamp"). Only the `local` target's timestamped `runtime.log` lines can
be matched by time; a stamped line outside every call's window gets its own note. A join by
`gateway_call_id` needs B8.

## Debugging a failing run

`notebooks/debug_failing_run.ipynb` fails **on purpose** and is a tutorial. It runs a fusion
whose first member is the ifeval golden (a cache hit on replay) and whose second member,
`openrouter/openai/gpt-5.5`, is an Engine route the replay tape never recorded. The gateway
refuses that call (404 `profile_not_found`), the engine reports the case as `upstream_error`
at stage `candidate`, and `client.evaluate()` still returns: a failed member is a case failure,
not a run failure. The notebook then walks from the symptom to the root cause:

1. **Report.** Which case failed, with code and stage. The candidate has no score (with
   `quorum="all"` the failed member fails the case before the synthesizer runs).
2. **Trace id.** `result.trace_id` on the report, or `exc.trace_id` when `evaluate()` raises
   after the run started.
3. **SDK telemetry.** Failing `Span`s (`status == "error"` or a refusal) and ERROR `Log`s
   (`severity_number >= 17`) from the recorded `events.jsonl`. Only the ERROR log
   `Model call failed` names the failing model; no span does. `Usage` for the healthy member
   proves it ran.
4. **Gateway lines.** Filtered by the exact `trace_id=<id>` token, with the same pattern the
   verdict uses (a substring match would also hit `parent_trace_id=` or a longer id).
5. **Root cause and fix.** The same fusion with a servable member, as a markdown block that is
   never executed, so the notebook keeps failing by design.

It declares `workbench.expect = {outcome: fail, failure_codes: [upstream_error], stage:
candidate}` and `targets: [replay]` (spec §3.7). `test_notebook[replay-debug_failing_run]`
passes only when the notebook fails **exactly** that way: the declared code at the declared
stage, a complete trace chain (engine and aigateway, with `gateway_call_id`s), and at least one
failing span or ERROR log. An unexpected pass (for example after a tape re-bless makes the
member servable), a different code, or missing evidence is red. `local` is not declared: there
`gpt-5.5` would be served and billed, and the test would be an unexpected pass.

**In the UI.** The run form labels it "(fails on purpose: debugging example)". Its bundle
shows the pill `expected FAIL ✓` (or `expected FAIL ✗` with the reasons), the declared and
observed codes, and in Telemetry an **Errors** view: each failing span and ERROR log is
highlighted (also in the waterfall and the log list) and links to the **Gateway calls of these
traces** table (`#gw-<gateway_call_id>`). No SDK event carries a `gateway_call_id` yet, so each
error links every call of its trace and says "by trace id".

Observed 2026-10-22 (replay, keyless, $0), UI on port 9114, both notebooks in one run: exit 0
after 12 s; `quickstart` PASS; `debug_failing_run` `expected FAIL ✓`, observed
`upstream_error`/`candidate`, error telemetry 10 spans and 2 logs. The Errors view had 12 rows
(10 spans, 2 logs), 10 waterfall rows were highlighted, and 24 links all resolved to the 2
gateway-call anchors, one per member call. Both gateway lines are `usage accounting started`.

Known gaps (follow-ups, not hidden by the notebook): the failing model has no span of its own;
the gateway's 404 chat span has status `unset`, and the gateway logs no refusal line; the
engine's `model call failed` line carries no `trace_id=`; the activity log's failure code
(`internal_error`) differs from the report's (`upstream_error`).

## What is verified, and what is not

| Check | Key needed | Status (2026-10-16) |
|---|---|---|
| Unit tests (runner, evidence, bundle, targets, builder, result check, `REQUIRE_ALL`) | none | pass |
| `test_notebook[replay-quickstart]`: notebook + engine/aigateway chain on the replay stack | none | pass locally; CI runs it on every PR |
| `test_notebook[replay-debug_failing_run]`: fails exactly as declared (`upstream_error`/`candidate`), chain complete, error telemetry present (2026-10-22) | none | pass locally (`expected FAIL ✓`) |
| UI smoke: both notebooks launched through `POST /runs`, debug bundle `expected FAIL ✓`, Errors view linked to gateway calls, run-form label (2026-10-22) | none | pass locally, by hand on port 9114 |
| `test_local_boot.py`: real `screamingface up` + inspect Engine boots and lists ifeval | none | pass locally (needs prepared assets) |
| `ui/test_ui_e2e.py`: a real replay run launched through the UI by node id, a live progress event, bundle listed PASS with a spend total (2026-10-21) | none | pass locally |
| `ui/test_ui_e2e.py` telemetry: the bundle's Telemetry section (waterfall with `url4.run` and a gateway span, usage, logs, cases) and the run's `/runs/<id>/telemetry` stream (2026-10-22) | none | pass locally |
| `ui/test_entrypoint.py`: `python -m workbench.ui` and `just workbench-ui` (package + repo root) serve the page (2026-10-21) | none | pass locally; the `just` cases skip where `just` is absent |
| `ui/test_shutdown.py`: SIGTERM, Ctrl-C (once, twice, thrice), SIGHUP on the UI process end its active run (2026-10-21) | none | pass locally |
| `test_notebook[local-quickstart]`: the notebook itself on `local` | `OPENROUTER_API_KEY` + `SCREAMINGFACE_TEST_PAID=1` | **not run yet**: needs one paid run |

So on `local`, the stack wiring is checked without a key, but the notebook's evaluate call, the
score band, and the trace chain through the real Gateway have not been exercised.

## Evidence bundle

Each notebook writes a bundle, whether it passes or fails:

```
<out>/
  summary.md                    # one row per notebook: target | notebook | outcome | trace ids | reasons
  junit.xml                     # CI only: the whole e2e run's JUnit (--junitxml in the workflow)
  setup_error.txt               # only when the target errored/skipped while booting (+ a SETUP-ERROR/SETUP-SKIP summary row)
  <target>/<notebook>/
    executed.ipynb              # the run with outputs, tracebacks included
    trace.json                  # per hop: found (every id), missing_ids; verdict, reasons, result
    logs/<hop>.txt              # the log lines matching the trace ids (engine, aigateway | runtime)
    events.jsonl                # every SDK event, one redacted JSON line each (cap 20 000)
    spans.jsonl                 # the OTel spans under this notebook's trace ids (cap 20 000)
    report.json                 # Report.to_dict()
    accounting.json             # per candidate: cost by model and by stage
    recorder.json               # the event recorder's counts and per-file outcome
    telemetry.json              # what was recorded, copied and dropped, and why a file is empty
```

CI (`screamingface-e2e-replay.yml`) passes `--junitxml=$SCREAMINGFACE_WORKBENCH_OUT/junit.xml`,
so the JUnit is uploaded with the bundles on pass and fail. With `--junitxml`, each
`test_notebook` entry also carries the properties `trace_ids`
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
   `workbench-result`-tagged cell that prints the trace ids. Exactly one such cell, holding the
   notebook's only `WORKBENCH_RESULT=` marker; the builder refuses any other shape.
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
