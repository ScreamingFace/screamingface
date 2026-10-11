---
ticket: OME-1503
stack: screamingface
status: done
started: 2026-10-08
finished: 2026-10-08
---

# Recover evaluations whose candidate manifests all fail decoding

## Intent

Fix the reproduced PR #1269 finding: a known saved evaluation must remain discoverable and return named candidate failures when every candidate manifest is corrupt. The user authorized this correction on 2026-10-08.

## Planned changes

- `_results/store.py`: reuse minimal identity enumeration for discovery.
- `_results/discovery.py`: independent evaluation metadata and unreadable-group discovery/settlement.
- `reports.py`: integrate fallback discovery and selection without changing healthy recovery.
- `tests/test_all_corrupt_recovery.py`: append regressions; preserve all inherited tests.
- Existing durable recovery spec/plan: record the correction.

## Test plan

RED first for canonical/legacy all-corrupt groups, sync/async named failures, one-candidate groups, unrelated healthy groups, canonical invalid/unreadable metadata, missing reports, and listing without raw result decoding. Preserve direct corrupt saved-key behavior and deletion.

## Acceptance

Listing retains known evaluation names; both recovery APIs raise candidates_failed with named result_metadata_invalid failures and no partial Report when none succeeds. No model calls, public API/schema/dependency changes, or weakened tests. Full SDK gates pass.

## Outcome

- **Actual files:** the planned store/discovery/report modules, one new regression test file, and the existing spec/plan plus this ledger.
- **Commit message:** `fix(screamingface): preserve all-corrupt report discovery`.
- **RED:** 14 new checks failed against the reviewed head (one existing-behavior boundary passed). Two additional legacy expected-name regressions failed before their correction.
- **GREEN:** all 19 new regressions pass; 120 focused recovery/identity/public-surface checks passed before the final discovery enumeration optimization, followed by all 19 regressions plus Ruff, formatting, and Pyright on the final source.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface --base e2b6654b9987263b695362aaa2d36fb059f4df67` returned ALL GATES GREEN: append-only tests, Ruff lint/format, Pyright, full parallel pytest with the 95% floor, deterministic notebooks, wheel/sdist builds, and distribution checks. Coverage: 95.89%. Mirror status and whitespace checks passed.
- **Wisdom/review:** canonical metadata remains authoritative; legacy discovery unions valid embedded expected names with known local names. Candidate manifest errors settle through the existing error shape. Shared canonical validation and failure construction avoid divergent sync/async paths. Metadata cannot supply filesystem paths; invalid identities are rejected before canonical reads. No authentication or result fetching occurs when every identifiable candidate fails metadata decoding. Healthy recovery, direct corrupt saved-key errors, explicit deletion, and the public snapshot remain protected by inherited tests.
- **Scope:** a known group requires identifiable local completion records; this fix does not make a preparation-only manifest count as a completed run. No paid calls, new public API/schema/dependency, rewritten inherited tests, GitHub comments, or merge.
- **Deviations:** used an isolated worktree of the existing review clone. The listing-enumeration optimization was checked with the focused regressions and static gates while the full runner was in progress; it does not change discovery results. OME-1503 remains open for PR review/merge.
