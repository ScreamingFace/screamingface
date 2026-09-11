---
ticket: OME-983
stack: screamingface
status: in_progress
started: 2026-09-11
finished:
---

# OME-983 — Name Candidates in Report failure summaries

## Intent

Make the combined Report failure banner identify which Candidate each failed Case belongs to.
The user approved the local preview, then Candidate headings and a direct ticket update.

## Planned changes

- Update `_ui/report_view.py` to group within each Candidate and prefix multi-Candidate lines.
- Extract the existing Candidate/member/Case failure traversal in `report.py` for reuse.
- Append focused regression coverage to `tests/test_report_panel.py`.
- Record the local spec, plan and task mirror.

## Test plan

First reproduce identical failures on Case 153 under two Candidates; assert separate named lines.
Cover grouping within a Candidate, escaping names, single-Candidate compactness and unchanged JSON.
Run the screamingface gate runner and render light/dark previews.

## Acceptance

Candidate names distinguish shared Case ids in multi-Candidate summaries. Single-Candidate summaries,
complete failure disclosure and alert semantics remain intact.

## Outcome

- Implemented semantic Candidate headings with indented failure lists for multi-Candidate Reports.
- Single-Candidate summaries and full raw JSON remain unchanged; all text is escaped.
- Shared Candidate/member/Case failure traversal keeps the summary and disclosure aligned.
- RED: the two regression tests failed before the grouping/heading implementation.
- Validation: all 37 Report-rendering tests pass; `run_gates.py screamingface` reports ALL GATES
  GREEN (append-only, lint, format, pyright, full pytest with >=95% coverage, notebook checks,
  build and distribution checks). Gate log: `.docs/OME-983-headings-gates.log`.
- Light and dark screenshots inspected; local previews remain in gitignored `.docs/`.
- Wisdom review: no public API, schema or dependency changes; one shared traversal, no new
  interpretation of errors. All tests from main remain unchanged. Only this worktree's new
  preview assertions were revised for the explicitly approved headings.
- Earlier full-suite attempts were interrupted during reconnect waits; the final run completed
  successfully without bypasses. The runner suppresses successful test counts, so only the
  independently verified 37-test Report count is reported here.
- Commit: `fix(screamingface): group Report failures under Candidate headings` (Refs: OME-983).
- Linear moved to In Progress and description updated directly, without comments.
- Draft PR follows this commit; issue and mirror stay open pending review and merge.

## Approved refinement — 2026-09-11

User approved Candidate headings with indented failure lines, and direct ticket updates without
comments. Refine the local preview tests to this expressly approved layout; all tests from main
remain unchanged. Use semantic headings and a list per Candidate, existing error text and tokens.
Run Report regressions, full gates, and refresh notebook output and light/dark previews.

## Screenshot cleanup — 2026-09-11

Owner requested removal of tracked preview images. Remove both PNGs from the PR diff and
remove their image links from the PR description. Keep the local `.docs/` copies.
Validation: documentation/assets only; `git diff --check` and commit hooks. Earlier code gates
remain applicable because no implementation or tests changed. No Linear comments.
