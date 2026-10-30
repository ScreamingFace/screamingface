# Featured benchmark search implementation — OME-1761

Spec: `docs/spec/2026-10-30-featured-benchmark-search-spec.md`.

1. Add a standalone Node DOM regression using the actual main.js and leaderboard logic.
   Confirm featured-query cases fail on the current implementation.
2. Pass listed boards alongside overflow boards to buildMoreMenu. Select the listed
   catalog only when the trimmed query is nonempty; retain the existing filter helper.
3. Register the new test explicitly in both local and CI gates. Run scoreboard gates,
   inspect the diff, and verify the picker in a browser where available.
4. Update the ledger and task mirror, commit, and open a review PR linked to OME-1761.

This keeps visibility filtering in one place and changes only the picker's search pool.
