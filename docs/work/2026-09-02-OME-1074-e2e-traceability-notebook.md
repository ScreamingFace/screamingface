---
ticket: OME-1074
stack: repo
status: in_progress
started: 2026-09-02
finished:
---

# OME-1074 — Commit the live-k8s traceability e2e notebook

## Intent

The tracing roadmap (`OME-935`) lands one rung at a time, and each rung's real acceptance
test is a run against the **deployed** stack — not the local harness. That check has been
done by hand so far. This unit version-controls it as a notebook so it is re-runnable,
reviewable, and so the two k8s facts that make a hand check wrong are encoded rather than
remembered.

Rungs 2–4 fail today by design. The notebook is the acceptance test for the changes that
make them pass, and its failure output is the current-state evidence.

## Planned changes

- `e2e/failor/notebooks/traceability_e2e_k8s.ipynb` — the notebook (path as specified by the
  owner).
- `e2e/failor/notebooks/README.md` — what it is, how to run it, and why it is not a CI lane.
- This ledger + the `docs/tasks/` mirror.

New top-level `e2e/` directory. No CI workflow is added: nothing here can run unattended
against a cluster, and no path filter matches, so the lane stays hand-run by design.

## Design decisions

**D1 — not under `packages/screamingface/examples/`.** `scripts/check_notebooks.py` requires
the public example notebooks to match a deterministic builder and stay output-free. A
live-cluster diagnostic is non-deterministic and output-bearing by nature, so putting it
there would either fail the gate or force the gate to be weakened. It is also not an SDK
example — it is an operator tool, and the two audiences want different things.

**D2 — tailers start before the run.** Runner Jobs are short-lived and reaped
(`orphan_grace_s = 120`; the orphan sweep in `adapters/jetstream.py` drops terminal streams
to 60 s once the NATS store is full — i.e. exactly when failures cluster). A notebook that
ran first and read logs afterwards would report empty evidence as a failed rung.

**D3 — rung 4 greps the Runner Job, not the engine Deployment.** A run executes in a per-run
Job (`app.kubernetes.io/name=url4-runner`, `RUNNER_LABELS` in `adapters/k8s.py`) and the
traceparent reaches it through the Job env. Reading the Deployment yields nothing and reads
as a false failure — so the selector is in the config cell and the troubleshooting section
names this as the first thing to check.

**D4 — the trace id is read off events on success.** `trace_id` is public only on the error
hierarchy (`ScreamingFaceError.trace_id`); `Report` carries no trace field. So the notebook
takes the id from `ScreamingFaceError.trace_id` when a run fails and from
`sf.Event.traceparent` via the `on_event` hook when it succeeds. **This is a gap worth its
own decision** — a user with a successful run currently has no supported way to quote an id,
which is the thing a report needs. Recorded here rather than fixed, because widening the
public surface is not this unit's call.

## Test plan

**Correction made during the work: ruff DOES apply.** The plan assumed a new top-level
directory outside every path filter meant no gate touched it. The repo's `.pre-commit-config`
runs `ruff check` and `ruff format` **repo-wide, including `.ipynb` files**, and the first
commit attempt was rejected with `E402` (imports not at top of cell), `E741` (ambiguous `l`),
and an unused import — then reformatted both files under me. Verification is therefore:

- `ruff check` and `ruff format --check` clean on the notebook *and* its builder;
- regeneration is **idempotent** — building twice produces a byte-identical file, so the
  builder and the commit hook agree instead of fighting;

- the notebook is valid `nbformat` 4 JSON;
- every code cell parses (`ast.parse`) — a broken cell must not reach the owner;
- no cell carries stored outputs, so the committed file is a clean diff on every re-run.

The last three run inside `build_notebook.py` itself, so they cannot be skipped.

## Acceptance

- Notebook and README committed under `e2e/failor/notebooks/`.
- Every code cell parses; no stored outputs; valid nbformat.
- Running it against a live cluster prints PASS for rung 1 and FAIL for rungs 2–4, which is
  the correct current state.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus one — `e2e/failor/notebooks/traceability_e2e_k8s.ipynb`,
  `e2e/failor/notebooks/README.md`, `e2e/failor/notebooks/build_notebook.py` (**added**), the
  ledger and the `docs/tasks/` mirror.
- **Commits:** `docs(e2e): commit the live-k8s traceability notebook` (sha at squash-merge).
- **Gates:** `ruff check` + `ruff format --check` clean on both files (they run repo-wide via
  pre-commit, including on `.ipynb` — see the Test plan correction). No *stack* gate applies:
  new top-level directory, no path filter matches, no CI lane by design. Also verified: valid
  nbformat 4, **22 cells / 10 code**, every code cell `ast.parse`s, every cell `outputs: []`
  with `execution_count: None`, and regeneration byte-identical.
- **Deviations:**
  - **`build_notebook.py` was added, which the plan did not list.** Hand-editing a committed
    `.ipynb` that is *meant to be executed* guarantees a dirty tree after every run. The
    builder emits empty outputs, so regeneration is always a clean diff — the notebook stays
    reviewable as source rather than as an execution record.
  - **The builder now runs `ruff check --fix` and `ruff format` on its own output.** Without
    it the builder and the pre-commit hook disagree: the hook reformats on commit, and the
    next regeneration reverts it. Formatting inside the builder makes regeneration idempotent,
    which is verified rather than assumed.
  - **Cells were restructured to satisfy `E402`** — imports moved into their own first cell
    instead of sitting below the config block. Section numbering shifted by one accordingly.
  - The directory name is `failor`, exactly as the owner specified.
