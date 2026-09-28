# OME-1053 — Client authorship implementation plan

1. Add failing tests for the three public submission entry points, omission semantics, exact-list
   preservation, local validation boundaries, response decoding, and immutable returned values.
2. Thread the keyword-only `authors` parameter through lazy, sync, and async submission methods
   into the one shared payload builder.
3. Validate author arguments once beside the payload builder and conditionally add the JSON field.
4. Add optional immutable `authors` fields to `LeaderboardScore` and `LeaderboardEntry`, then
   decode non-null Scoreboard arrays into tuples.
5. Refresh the public API snapshot, run focused and full tests, then run the complete
   `screamingface` gate set.
6. Complete the ledger, commit with `Refs: OME-1053`, push, and open a draft PR that names the
   unmerged/deployment dependency on the Scoreboard implementation.
