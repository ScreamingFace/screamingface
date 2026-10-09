---
ticket: OME-1503
stack: screamingface
status: done
started: 2026-10-09
finished: 2026-10-09
---

# Recovery duplicate claims and complete retained storage

## Intent

The user authorized fixing and pushing both reproduced PR #1269 review findings.
Duplicate saved candidate names must never substitute one run's results for another.
Listing must count retained files even when a member's metadata cannot fully decode.

## Planned changes

- `reports.py`: reject ambiguous candidate-name claims during settlement, preserving
  unaffected candidates; calculate sizes from minimally identified member directories.
- New function-style regressions for sync/async duplicate-name recovery, manifest
  ordering, invalid duplicate metadata, unaffected siblings, and listing storage totals.
- Record the approved correction in a focused spec and plan.

## Test plan

- RED first against pinned head `9f44386e57f89833ca2af339d5168d4428b911d2`.
- Ambiguous slots return `result_metadata_invalid` and never the other run's answer.
- Healthy unrelated slots remain available in the partial report in both APIs.
- Corrupt member directories contribute their full retained bytes to listing.
- Preserve inherited tests; run the full screamingface card gates before pushing.

## Acceptance

Both findings resolved with no public API, schema, dependency, or Engine changes.
Push an ordinary follow-up commit to the existing PR after green gates.

## Outcome

Implemented both corrections in `reports.py` and added fourteen regression cases
in `test_recovery_duplicate_claims.py`, plus the focused spec, plan, and this ledger.
Duplicate claims are rejected before decoding, preserving unrelated healthy members.
Storage accounting scans minimal identities once so corrupt members still contribute.

RED at the pinned PR head: twelve failures and two passes. After implementation,
the focused recovery/storage suite passed all 104 cases; after refining accounting
to a single identity scan, all 61 affected focused cases passed again. The original
probes now reject substitution in both APIs and report all 71,691 retained bytes.

All screamingface card gates passed: append-only tests, Ruff lint and formatting,
Pyright, the full parallel pytest suite with the 95% coverage floor, deterministic
notebooks, build, and distribution validation. Existing tests were unchanged.

Wisdom review: retain canonical membership as the authority, fail closed only for
ambiguous slots, and keep storage measurement independent of rich metadata decoding.
No public API, schema, dependency, or Engine changes were needed. Work used an
isolated checkout of the existing PR branch; no additional ticket or closure was needed.
