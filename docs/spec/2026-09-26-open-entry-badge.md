# Mark each leaderboard entry open or closed

Under Irina's Urgent epic `OME-1282`: the board must show **which entries** win the cost/score
Pareto frontier and which win the open frontier. After `OME-1145` (PR #1080) the card says
"N% open" but no row says which. Stacked on #1080; ledger
`docs/work/2026-09-26-open-entry-badge.md`.

## §1 Decisions (owner, 2026-09-26)

| # | Decision |
| -- | -- |
| B1 | **Reading (a).** Each entry carries an open/closed verdict. An "open frontier win" is a row with both the Pareto mark and the open verdict. No second, open-only frontier. |
| B2 | **Publish the verdict, not the models.** `openness` joins the public ranked entry; `models` stays internal (OME-1181 Q2 stands). |
| B3 | **Every ranked row** carries it, not only frontier rows. |
| B4 | **Stacked on #1080**, rebased onto `main` once it merges. |

## §2 The field

`RankedLeaderboardEntry.openness: Literal["open", "closed", "unidentified"]`, computed by the same
`classify_entry` the card uses (D1 any-closed-wins, D4 unknown closes, D-Q4 override wins). So a
row's badge and the card's count can never disagree.

Read with `frontier_member_models` over the **page's** ids only (at most 200), the same bounded
`id, models, openness_override` read, before the `turned_private` re-check (OME-894). Private
boards' `my_submissions` are out of scope: they are not ranked.

## §3 The portal: a line in the Backends cell

**Revised 2026-09-26 during build (owner decision).** A separate "Weights" column pushed the
table from 958px to 978px in a 958px container, putting "Run locally", the board's primary
action, behind a horizontal scroll (the regression the Questions column was dropped to avoid).
The verdict rides as a second line in the Backends cell instead, where a reader looks for what
an entry runs on. The table measured 958px after the move, in light and dark.

SFDS `.status` recipe (square + sentence-case word), kept on one line:

| verdict | renders | tone |
| -- | -- | -- |
| `open` | ■ Open weights | full ink, neutral square |
| `closed` | ■ Closed weights | whisper (the recipe's off-state) |
| `unidentified` | — | faint, `title` and screen-reader text "Models not declared…" |

**No green.** In SFDS green marks *verified / reproduced* (`.status.on` is success-green). Open
weights means *you* can run it, not that *we* verified it (`OME-1146`, `OME-1319`). Two CSS rules,
tokens only: `.weights-line` (block, nowrap) and `.status.status--open` (full-tone ink).

The decision of what to show lives in `leaderboard-logic.js` (`opennessLabel`), tested in Node;
`benchmark.js` only paints it.

## §4 Tests

- route: each ranked row carries `openness`; open/closed/unidentified all appear correctly
- route: the verdict matches the card's classification for the same rows
- route: the models read is page-bounded, and a flip to private during it withholds the board
- portal: `opennessLabel` for all three verdicts, and unknown input
- **prior test (needs sign-off):** `_PUBLIC_BOARD_ENTRY_FIELDS` in `test_leaderboard_routes.py`
  gains `"openness"`, an additive change to an exact-set guard, as `OME-1051` and `OME-923` did

## §5 Out of scope

- an open-only frontier (B1 reading b)
- publishing `models` or model names
- the chart's point colours by openness (a later chart ticket)
