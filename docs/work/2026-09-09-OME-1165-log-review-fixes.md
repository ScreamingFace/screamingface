---
ticket: OME-1165
stack: url4
status: done
started: 2026-09-09
finished: 2026-09-09
---

# OME-1165 — Address PR 877 Log review feedback

## Intent

Owner requested both review fixes on 2026-09-09: restore public Log serialization compatibility and make failed producer submissions diagnosable without exposing payloads.

## Planned changes

- packages/url4/src/url4/observe.py: reconstruction for Log and fixed-reason drop counters.
- packages/url4/src/url4/_log_attributes.py: immutable mapping with copy/serialization support.
- packages/url4/tests/unit/test_log_review_fixes.py: additive regressions.
- packages/url4/README.md: serialization and diagnostics API.
- Existing OME-934 spec/plan and OME-1165 task mirror: record approved review refinement.

## Test plan

Write and run failing regressions first. Cover pickle protocols, deepcopy, asdict/JSON, empty/populated scalar mappings, immutable round trips, every drop reason, repeated failures, concurrent off-thread calls, read-only counter snapshots, saturation, successful emission and process-control propagation. Preserve previous tests. Run full URL4 gates.

## Acceptance

Both review concerns fixed on PR 877; attributes stay immutable; counters contain only fixed reasons and bounded integers; callbacks, payloads and errors never enter diagnostics. Direct observation semantics remain unchanged.

## Outcome

- **Actual files:** As planned; one private attribute mapping module, observation changes, 27 new regression cases, README, spec/plan refinement, task mirror and this ledger.
- **Commits:** fix(url4): preserve Log serialization and count dropped submissions; Refs: OME-1165.
- **Gates:** Initial RED: 24 cases failed on mappingproxy serialization or absent counters. Additional immutability regression exposed deletion of wrapper storage, corrected before GREEN. Full `uv run .claude/scripts/run_gates.py url4` passed append-only, Ruff lint/format, Pyright and full pytest with the unchanged 95% coverage gate. New attribute wrapper: 100%; observe.py: 99%. Existing tests remain byte-for-byte unchanged.
- **Deviations:** None. This review iteration is complete; OME-1165 remains open pending PR approval/merge. No review replies or merge performed.

## Wisdom and confidence review

The custom immutable mapping is necessary because dataclasses.asdict traverses fields without consulting Log's reducer. Its detached deepcopy deliberately becomes a plain dict; Log reconstruction re-wraps attributes for event immutability. No dependency or transport change. Drop counters retain only six fixed keys and saturated integers. Short locked updates make concurrent off-thread rejection count correctly; the lock never encloses user code. Successful submissions avoid diagnostics entirely. Existing silent-logging tests and process-control propagation continue to pass. Both review requirements are covered without changing previous tests or execution outcomes.
