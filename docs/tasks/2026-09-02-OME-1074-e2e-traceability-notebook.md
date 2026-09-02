---
id: OME-1074
linear_url: https://linear.app/openmined/issue/OME-1074/commit-the-live-k8s-traceability-e2e-notebook
status: in_progress
type: task
priority: 3
labels: [repo, agentic, autonomous, task]
created: 2026-09-02
closed:
---

# Commit the live-k8s traceability e2e notebook

Version-controls the interactive traceability ladder at `e2e/failor/notebooks/` so it is
re-runnable as each rung of the tracing roadmap (`OME-935`) lands, instead of being repeated
by hand.

Four rungs, one section each, printing PASS/FAIL: the client originated a trace id
(`OME-967`); the engine emitted it to aigateway; `gateway_call_id` on every aigateway line
(`OME-938`); one id greppable across the Runner Job and aigateway. **Rungs 2–4 fail today by
design** — the notebook is the acceptance test for changes that have not landed.

It sits outside `packages/screamingface/examples/` because `scripts/check_notebooks.py`
requires those to be deterministic and output-free, and a live-cluster diagnostic is neither.
A `build_notebook.py` regenerates the authored cells with empty outputs, so executing the
notebook never dirties the tree.

Two k8s facts are encoded rather than remembered: a run executes in a per-run Runner Job
(`app.kubernetes.io/name=url4-runner`), not the engine pod; and the log tailers must start
before the run, because Jobs are reaped within 60–120 s.

Known limitation recorded with it: `trace_id` is public only on the error hierarchy, so a
successful run has no supported way to quote an id.

Ledger: `docs/work/2026-09-02-OME-1074-e2e-traceability-notebook.md`.
