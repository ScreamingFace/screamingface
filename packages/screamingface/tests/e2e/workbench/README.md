# E2E notebook workbench

Reviewable notebooks executed by pytest against a live target. Design:
[`docs/spec/2026-10-16-e2e-notebook-workbench.md`](../../../../../docs/spec/2026-10-16-e2e-notebook-workbench.md).

## What it proves

`test_notebook[<target>-<stem>]` passes only when **both** hold:

1. The notebook runs top to bottom and its own `assert`s hold, score band included.
   `SCORE_BAND` is set by hand per scenario in the `parameters` cell.
2. Every trace id the notebook reports (its `workbench-result` cell prints
   `WORKBENCH_RESULT={"trace_ids": [...]}`) is found in each of the target's required log
   sources. On `replay` those are the engine and the aigateway. Every matched aigateway line
   must also carry a `gateway_call_id`.

If no trace id is reported, the test fails. It never passes on an empty chain. Engine lifecycle
lines are collected into `trace.json` but not yet required.

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

Both targets also go through the usual e2e gate (`SCREAMINGFACE_TEST_E2E=1` + docker).

## Evidence bundle

Each notebook writes a bundle, whether it passes or fails:

```
<out>/
  summary.md                    # one row per notebook: target | notebook | outcome | trace ids | reasons
  <target>/<notebook>/
    executed.ipynb              # the run with outputs, tracebacks included
    trace.json                  # hops found/missing, verdict, reasons, the reported result
    logs/<hop>.txt              # the log lines matching the trace ids (engine, aigateway | runtime)
```

With `--junitxml`, each `test_notebook` entry also carries the properties `trace_ids`
(comma-joined) and `bundle` (the bundle path).

Secrets are redacted before anything is written. The patterns are `sk-…` keys, JWT-shaped
tokens, and `Bearer …`.

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
