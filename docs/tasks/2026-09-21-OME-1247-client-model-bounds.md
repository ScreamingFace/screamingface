---
id: OME-1247
linear_url: https://linear.app/openmined/issue/OME-1247/mirror-the-scoreboards-models-bounds-in-the-client
status: done
type: task
priority: high
labels: [py-screamingface, agentic, autonomous]
created: 2026-09-21
closed: 2026-09-23
---

# Mirror the Scoreboard's models bounds in the Client

The Scoreboard caps `models` at 32 routes, 255 characters each and 4096 bytes serialized. The
Client enforced none of them, so once `OME-1180` began sending the field a candidate exceeding
any cap would turn a previously valid submission into a **422 on the whole submission**.

The board's route *pattern* was deliberately mirrored from the Client's for exactly this reason —
"the two ends must agree on what a route is, or the Client compiles an expression the board then
rejects at submit". The bounds were not. This closed that gap.

Ledger: `docs/work/2026-09-21-OME-1247-client-model-bounds.md`.

**Mirror created late, 2026-09-24.** This unit was filed mid-flight as a bounds follow-up to
`OME-1180` and the mirror was never created at start, so the repo-side record was the ledger
alone. Noted in the ticket's close comment rather than hidden.

- 2026-09-21: filed. Owner decision: fix the defect rather than guard the release button, because
  merging `OME-1180` opens the SDK release PR and merging that publishes to PyPI.
- 2026-09-22: built on `OME-1180`'s branch. Bounds enforced at the submission boundary, not at
  `Pipeline` construction — the caps belong to the leaderboard, so a 40-model local ensemble must
  not be blocked, only publishing it. Gates ALL GREEN at 95%; full suite 1656 passed / 26 skipped.
- 2026-09-23: merged with `OME-1180` as `72a82950` (PR `#923`), approved by HupBaHa with no code
  findings. Closed in Linear with four deviations recorded. **Gate:** Done.
