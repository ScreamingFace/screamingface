---
id: OME-1655
linear_url: https://linear.app/openmined/issue/OME-1655/turn-on-the-reproduce-button-on-the-leaderboard
status: in_review
type: task
priority: medium
labels: [scoreboard, agentic, autonomous]
parent: OME-1307
created: 2026-10-19
closed:
---

# Turn on the Reproduce button on the leaderboard

`OME-1596` shipped the Reproduce button in the board's Run column behind `SHOW_REPRODUCE_BUTTON`
in `apps/scoreboard/portal/benchmark.js`, off. This ticket turns it on.

The release gate is satisfied: SDK **0.1.7** is on PyPI and contains `OME-1613` replay support
and the `OME-1649` login fix. [PR #1522](https://github.com/ScreamingFace/screamingface/pull/1522)
is ready for review, no longer a draft. Independent review of `360a81a` found no actionable
defects; all 148 portal tests passed and the reviewed head's GitHub CI was green.

Still pending: merge and deploy the scoreboard change, run the copied snippet from a production
captured public row with the released SDK, and confirm its replay verdict. Also verify the
`OME-1614` public-docs replay examples and update their sidebar source baseline to the verified
SDK release. The live checks have not been performed; this issue remains open.

- 2026-10-19: filed by the owner, split out of `OME-1596`'s acceptance.
- 2026-10-21: built; draft PR held until the SDK release with `OME-1613` is on PyPI.
- 2026-10-23: release gate satisfied by SDK 0.1.7; independent review clean; ready for review.
