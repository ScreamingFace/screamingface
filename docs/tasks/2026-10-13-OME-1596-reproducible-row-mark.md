---
id: OME-1596
linear_url: https://linear.app/openmined/issue/OME-1596/add-author-and-paper-metadata-and-a-reproduce-button-to-the
status: in_progress
type: task
priority: medium
labels: [scoreboard, agentic, autonomous]
parent: OME-1307
created: 2026-10-13
closed:
---

# Add author and paper metadata and a Reproduce button to the leaderboard

Scoreboard half of the E14 follow-up: `authors_metadata` and `paper_metadata` on submissions, a
public pinned-cache lookup for `sf.evaluate(pinned_cache=…)`, a Reproduce button behind a switch, and
no displayed reproduction count. SDK: `OME-1613`. Docs: `OME-1614`.

- 2026-10-13: filed as a row mark ("reproducible / reproduced N×"), started.
- 2026-10-14: rescoped after Irina's review; the row mark is dropped.
- 2026-10-15: spec approved piece by piece (`docs/spec/2026-10-13-OME-1596-reproducible-row-mark.md`).
- 2026-10-16: rebased onto `main`; draft PR #1440 opened.
- 2026-10-19: review round 1 fixed (unstorable metadata text refused with a 422, Reproduce button
  accessible name, OpenAPI descriptions, test and doc follow-ups).
- 2026-10-19: owner resolved the resubmit-null contract raised in Dmitry's PR #1440 review:
  null/omission preserve metadata on same-owner resubmit; PATCH null clears and omission preserves.
  Spec §2/§7 and the plan now state the distinction explicitly; implementation unchanged.
