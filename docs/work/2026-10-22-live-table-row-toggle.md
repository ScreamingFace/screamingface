---
ticket: OME-1612
stack: screamingface
status: done
started: 2026-10-22
finished: 2026-10-22
---

# live-table-row-toggle — rows in the live progress table open while an evaluation runs

## Intent

OME-1612: in a notebook, clicking a Candidate row's chevron in the live progress table did nothing
until `sf.evaluate` finished, because opening a row is a Python `observe` callback and the running
cell holds the kernel. The browser now owns a row's open/closed state and chevron, and the ticker
keeps every row's activity current, rendering each row at most once per 2 s step. Spec:
`docs/spec/2026-10-22-OME-1612-live-table-row-toggle.md`. Plan:
`docs/plan/2026-10-22-OME-1612-live-table-row-toggle.md`.

## Planned changes

- `packages/screamingface/src/screamingface/_ui/activity_view.py` — CSS on the browser-side
  `mod-active` class; `activity_html` without `STYLE`.
- `packages/screamingface/src/screamingface/_ui/activity_state.py` — `ActivityLog.revision`.
- `packages/screamingface/src/screamingface/_ui/activity_widget.py` — every row refreshed at most
  once per 2 s step under a render key; no icon swap.
- `packages/screamingface/src/screamingface/_ui/evaluation_widget.py` — the final refresh always renders.
- `packages/screamingface/tests/test_activity_live_toggle.py` — new tests.

## Test plan

- A closed row's activity is filled, without `STYLE`; the CSS rules are present.
- A finished row renders at most once per step and only on change; a running row once per step;
  a queued row only on change.
- End, loss and suppression rises, evictions (own and log-wide count) and a late result render;
  events that store nothing do not.
- The final refresh (via `abort`, after another Candidate's change) renders at once; a failed
  render is retried.
- Invariant: prior tests unmodified.

## Acceptance

- Mid-run click opens and closes a row immediately in Jupyter Lab, with live activity.
- All `screamingface` gates green. No change to runs, scores or the Report.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger, the spec, the plan and the `docs/tasks/` mirror.
- **Commits:** one — `fix(client): open live progress rows while an evaluation runs`.
- **Gates:** `run_gates.py screamingface` — ALL GATES GREEN (ruff, format, pyright, pytest with the
  95% coverage floor, notebook check, build, distribution). The new tests fail on `origin/main`; eleven
  mutations of the render key and revision bumps are each caught by a new test.
- **Visual (Jupyter Lab, kernel held 60 s):** a row opened at 24 s with live model-call activity
  and its chevron pointing down; closed at 35 s; another opened mid-run; after the queued clicks
  drained both kept their state; opening after the run works. VS Code checked by source only;
  Colab not checked.
- **Deviations:** none.
