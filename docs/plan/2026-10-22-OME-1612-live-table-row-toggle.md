# OME-1612 plan — rows in the live progress table open while an evaluation runs

Spec: `docs/spec/2026-10-22-OME-1612-live-table-row-toggle.md`. Stack: `screamingface`
(`sdlc-python`). One unit, one PR, one commit.

## Steps

1. **RED** — `packages/screamingface/tests/test_activity_live_toggle.py`: a closed row's activity
   is filled, without `STYLE`; the CSS rules; a finished row renders at most once per step and only
   on change; a running row once per step, a queued one only on change; end, loss and suppression
   rises, evictions and a late result render; events that store nothing do not; the final refresh
   renders at once; a failed render is retried. Confirm each fails on `origin/main`.
2. **GREEN** — `_ui/activity_view.py` (CSS, no `STYLE` in `activity_html`),
   `_ui/activity_state.py` (`revision`), `_ui/activity_widget.py` (render step and key, no icon
   swap), `_ui/evaluation_widget.py` (`final` on the last refresh). Prior tests unmodified.
3. **GATES** — `uv run .claude/scripts/run_gates.py screamingface` from the repo root.
4. **VISUAL** — scratch notebook holding the kernel 60 s against the real code in Jupyter Lab.
5. **LEDGER OUTCOME → COMMIT** (`fix(client): open live progress rows while an evaluation runs`)
   with the `docs/tasks/` mirror; `Refs: OME-1612` in the PR body.
