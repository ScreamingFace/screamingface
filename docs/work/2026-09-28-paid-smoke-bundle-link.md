---
ticket: OME-1392
stack: repo
status: in_progress
started: 2026-09-28
finished:
---

# paid-smoke-bundle-link — link the debug bundle from the paid smoke's run summary

## Intent

The paid smoke's run summary shows the per-board table, but the debug bundle (stack logs,
one Report per board, junit.xml) sits only in the run's Artifacts panel at the bottom of
the page. Debugging a press starts from the table, so the table should end with a direct
download link to that run's bundle.

## Planned changes

- `.github/workflows/screamingface-paid-inspect-smoke.yml`: give the upload step an id;
  add a step after it that appends the upload's `artifact-url` output as a markdown link
  to `$GITHUB_STEP_SUMMARY`, skipped when the upload wrote nothing (empty url).

## Test plan

- YAML lint of the workflow.
- No free local harness for Actions step summaries; the proof is the owner's next paid
  press showing the link under the table (the lane is paid, so no agent-run press).

## Acceptance

- The next paid press's summary ends with a "Download the debug bundle" link whose URL
  has the shape `…/actions/runs/<run_id>/artifacts/<artifact_id>` and downloads the zip.
- A run whose upload found no files writes no link (no dead link).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (workflow + this ledger + the OME-1392 mirror).
- **Commits:** `93147b15` — ci(screamingface): link the paid smoke debug bundle from the run summary
- **Gates:** pre-commit (check yaml, whitespace, EOF) passed; yamllint relaxed passed. No Python touched.
- **Deviations:** none. Acceptance waits on the owner's paid press (agents never press it).
