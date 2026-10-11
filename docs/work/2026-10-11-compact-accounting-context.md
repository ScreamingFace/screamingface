---
ticket: OME-1570
stack: screamingface
status: completed
started: 2026-10-11
finished: 2026-10-11
---

# Compact accounting context and rebuildable cache — third SDK slice

## Intent

Extract accounting context/cache from #1156 after #1241/#1269 merged. Preserve exact attribution, nullable totals and inconsistency while avoiding retained accounting rows/evidence for run-level disclosure. Reuse compact disk context.

## Planned changes

Streaming accounting/context, optional saved cache, private disk index access, existing cost disclosure consumers, new regressions, spec/plan/changelog and focused ticket mirror. No eager decoder warming, notebook pagination/browser, lifecycle, Engine, public API or dependency changes.

## Test plan

RED first: contexts match public breakdown across missing/unknown/inconsistent observations; bounded judge evidence memory; saved cache hits avoid decoding, invalid/stale/read-only cache handling, metadata changes and exact disclosure HTML. Preserve inherited tests and main provenance. All SDK card gates and independent Standards/Spec review.

## Acceptance

Context retains only attribution maps, nullable remainder and consistency; cache derived/optional; current disclosures consume compact context/per-Case rows. Report bytes/signatures unchanged. Main-based draft, existing epic, no paid calls or GitHub comments.

## Outcome

Implemented compact streaming context, lazy optional disk cache and unchanged accounting disclosures. Added 34 regressions in new test files; existing tests remain intact. Initial context/cache regressions failed against main. Strict cache version/type tests exposed three failures against the original #1156 implementation. Independent Standards review reproduced an invalid remainder; all four new semantic regressions failed before the fix and pass afterward. Review now reports no actionable findings; Spec review also passed. All screamingface gates passed: append-only tests, Ruff lint/format, Pyright, full parallel pytest (96.10% coverage, 95% floor), notebook validation, wheel/sdist build and distribution checks. Focused accounting tests: 50 passed; independent reviewers also checked unchanged provenance/Named Scores/archive behavior. No inherited tests or snapshots changed. Draft publication on OME-1570-compact-accounting-context.

Base main e7833e35cf36c413ca2dd8509e48f4515c25b8f7; source1156 b3b503d668eb7c78b7daed780eea39e510e6c7a3. Isolated clone because macOS denies shared-checkout reads.
