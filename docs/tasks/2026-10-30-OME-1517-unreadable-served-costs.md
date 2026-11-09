---
id: OME-1517
linear_url: https://linear.app/openmined/issue/OME-1517
status: done
type: bug
priority: 4
labels: [scoreboard, agentic, autonomous, bug]
created: 2026-10-07
closed: 2026-11-05
---

# Serve unknown costs for unreadable stored amounts

Keep my_submissions and spec history available when any stored money field is
malformed/non-finite, using the ranked leaderboard's existing degradation policy.
Preserve owner filters, history limits, valid sums, receipts and private export.

Ledger: `docs/work/2026-10-30-unreadable-served-costs.md`.

Merged [PR #1626](https://github.com/ScreamingFace/screamingface/pull/1626)
on 2026-11-05, commit `b972231dafc92f975bd43445bdd50f5015bdabe2`. Linear is Done.
