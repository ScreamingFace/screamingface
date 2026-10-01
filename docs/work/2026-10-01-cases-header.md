---
ticket: OME-1422
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---
# Inline cases header

## Intent and plan
User requests pagination, count, and export/download inline inside the cases box header.
Reuse the case body without its separate static frame; give the notebook case box one
header containing its collapse control, range, Previous/Next, and single export slot.
Use existing report colors/borders and responsive wrapping. Preserve export state behavior.

## Verification
Header ownership, one frame, collapse and pagination, SDK gates, live notebook screenshot.
User-approved layout changes supersede prior widget-tree expectations only.

## Implementation and visual check
The live cases box owns one header, error area, and original case body. The static renderer
keeps its original details frame; live rendering reuses only the body, preventing a nested
or duplicated header. Case results remains collapsible. The range has one total, and
Previous/Next are grouped so responsive wrapping never splits them apart. The export slot
is part of the header in every state.

JupyterLab confirmed collapse/reopen and a clean two-row header at the available narrow
width: title/range followed by grouped navigation and export, all within the same border.
Screenshot: `docs/work/assets/OME-1422-report-browser.png`. 52 focused report tests and the
final 14 browser tests pass. No persistence/recovery or Engine behavior changed.

Final SDK gates green: 2,118 passed, 26 skipped, 26 paid tests excluded; 95.72% coverage;
lint, format, Pyright, notebook checks, build and distribution pass. The final run includes
the grouped narrow-screen navigation adjustment. Commit: `fix(client): integrate controls into cases header`,
existing draft PR #1156.

Follow-up requested by owner: shorten the range label to `26–50 of 46002`, removing
Showing and total repetition. Validate the approved text expectations and refresh the notebook.

Compact range verified in the refreshed notebook; all 14 focused browser tests and the
full SDK gates pass (lint, format, Pyright, coverage suite, notebooks, build, distribution).
