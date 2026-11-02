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
merged on 2026-10-26 as `f70cde71b207f14543d41b9fb160b4bc21d54d90`, after approval and
passing CI. The review fixes keep the Run column reachable on narrow screens and name the
replay-capable Engine/Gateway prerequisite without an unconditional cost promise.

Dev acceptance passed on 2026-10-26: the live button copied the correct snippet on desktop
and mobile; a real complete dev capture replayed exactly for 100 DRACO cases at 0.3593,
with $0 new provider spend and a successfully recorded reproduction. Dev metadata editing
also passed. Owner edit-history retrieval is tracked separately as the nonblocking general
bug OME-1736; this does not claim that retrieval passed.

The 2026-10-27 production firecall check still found Scoreboard `c33df414f` and the Reproduce
flag off. Service readiness, required E14 columns and an existing sealed capture passed
read-only checks. Production copied-button acceptance remains outstanding.

Still pending: production deployment and captured/uncaptured-row checks, then execute the
copied snippet with the released SDK and confirm its exact verdict and recording. The
`OME-1614` public-docs release verification and sidebar update are locally complete in
`docs/work/2026-10-27-e14-docs-release-verification.md`: SDK 0.1.7 pinned-cache and score-ID
replays both returned exact for 100 cases at 0.3593; the one-case partial replay had no
verdict. All cost $0, with recording disabled. Docs build/lint/browser checks passed;
publication remains separate.
This issue remains In Review in Linear. No Linear changes were made by this docs follow-up.

- 2026-10-19: filed by the owner, split out of `OME-1596`'s acceptance.
- 2026-10-21: built; draft PR held until the SDK release with `OME-1613` is on PyPI.
- 2026-10-23: release gate satisfied by SDK 0.1.7; independent review clean; ready for review.
- 2026-10-23: fixed both subsequent review findings; awaiting CI and reviewer recheck.
- 2026-10-26: PR merged; real dev capture, copied-button replay and recording accepted.
- 2026-10-27: production inspected read-only; enabled-button deployment still pending.
