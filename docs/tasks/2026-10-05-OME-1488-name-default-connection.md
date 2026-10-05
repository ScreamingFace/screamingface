---
id: OME-1488
linear_url: https://linear.app/openmined/issue/OME-1488/leaderboard-submissions-and-operator-commands-fail-since-the-readiness
status: in_review
type: bug
priority: urgent
labels: [bug, scoreboard, agentic, autonomous]
created: 2026-10-05
closed:
---

# Leaderboard, submissions and operator commands fail since the readiness connection was added

#1213 gave the web app a second Tortoise connection (`readiness`); Tortoise then refuses every
unnamed `in_transaction()`, so on dev every leaderboard and frontier read returned 500 and
submissions failed. Fixed by naming `DEFAULT_CONNECTION` at all 8 transactions, with tests that start
Tortoise exactly as the web app does and an AST guard against new unnamed calls.

Ledger: `docs/work/2026-10-05-OME-1488-name-default-connection.md`.
Spec: `docs/spec/2026-10-05-OME-1488-name-default-connection.md`.

- 2026-10-05: found from the dev pod log after #1227's deploy; fixed the same day.
