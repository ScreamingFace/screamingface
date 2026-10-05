---
ticket: OME-1422
related: OME-1448
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---
# Restore report presentation and guard export

## Intent
User requests the original case presentation with pagination only, removing the added
Case detail / Full content tabs, and a disabled busy state preventing duplicate exports.

## Planned changes
Reuse original report rail and case panes for the current 25-case page. Export asynchronously
in notebooks, disable immediately, reject duplicate clicks, retain ready download, allow retry
on failure. Update superseded browser expectations, docs, notebook and existing draft PR.

## Test plan and acceptance
Original markup and bounded pages; no added widget tabs; export busy/deduplication/success/error
states; SDK gates and live Jupyter verification. No changes to durable result data or recovery.

## Outcome
Reused the original report rail, pane renderer, and CSS for each 25-case page. Removed
the replacement select box and added tabs. Original 10,000-character text previews remain;
full export is lossless. Widget output contains only the current page (regression bound 1 MB).

Export sets disabled/busy synchronously, runs file generation in a worker via the notebook
async event loop, ignores duplicate queued clicks, retains a ready download, and enables retry
after storage errors. A synchronous fallback serves callers without an event loop.

Verification: 2,116 passed, 26 skipped, 26 paid tests deselected; 95.72% coverage.
All SDK gates passed: Ruff, formatting, Pyright, coverage, notebook checks, build, distribution.
The final status-copy correction was rechecked with lint and all 12 browser tests.
JupyterLab verified the disabled spinner during the 2.22 GB export, completion/download,
Next to cases 26–50, and original radio selection of case 26. Screenshots are in
`docs/work/assets/OME-1422-report-browser.png` and `OME-1422-export-busy.png`.

User explicitly authorized replacing the tabbed UI. Superseded UI expectations were updated;
`--skip-append-only` records that approved contract change; no other gates were bypassed.
Design review: reusing the existing renderer keeps appearance consistent and removes duplicate
UI machinery. Disk persistence and recovery are unchanged. No paid calls or Engine changes.
Commit: `fix(client): restore report layout and guard export requests`, existing draft PR #1156.
