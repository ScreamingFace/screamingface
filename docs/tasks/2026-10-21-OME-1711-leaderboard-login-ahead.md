---
id: OME-1711
linear_url: https://linear.app/openmined/issue/OME-1711/let-the-sdk-log-in-to-the-leaderboard-before-a-submit
status: backlog
type: feature
priority: medium
labels: [client-sf, agentic, autonomous]
parent: none
created: 2026-10-21
closed:
---

# Let the SDK log in to the leaderboard before a submit

Follow-up to `OME-1649` (its RC-2). `Client.login()` logs in to the Engine only, and the scoreboard
auth discovers Access at the public host root, so a leaderboard login before a submit raises
`access_not_advertised`. Discover on `/v1/scores` and offer a public leaderboard login.
