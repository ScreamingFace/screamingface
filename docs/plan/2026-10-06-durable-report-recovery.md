# Implementation plan

1. Import the existing recovery regression tests as new tests and confirm failure on main.
2. Extract store/codec/membership, streamed downloads, disk indexing/integrity, explicit saved-report API, and nullable member totals from pinned #1156.
3. Integrate membership and per-candidate decode settlement while removing accounting caches, lifecycle markers/notices, and all notebook hooks. Preserve current main changes and existing tests.
4. Reuse #1241 atomic helper exactly. Validate the current-main draft and simulated post-#1241 merge without reverting its export implementation.
5. Run focused regressions, the full SDK gate runner, and independent Standards/Spec review. Record evidence, create the focused ticket under OME-1294 linked to OME-1448, and open the requested draft.
