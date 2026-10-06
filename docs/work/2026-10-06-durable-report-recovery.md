---
ticket: OME-1503
stack: screamingface
status: in_progress
started: 2026-10-06
finished:
---

# Durable report recovery — second split from #1156

## Intent

Keep completed evaluations readable after a kernel failure without rerunning models, in a main-based draft limited to collection, verified downloads, indexing, explicit recovery, and fusion totals.

## Planned changes

SDK persistence modules, transport and decoder integration, disk Case sequence support, saved-report API, nullable member accumulation, new regression tests, README/changelog, and these spec/plan/task records. Atomic helper reused from #1241.

## Test plan

Existing recovery regression additions first: lazy disk decoding, inline/artifact persistence, integrity checks, partial recovery and storage errors, sync/async paths, nullable fusion summaries. Preserve every inherited assertion. Full SDK card gates, source scope audit, and compatibility with #1241.

## Acceptance

All SDK gates pass; full values/provenance and healthy siblings survive; no notebook/lifecycle/accounting-cache modules enter this PR; no Engine changes or paid calls.

## Outcome

Implemented and validated; ready for draft review. Sources pinned at #1156 b3b503d6 and #1241 0b2a3b03; base main b83b9670. An isolated clone/worktree is used because macOS denies reads of the shared checkout.


## Extraction and review evidence

The initial new recovery/member regression run failed on main (24 failures, 10 passes), including missing persistence modules and Case-count-dependent member memory. The first integrated run passed 74 recovery regressions and 33 existing archive-cost compatibility tests. Added 37 download/membership/atomic regressions also passed.

Independent Standards and Spec review reproduced malformed artifact tickets and conflicting sibling evaluation contexts bypassing the healthy partial-report contract. New corrected regressions failed against the actual staged pre-fix source in disposable scratch (16 failures), then passed after validation. A further four regressions reproduced timezone-naive saved timestamps reaching authentication; shared pre-download timestamp validation now rejects these with named metadata errors. Metadata/main compatibility: 25 passed; Ruff and Pyright green.

All SDK card gates passed on the initial extracted implementation at 96% coverage. The final full run after metadata corrections is recorded below. A disposable copy applied #1241's report export patch cleanly and passed 65 recovery/export tests, preserving its serializer, long-name handling, and descriptor cleanup. The helper and inherited atomic tests are identical to #1241.

Public surface snapshot changes only add sf.reports and Client/AsyncClient save_results; every inherited Python test/assertion remains unchanged. The exact snapshot transition is pinned in .claude/test-change-approvals/OME-1503.json. Direct internal transports preserve legacy defaults; public Clients explicitly enable saving. New tests imported from #1156 enable saving explicitly where needed. Tests and helpers belonging to notebook/lifecycle/cache slices were excluded; recovery assertions retained. Main's newer archive savings and unpriced-hit provenance were preserved.

No Engine/runtime/UI files, compact accounting cache, lifecycle notices/markers, or export serializer enter this PR. OME-1448/OME-1422 remain open for the umbrella scope. No paid model calls or live hosted tests.


## Final gates and handoff

Final SDK runner after all corrections: ALL GATES GREEN. Approved API snapshot transition and append-only test check, Ruff lint/format, Pyright, full parallel pytest (2,400 offline tests collected; 36 paid-lane tests deselected), deterministic notebook checks, wheel/sdist builds, and distribution checks passed. Final coverage: 96% (11,403 statements, 449 missed). Independent Standards and Spec reviews have no remaining required changes.

The implementation spans SDK persistence/download/index modules, disk-backed Report access, public saved-report APIs and Client options, bounded member totals, focused regression additions, API snapshot approval, package dependency metadata, README/changelog and these records. No inherited Python test or assertion changed. Extraction deviations: preserve newer main accounting provenance, remove later-slice UI/lifecycle/cache behavior, keep internal transport defaults compatible, and add pre-download metadata isolation checks found by review. Draft targets main; merge #1241 first. Ticket stays open for review and merge.
