---
id: OME-2015
linear_url: https://linear.app/openmined/issue/OME-2015/let-authors-link-a-personal-website-so-their-name-is-clickable-on-the
status: in_review
type: feature
priority: medium
labels: [scoreboard, agentic, autonomous]
parent: OME-1915
created: 2026-11-26
closed:
---

# Let authors link a personal website so their name is clickable on the leaderboard

`website` is a new known URL key in `authors_metadata` (validated exactly like `paper_url`/`url`:
http/https only, no user-info, 2048-char cap) and is now published — key-masked the same way
`ScoreSchema.authors_metadata` already is — on `LeaderboardEntry`, `SpecHistoryRow`,
`RankedLeaderboardEntry` and `HistorySubmission`. The portal's `formatAuthors()` renders each
author's name as an `<a href>` to their website (labelled with `full_name` when given) and falls
back to plain text otherwise, on the leaderboard table and the spec history table.

Scoreboard-only scope; the client-sf ergonomic half is the independent `OME-2041`.

Four pre-existing tests needed owner-approved edits for this field/signature change (two
call-site substring checks and two exhaustive-field guards), pinned at
`.claude/test-change-approvals/OME-2015.json`.

Ledger: `docs/work/2026-11-26-OME-2015-author-website.md`.
Branch: `OME-2015-author-website`.
