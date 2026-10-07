---
id: OME-1487
linear_url: https://linear.app/openmined/issue/OME-1487/keep-the-reproduction-cost-unknown-when-a-stored-saving-cannot-be-read
status: done
type: task
priority: low
labels: [scoreboard, agentic, autonomous]
parent: OME-1251
created: 2026-10-05
closed: 2026-10-07
---

# Keep the reproduction cost unknown when a stored saving cannot be read

Non-blocking follow-up from the review of PR #1227 (`OME-1382`). On SQLite a cache saving column
is `VARCHAR(40)`, so raw SQL can store an undecodable value. The raw leaderboard and Pareto reads
degrade it to `None`, which `reproduction_cost` reads as "no saving", so a `complete` row is served
at its bare spend and can take a frontier slot it has not earned.

Change: an undecodable saving makes the served reproduction cost unknown (`None`); a genuinely
absent saving still adds nothing. Regression tests for both saving fields through the ranked table
and the Pareto input.

- 2026-10-07: merged via #1259 (`b885aa22`) after one review round (non-finite amounts); the frontier route and NaN handling were folded in. ORM-loaded reads moved to OME-1517. Closed in Linear with the close comment.
