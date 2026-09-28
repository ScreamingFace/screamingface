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
