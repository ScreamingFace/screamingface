# OME-1612 — Rows in the live progress table open while an evaluation runs

Ticket: `OME-1612` (bug; related epic `OME-1288`). Landing: `packages/screamingface`
(`client-sf`). Ledger: `docs/work/2026-10-22-live-table-row-toggle.md`. Plan:
`docs/plan/2026-10-22-OME-1612-live-table-row-toggle.md`.

## 1. Problem

`sf.evaluate` in a notebook draws the live progress table: one row per Candidate, each with a
chevron (an ipywidgets `ToggleButton`) that opens the Candidate's activity log.

- A click updates the toggle's model in the browser and sends a `comm_msg` to the kernel.
- Opening the row is Python: `CandidateActivityRow._toggle` (`_ui/activity_widget.py`) sets
  `details.layout.display` and the icon, then fills the activity HTML.
- `evaluate_sync` holds the kernel's main thread for the whole run, so the `comm_msg` waits in the
  shell queue, and every queued click fires when the cell ends.
- The ticker thread (`_NotebookEvaluationView._tick_loop`, `_ui/evaluation_widget.py`) keeps the
  table live from its own thread, but `CandidateActivityRow.refresh` fills activity only for rows
  Python believes are open, and Python never saw the click.

Reproduced 2026-10-22 in Jupyter Lab with the real `_NotebookEvaluationView` and a cell holding the
kernel for 60 s: chevrons clicked at 13 s and 22 s stayed closed and opened together when the cell
ended; an `observe` hook on each toggle recorded no call during the run.

## 2. Goal

A chevron click opens or closes its row at once while a run is going, and the opened row shows
that Candidate's live activity. Opening and closing after the run keeps working.

Out of scope: runs, scores, the Report, `evaluate_sync`'s wait loop.

## 3. Design — the browser owns open/closed

1. **Visibility and chevron from the browser's own state.** ipywidgets' `ToggleButton` view adds
   `mod-active` to its `<button>` as soon as the browser-side model changes, with no kernel
   round-trip. `STYLE` in `_ui/activity_view.py`:

   ```css
   .sf-candidate-row>.sf-candidate-details{display:none!important}
   .sf-candidate-row:has(>.sf-candidate-summary .widget-toggle-button.mod-active)
    >.sf-candidate-details{display:flex!important}
   .sf-candidate-row .widget-toggle-button.mod-active .fa-chevron-right{
    transform:translateY(-50%) rotate(90deg)}
   ```

   `!important` overrides the inline `display` Python writes, so the browser is the single
   authority. Python no longer swaps the icon: the chevron then depends only on the browser's
   `mod-active`, whereas a Python-set `chevron-down` would stay down on a row closed while the
   kernel is busy. The rule names `.fa-chevron-right`, so an open row drawn by an earlier release
   (`chevron-down`) is not rotated. `_toggle` still sets `layout.display` and the Show/Hide tooltip,
   as before.

2. **Activity for every row, at most once per 2 s step.** `CandidateActivityRow.refresh` fills
   `html.value` for every row, open or not. It runs each tick under the view lock that Engine
   events also take, so a row renders at most once per 2 s step, and only when its key
   (`ActivityLog.revision(candidate)` and the completion time) changed or the row is still running,
   because a running operation turns "No recent update" by wall-clock age alone.
   `ActivityLog.revision` changes when a record is stored, the Candidate's suppression or loss count
   rises, or it ends, and with the log-wide counters (evictions, invalid and unsupported records,
   revision gaps); it does not change for an event that stores nothing (plain Logs, replayed
   revisions, updates to a terminal record). The final refresh (evaluation finished) and a click
   always render. A render that raises is retried on the next refresh.

3. **Stylesheet once.** `activity_html` no longer prepends `STYLE`: the evaluation view already
   injects it once, and every row now holds its activity.

Verified in Jupyter Lab 2026-10-22 with the kernel held 60 s: a row opened mid-run with live
activity, closed mid-run, and kept its state after the queued clicks drained.

## 4. Browser support

`:has()` is in every browser JupyterLab 4 supports (current Chrome, Firefox, Safari; Chrome 105+,
Firefox 121+, Safari 15.4+). VS Code desktop renders widgets in its bundled Chromium; Colab and
browser-hosted VS Code run in the user's browser. No fallback for older browsers.

## 5. Alternatives rejected

- **Wait loop delivers widget messages** (jupyter-ui-poll technique inside `evaluate_sync`):
  depends on ipykernel internals, must skip queued `execute_request`s to avoid re-entrant cells,
  and touches the run path.
- **HTML `<details>` inside the HTML widget:** the open state is lost on every value replacement.

## 6. Accepted limits

- The Show/Hide tooltip follows Python, so mid-run it updates once the kernel is free (an existing
  test pins its text).
- A row's activity, including an open row mid-run, can lag by up to one 2 s step.
- Cost of the activity renders in a live run with 1 s ticks and 8 Candidates running (the
  runner's cap), each receiving records every tick (synthetic completed model calls, Apple-silicon
  MacBook). Below the log's 2000-record cap only running rows render, once per 2 s step: 9 or 50
  Candidates ~12–15 ms per tick. At the cap every new record evicts one and changes the eviction
  count all rows show, so every row renders once per step: 9 Candidates ~30 ms per tick and
  ~440 KiB/s of changed HTML, 50 Candidates ~130 ms per tick. Rendering on every tick would double
  these; `main` rendered none mid-run, because no row could open.
- Selectors rely on ipywidgets' `widget-toggle-button` / `mod-active` / `fa-<icon>` classes,
  present in ipywidgets 7 and 8 (the `notebook` extra's range); `_ui/card_style.py` uses the same.
- Jupyter Lab verified visually; VS Code checked by source (its Jupyter extension loads the standard
  `@jupyter-widgets/controls`); Colab not checked.
