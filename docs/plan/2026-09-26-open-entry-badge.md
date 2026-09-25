# open-entry-badge — plan

Spec: `docs/spec/2026-09-26-open-entry-badge.md`. Branch `open-entry-badge` from
`OME-1145-frontier-openness` at `de0fcc2a` (stacked on #1080).

1. **RED.** `tests/unit/test_entry_openness_route.py`: verdicts on ranked rows, agreement with the
   card, page-bounded read, private flip during the read. Append `opennessLabel` tests to
   `tests/portal/leaderboard-logic.test.js`. Confirm each fails for the stated reason.
2. **GREEN.** `openness` on `RankedLeaderboardEntry`; in `get_leaderboard`, one
   `frontier_member_models` call over the page's `source_id`s before `turned_private`, then
   `classify_entry` per row in `_ranked_entry`. `opennessLabel` in `leaderboard-logic.js`, a
   Weights cell in `benchmark.js`, its `<th>` in `benchmark.html`, `.status--open` in `portal.css`.
3. **Prior test (approved list).** `_PUBLIC_BOARD_ENTRY_FIELDS` gains `"openness"`, with the same
   recorded-exception comment the OME-1051 and OME-923 additions carry. Anything else: STOP.
4. **Gates** with `--skip-append-only` after one run without it proves only that file is flagged.
5. **Mutations:** drop the override branch; read models for the whole board instead of the page;
   move the read after `turned_private`. Then the ticket under `OME-1282`, rename the branch, PR
   against `OME-1145-frontier-openness`.

Both light and dark themes get checked in the page before the PR (SFDS self-check).
