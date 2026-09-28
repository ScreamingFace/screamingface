---
id: OME-1392
linear_url: https://linear.app/openmined/issue/OME-1392/link-the-paid-smokes-debug-download-from-its-run-summary
status: in_progress
type: task
priority: low
labels: [client-sf, agentic, autonomous]
parent: OME-1299
created: 2026-09-28
closed:
---

# Link the paid smoke's debug download from its run summary

The paid smoke's run summary shows one row per board, but the debug bundle (stack logs, one
Report per board, junit.xml) is only in the run's Artifacts panel at the bottom of the page.
After the upload, append a "Download the debug bundle" link to that run's zip
(`…/actions/runs/<run>/artifacts/<id>`) to the summary; write nothing when no bundle was
uploaded.

- 2026-09-28: filed at PR-open; ledger `docs/work/2026-09-28-paid-smoke-bundle-link.md`.
