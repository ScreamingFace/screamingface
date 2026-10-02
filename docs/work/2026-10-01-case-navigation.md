---
ticket: OME-1422
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# Shared case navigation

## Intent

Implement the owner's approved layout: Candidate All compares candidates on one case, selecting a candidate browses its cases, Go to case number uses exact identity, and summary names select the shared browser. Replace the text-search UI.

## Planned changes

- Compact navigation model from indexed case identities, with no prompt scans.
- Candidate selector, exact case input and mode-aware page controls in the existing header.
- Live summary-name controls linked to the same candidate selection.
- Keep 25-result bound and existing details/Download behavior; coalesced clicks remain enabled.
- Update superseded search interaction tests under the owner's explicit UI instruction.

## Test plan

Exact numeric/string identities, missing IDs, multiple candidates, sparse/reordered IDs, singleton reports, more than 25 candidates, candidate selection, lossless download, disk reads and rapid clicks. Full SDK gates and live notebook trial.

## Acceptance

No text search, no additional report-detail tabs or per-candidate case panels. Controls default to All and use real case identity. Navigation and lookup do not read every case body.

## Outcome

Implemented `CaseNavigation` over indexed case identities and the approved inline Candidate / Go to case controls. Summary name buttons select the shared browser. All compares one case across candidates; individual candidates retain 25-case pagination with the requested case selected. More than 25 candidates remain bounded per page.

All SDK gates green: Ruff, format, Pyright, full pytest at the required coverage, notebook checks, build and distribution checks. Nine navigation tests cover grouping, exact IDs, disk reads and rapid clicks; existing interaction tests retain export/error/paging coverage.

Live JupyterLab verified typed Enter navigation to case 124 across 11 candidates; candidate-5 retained case 124 in its 101–125 page; five rapid Next clicks reached case 129; invalid 46000 retained the results with an error; summary candidate-2 selected the same browser. Restored All / case 0 and saved screenshot in `docs/work/assets/OME-1422-report-browser.png`.

Synthetic 46,002-result fixture: navigation/browser construction 0.8554 s, exact ID lookup 0.000046 s, 11-candidate page rendering 0.0025 s, individual last-page rendering 0.001 s. Backend timings exclude frontend transfer/paint. No model calls or source-result deletion.

Browser automation `fill()` alone did not commit the ipywidgets Text value; real key typing and Enter did. This was verified in the live notebook before completion.

## Owner-approved row refinement

Removed the Candidate prefix and renamed All to All Candidates. Live rows use 44 px and a bounded scrollable rail, omitting redundant candidate labels in candidate mode and redundant case/preview labels in comparison mode. Go to case uses the existing selected detail and highlight plus initial CSS scroll snapping; snapping ends after insertion to avoid trapping manual scrolling. No new frontend dependency or executable report-content scripts. Updated the navigation interaction test to retain mode-specific label expectations.

Validation: 35 focused navigation/browser/interaction tests pass, all SDK gates green, and final CSS lint/format checks pass. Live JupyterLab verified Go to 124 selected the final row on candidate-5’s 101–125 page; the rail scrolled to 801.5 px and the selected row was visible. Computed scroll-snap-type returned none after initial insertion. Manual scrolling stayed at the new position after leaving the rail. Saved `outputs/case-row-jump.png` as local visual proof; updated the PR screenshot with All Candidates comparison mode.
