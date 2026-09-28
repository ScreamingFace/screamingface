---
ticket: OME-1031
stack: screamingface
status: done
started: 2026-09-28
finished: 2026-09-28
---

# report-accounting — Completed Report accounting and review notebook

## Intent

Implement the approved OME-901 Client presentation slice (OME-1031): derive exact accounting views from retained operations/evidence and expose them in completed Reports. User authorized implementation and a draft PR on 2026-09-28, including a Jupyter review notebook.

## Planned changes

- New derived accounting module and report-table renderer in packages/screamingface/src/screamingface.
- report.py, _evaluation/results.py, _ui/report_view.py: integrate views, unique member usage and completed report breakdown.
- New append-only accounting and rendering tests; same-run live-event preservation regression.
- Deterministic review notebook and builder support, README usage; existing spec/plan and task mirror as needed.

## Test plan

- RED: exact sums, missing records/fields, repeated ownership, unknown costs, negative remainder, cache hits, grading, loops, member attribution, HTML escaping and case expansion.
- Integration: retained accounting and unchanged generic Span/Usage delivery in the same evaluation.
- Full screamingface gates; execute review notebook without paid calls; visually inspect light/dark report HTML.

## Acceptance

- Shared Client-only views grouped by stage/operation/member/model/Case; root totals unchanged.
- No guessed accounting, member wall times or token remainder; inconsistent reconciliation fails open.
- Completed report UI and runnable Jupyter notebook available with draft PR.

## Outcome

Implementation is complete in the isolated `OME-1031-report-accounting` branch; all final stack gates passed. Owner explicitly approved the additive test snapshot
update on 2026-09-28 (“yes i apprrove changeing the tets”).

- Added `accounting.py`, `_ui/accounting_view.py`, deterministic notebook authoring helper,
  `14_report_accounting.ipynb`, and four focused test modules. Integrated the existing report
  renderer and exact direct-model member usage; documented the API in README and changelog.
- RED/GREEN: new accounting tests first failed for the missing projection; focused tests now pass.
  The notebook builder's existing runpy regression found a companion import issue, fixed by
  resolving the companion relative to the builder rather than the process import path.
- Full gate attempt: lint, formatting and types passed; pytest reported 1,887 passed, 26 skipped,
  26 deselected, and one expected public-surface snapshot failure (the new property in two
  namespaces). Coverage 95.74%; accounting projection 100%. No prior test source was edited.
- Notebook provenance plus new focused tests: 35 passed. Deterministic notebook check, wheel/sdist
  build and distribution check passed separately. All notebook cells also executed via nbclient.
- Visual review: light/dark HTML, narrow viewport, expandable Case accounting and keyboard-scrollable
  table. Synthetic zero-cost cache hit and explicit unknown observations are inspectable offline.

### Wisdom and confidence review

The module is a pure derived view over existing Engine owners, without new transport or serialized
summary truth. Tests cover strict unknowns, disjoint identity, duplicate/unknown records, negative
reconciliation, loops, cache hits, HTML escaping and same-run live-event isolation. The public API
addition is deliberate and documented; the snapshot refresh was explicitly owner-approved and independently checked as additive. Root totals and scores remain authoritative, and diagnostics never include payloads.
Direct composite-member and loop ownership remains unsupported as specified. No new package
dependency is added. Existing large integration files receive only small hooks; new modules stay
under 450 lines.

### Approved test contract transition

The API snapshot adds only `CandidateResult.accounting` in the two existing namespaces.
All previous entries remain identical; no existing Python test source changes. The append-only
runner cannot recognize additive JSON edits, so the explicitly approved snapshot transition uses
`--skip-append-only`; the complete stack gates remain enabled. The diff is checked separately to
ensure only the two approved snapshot entries changed. Notebook launch instructions use JupyterLab;
review fixtures use distinct run identities so multiple rendered examples do not share DOM ids.

### Final validation

`uv run .claude/scripts/run_gates.py screamingface --skip-append-only`: ALL GATES GREEN
(lint, format, pyright, full pytest with >=95% coverage, deterministic notebooks, build and
distribution checks). The approved JSON snapshot adds exactly two property entries and all
previous snapshot values and Python test sources remain identical. Final notebook cells execute
without errors. Commit: `feat(client): show completed operation accounting`. Delivery is a draft
PR; the issue remains open for review and merge.

## Readability follow-up — 2026-09-28

Owner found the operation accounting table hard to digest after reviewing JupyterLab. Continue
this draft PR in its isolated worktree. Plan: make cost and plain-language cache outcomes the
primary view, put call/token/provider details behind a disclosure, and preserve exact accounting
and per-Case access. Keep existing tests unchanged and add presentation regressions before code.
Validate full Client gates and inspect the refreshed notebook preview. No public contract changes.

## Approved case-tab revision

Owner approved replacing the separate accounting section with Answer & grading / Cost & usage
views within each selected Case, using readable activity blocks instead of subtables. This
supersedes the uncommitted cost-summary iteration. Preserve run totals at the top, keep run-wide
unattributed cost labelled there, and never imply a Case total or remainder from incomplete data.
Use native radio controls styled as tabs for keyboard support and script-free notebook rendering.
Update the presentation tests to the explicitly approved new layout while preserving accounting,
escaping, unknown-value and inconsistent-data assertions. No accounting API changes.

### Case-tab validation and review

The final layout removes the separate operation table. Case panels retain their question and
verdict above native Answer & grading / Cost & usage controls. Each retained operation or judge
observation has a labelled block with cost, calls, named cache outcomes, input/output tokens and
provider time. Unknowns remain explicit; run-wide unattributed cost stays with the run summary.

Added three regressions for Case isolation, labelled values without subtables, and independent
native control groups. Updated only the draft's panel/notebook presentation assertions to the
approved layout; numeric, missing-data, inconsistency and escaping checks remain. Focused
accounting checks: 24 passed. JupyterLab and light/dark standalone renderings were inspected;
click switching works in JupyterLab and native keyboard switching works in standalone HTML.
JupyterLab needs more specific definition-list CSS to prevent its notebook styles overriding
the responsive field layout. No accounting calculations, public API or wire records changed.

Final follow-up gate run: `uv run .claude/scripts/run_gates.py screamingface --skip-append-only`
reported ALL GATES GREEN (ruff, formatting, pyright, full pytest with >=95% coverage,
notebook provenance, package build and distribution checks). The skip covers the owner-approved
snapshot and presentation assertion transitions described above. Notebook source remains
output-free and deterministic. Deliver this revision to the existing draft PR #1097.

## Approved visual polish

Owner approved a second polish pass: underline-only tabs, cost beside the operation title,
compact grouped metrics keeping input/output tokens together, explanations in a native
About these numbers disclosure, and reduced spacing. Continue OME-1031 in the existing
worktree and draft PR. Preserve exact amounts, unknowns, scope and all accounting semantics.
Plan: add presentation regressions, adjust only the accounting renderer, inspect both themes
and the notebook, run Client gates, then push. Acceptance: compact readable blocks with native
controls and all previously available fields retained.

Polish review: the new disclosure/header/grouping test failed before implementation and passes
afterward; all eight focused rendering tests pass unchanged except the additive regression.
Verified compact layout in light JupyterLab and standalone dark HTML; About these numbers opens
and closes natively. A fresh JupyterLab tab was needed to replace a stale preview. Exact costs
remain at four decimal places to preserve small billed amounts; no accounting data is hidden
or inferred by the layout. This is a presentation-only change with no public contract change.

Polish outcome: ALL GATES GREEN from the full Client runner (lint, format, types, pytest with
>=95% coverage, deterministic notebook checks, build and distribution checks). The existing
approved snapshot/presentation transition still requires --skip-append-only; this polish adds
one test and changes no prior assertions. Preview execution outputs are excluded from Git.

## Owner-requested help removal

Remove About these numbers and its explanatory paragraph from Case accounting. Remove unused
help styles and update the corresponding presentation assertions to require absence, preserving
header/field coverage. Owner explicitly requested this reversal. Verify focused rendering tests,
full Client gates and refreshed JupyterLab; update the existing draft PR.

Help-removal outcome: all eight focused rendering tests pass and the full Client gates are
green (lint, format, types, full pytest/coverage, notebooks, build and distribution). Verified
JupyterLab renders the cost blocks directly under the tabs with the requested text absent.

## Owner-approved separator refinement

Remove the first cost block's top rule while retaining rules between adjacent operations.
Use the adjacent-sibling CSS selector; preserve the active-tab underline and all content.
This is a reversible CSS-only refinement; verify existing rendering tests, full gates and
notebook appearance without adding an implementation-mirroring test.

Separator outcome: verified in JupyterLab that the first operation has no top rule while
subsequent operations retain separators. Full Client gates are green: lint, format, types,
pytest/coverage, notebook provenance, build and distribution. No test or data changes.
