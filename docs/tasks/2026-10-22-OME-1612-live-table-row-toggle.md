---
id: OME-1612
linear_url: https://linear.app/openmined/issue/OME-1612/rows-in-the-live-progress-table-cant-be-opened-while-an-evaluation-is
status: in_review
type: bug
priority: medium
labels: [bug, client-sf, agentic, autonomous]
created: 2026-10-15
closed:
---

# OME-1612 — Rows in the live progress table can't be opened while an evaluation is running

The browser now owns a Candidate row's open/closed state and chevron through CSS on the toggle's
browser-side `mod-active` class, so a click opens the row while `sf.evaluate` holds the kernel; the
ticker keeps every row's activity current, rendering each row at most once per 2 s step. Verified in
Jupyter Lab. Spec: `docs/spec/2026-10-22-OME-1612-live-table-row-toggle.md`. Plan:
`docs/plan/2026-10-22-OME-1612-live-table-row-toggle.md`. Ledger:
`docs/work/2026-10-22-live-table-row-toggle.md`.
