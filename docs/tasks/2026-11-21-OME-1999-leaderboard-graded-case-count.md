---
id: OME-1999
linear_url: https://linear.app/openmined/issue/OME-1999/show-on-the-leaderboard-how-many-cases-each-run-failed-to-grade
status: Done
type: task
priority: medium
labels: [scoreboard, agentic, autonomous, user-request]
parent: OME-1286
created: 2026-11-21
closed: 2026-11-21
---

# Show on the leaderboard how many Cases each run failed to grade

A run can fail to grade some of its Cases (the Candidate call errors or times out, or the judge
gives no readable verdict). The SDK told the submitter, but the leaderboard received only the
selected-Case total, so such a run looked complete to every reader. An external researcher asked
for failures to be shown next to the score.

A partly graded run now submits `graded_questions`. The scoreboard checks it (a whole number from
0 to `total_questions`), stores it in a nullable column (migration `0026`), serves it on the
ranked leaderboard, and the page prints "505 / 525 graded" under the score. An entry with no
count, from an older SDK or an older row, shows and exports exactly what it did before. Ranking,
scores, revisions and the Engine are unchanged.

Not covered: the submission-history page and a participant's own rows on a private Benchmark.

Pending owner steps (in the ledger's owner-verify note): deploy the scoreboard before the SDK
release, and renumber against the other open `0026` migration.

Ledger: `docs/work/2026-11-21-leaderboard-graded-case-count.md`.
Branch: `OME-1999-leaderboard-graded-case-count`.
