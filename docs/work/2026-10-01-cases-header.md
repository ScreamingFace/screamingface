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

Owner follow-up: replace the interactive Case results toggle with a plain title; keep
cases visible. Shorten the single export control labels to Export and Download.
Plan: remove the toggle callback, preserve inline actions, update the explicitly
superseded UI expectations, run SDK gates and refresh the notebook.

Outcome: replaced the ToggleButton with a styled Label and removed the collapse
callback. Export / Preparing… / Download preserve the existing single-control behavior.
The revised UI expectations failed before implementation; all 14 browser tests now
pass. Full SDK gates green. Notebook restart recovered the fixture and visibly showed
the plain title with inline actions; updated the PR screenshot. No persistence, public
API or schema changes. Review: removing the callback is the smallest implementation;
only the explicitly requested title interaction and labels changed.

Owner follow-up: add only a search input between the plain title and compact range.
Search all retained case fields and candidate names on submit; scan one case at a time
in a worker when running in a notebook, disable navigation during the scan, reset to
the first matching page, and keep export lossless for all cases. Clearing restores all
positions without scanning. Test matches beyond the initial page and failure recovery.

Outcome: added submitted search inline between title and range. Queries scan the
streaming candidate case iterators, retain only matching positions, and run in a worker
in the notebook. Blank search restores all positions without a scan. Errors preserve
prior results and restore controls. No filter menus or alternate export scope added.
All 16 focused browser tests and full SDK gates pass. Live notebook search for
answer 4181 found 11 matches across the 46,002-case fixture; clearing restored the
first page. Refreshed the saved notebook and PR screenshot. The initial browser
verification used stale restored widgets; recreating them through native notebook
input resolved it. Review: memory stays bounded to one case plus match indices;
public APIs, persistence and JSON export remain unchanged.
