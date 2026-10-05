---
ticket: OME-1422
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---
# Single report export control

## Intent and plan
User approved one control: Export JSON → Preparing… (disabled/spinning) → Download JSON.
Replace the export button in place with the file link on success; remove redundant normal
status text. Keep duplicate suppression, error explanation and return-to-Export JSON behavior.

## Verification
Test exactly one export control across transitions; full SDK gates and live notebook export.
User authorized updating superseded ready-button expectations. Use the repo Python/design
skills already read; append-only exception applies only to these approved UI changes.

User clarification: on failure restore the original Export JSON label, enabled, with an error message.

## Implementation and review
One widget slot owns the export action. It contains the button while idle/preparing and
replaces it with a styled native download link when complete. The old button is detached
from the displayed tree, normal status text is empty, and errors alone use the alert area.
The immutable Report and existing duplicate suppression are unchanged. The no-server fallback
still displays the saved path instead of inventing a broken download URL.

The regression test checks the slot before/after export and exactly one native link. Existing
busy and failure tests use the clarified labels; 13 focused browser tests pass. JupyterLab
confirmed one disabled Preparing… button, followed by one Download JSON link and zero leftover
export buttons. Screenshots show the actual synthetic export trial; no paid calls were made.

Final gates green: lint, format, Pyright, 2,117 passed / 26 skipped (26 paid tests excluded),
95.72% coverage, notebook checks, build and distribution. The first full run loaded the old
Retry export expectation before the user clarified the wording; the final rerun passes.
Commit: `fix(client): use one report export control`, draft PR #1156.
