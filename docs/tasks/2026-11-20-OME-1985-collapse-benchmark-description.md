---
id: OME-1985
linear_url: https://linear.app/openmined/issue/OME-1985/improve-benchmark-description-rendering-and-make-it-collapsible
status: done
type: feat
priority: medium
labels: [scoreboard, agentic, autonomous]
parent: OME-1915
created: 2026-11-20
closed: 2026-11-20
---

# Improve benchmark description rendering and make it collapsible

A benchmark page printed its whole description as one plain paragraph at lead size; the median
description is 723 characters and the longest 2,515. The page now folds a description taller than
three lines behind a "Show more / Show less" button and sets it at body size. A description that
fits shows no button, and a page whose scripts did not run shows the whole text. Rendering only:
no description copy changes.

- 2026-11-20: issue filed from Slack under epic `OME-1915`; picked up the same day. Owner action
  left: merge; the page changes on the next Scoreboard deploy.
- Ledger: `docs/work/2026-11-20-collapse-benchmark-description.md`
