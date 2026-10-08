# Implementation plan

1. Import the existing recovery regression tests as new tests and confirm failure on main.
2. Extract store/codec/membership, streamed downloads, disk indexing/integrity, explicit saved-report API, and nullable member totals from pinned #1156.
3. Integrate membership and per-candidate decode settlement while removing accounting caches, lifecycle markers/notices, and all notebook hooks. Preserve current main changes and existing tests.
4. Reuse #1241 atomic helper exactly. Validate the current-main draft and simulated post-#1241 merge without reverting its export implementation.
5. Run focused regressions, the full SDK gate runner, and independent Standards/Spec review. Record evidence, create the focused ticket under OME-1294 linked to OME-1448, and open the requested draft.

Review follow-up: add failing corrupt-first regressions; resolve canonical context
before grouping, retaining a locally validated legacy fallback; rerun SDK gates
and execute the requested temporary report feature notebook.
# Listing and deletion review correction (2026-10-08)

Share the canonical metadata loader between recovery and lightweight listing.
Union expected legacy membership and locally known names without result decoding.
Delete saved runs by evaluation identity independently of candidate name lists.
Add corruption, completeness, error, saved-key lookup, and unrelated-group tests;
preserve every inherited test and run all SDK gates before committing.

## Corrupt metadata review fixes (2026-10-08)

Add RED regressions for malformed saved costs and full membership validation
failures. Normalize decimal parse errors; settle each identifiable sibling
manifest independently. Reuse minimal identity enumeration for complete deletion,
including saved-key lookup and groups whose members all fail full validation.
Rebase on current main, refresh the precise API snapshot transition, run all SDK
gates and independently recheck the demonstrated failures.

## All-corrupt discovery correction (2026-10-08)

Reuse minimal identity enumeration and independent canonical metadata when full
candidate decoding yields no saved runs. Add failing listing and sync/async
settlement regressions, preserve inherited behavior, and run all SDK gates.
