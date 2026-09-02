# Traceability e2e — live k8s

Hand-run notebooks that validate the correlation chain against the **deployed** stack.

| File | What it does |
|---|---|
| `traceability_e2e_k8s.ipynb` | Walks the tracing ladder (`OME-935`), one rung per section, printing PASS/FAIL and a summary table |
| `build_notebook.py` | Regenerates the notebook's authored cells — edit here, re-run, commit both |

## Run it

```sh
pip install screamingface        # a build containing OME-967
jupyter lab traceability_e2e_k8s.ipynb
```

Edit the **first code cell only** — namespace, engine URL, aigateway deployment name,
benchmark — then run top to bottom.

## What it asserts

1. **`OME-967`** — the client originated one well-formed trace id.
2. The engine emitted that id to aigateway.
3. **`OME-938`** — `gateway_call_id` on **every** aigateway log line.
4. One id greppable across the Runner Job **and** aigateway logs.

**Rungs 2–4 are expected to FAIL today.** They are the acceptance test for changes that have
not landed yet, and the failure output is the current-state evidence. Re-run as each lands.

## Two things that make a hand-run check wrong

**A run does not execute in the engine pod.** It executes in a per-run Runner Job
(`app.kubernetes.io/name=url4-runner` — `RUNNER_LABELS` in the engine's `adapters/k8s.py`),
and the traceparent reaches it through the Job env. Grepping the engine Deployment finds
nothing and reads as a failed rung when the rung is fine.

**Start the log tailers before the run.** Runner Jobs are short-lived and reaped
(`orphan_grace_s = 120`, and the orphan sweep drops terminal streams to 60 s once the NATS
store is full — exactly when failures cluster). Run first, read after, and the evidence is
already gone. The notebook's section order enforces this.

## Why there is no CI lane

Nothing here can run unattended: it needs a reachable cluster, `kubectl` credentials, and a
real benchmark run that spends provider budget. It is an operator tool, in the same class as
the `AIGW_LIVE=1` diagnostics — run before you believe a tracing change works in production,
not on every PR.

It also deliberately sits outside `packages/screamingface/examples/`, whose notebooks must
match a deterministic builder and stay output-free (`scripts/check_notebooks.py`). A
live-cluster diagnostic is non-deterministic and output-bearing by nature.

## Known limitation

`trace_id` is public only on the error hierarchy (`ScreamingFaceError.trace_id`); `Report`
carries no trace field. So the notebook reads the id from the exception when a run fails and
from `sf.Event.traceparent` via the `on_event` hook when it succeeds. A user with a
successful run currently has no supported way to quote an id — which is the thing a bug
report needs. Worth its own decision.
