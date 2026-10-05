---
ticket: OME-1486
stack: screamingface
status: in_progress
started: 2026-10-05
finished:
---

# streamed-atomic-report-export

## Intent

Extract the first independently mergeable client PR: case-streamed report.v1 serialization and durable atomic JSON export.

## Planned changes

SDK source and new regression tests only, with spec/plan/task mirrors and changelog documentation.

## Test plan

Write regression tests first and record their failure; run focused tests, preserved SDK tests, coverage, Ruff, Pyright, notebooks and distributions.

## Acceptance

Original JSON bytes and public API remain unchanged; no persistence or notebook dependency enters this PR; all SDK gates pass.

## Outcome

All SDK gates passed: append-only tests, Ruff, format, Pyright, full parallel pytest with the 95% coverage floor, deterministic notebooks, wheel/sdist build and distribution checks. New serializer tests failed before implementation; all 16 focused export/atomic tests pass. Independent Standards and Spec reviewers found no required export changes.

Based on origin/main aa582c12e30e17f527528d8bf649df1e696a2b51. Source export work credited to Ionésio from PR #1211, extracted from PR #1156. No public snapshot or dependency changes. Issue OME-1486 is the focused child of OME-1294.

Approved follow-on split (each PR based on main after prerequisites land): durable collection/indexing/explicit recovery/fusion totals; compact accounting context/cache; paginated notebook browser; lifecycle discovery. OME-1448 and OME-1422 retain the remaining umbrella scope. This draft is the first slice only.
