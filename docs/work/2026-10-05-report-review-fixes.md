---
ticket: OME-1448
stack: screamingface
status: in_progress
started: 2026-10-05
finished:
---

# report-review-fixes

## Intent

Fix reviewed download, inline lifecycle, notebook loading, PID and sequence regressions; consolidate saved-file atomic writes.

## Planned changes

SDK source and new regression tests only, with spec/plan/task mirrors and changelog documentation.

## Test plan

Write regression tests first and record their failure; run focused tests, preserved SDK tests, coverage, Ruff, Pyright, notebooks and distributions.

## Acceptance

Regression tests pass, existing reports retain values, full SDK gates pass.

## Outcome

All SDK gates passed after correction: Ruff, format, Pyright, full parallel tests at the >=95% coverage floor, deterministic notebooks, distribution build/check. Eighteen targeted regressions pass, including gzip errors expanding to 32MiB constrained below 2MiB traced peak in sync and async transports, and queued notebook selection events. Independent Standards and Spec reviews report no blockers.

Initial regressions failed before their respective source corrections. Compatibility correction preserves all inherited transport body assertions: persist_inline retains the body; decoding prefers the durable path. Synthetic outcome wrappers that replace the body now also clear the old result_path. The existing async candidate selection assertion awaits its worker. These are the two justified inherited test-file changes, documented here; --skip-append-only was used for those changes while all functional assertions and full tests ran unchanged otherwise.

Reuse OME-1448 / OME-1422 and push this correction commit to the unchanged PR #1156 head as a normal fast-forward. First independent export slice is OME-1486, based on main. No merge or closure of the umbrella PR.
