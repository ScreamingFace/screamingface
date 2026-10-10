---
id: OME-1533
linear_url: https://linear.app/openmined/issue/OME-1533/a-garbled-judge-reply-on-healthbench-gdpval-text-or-draco-is-retried
status: done
type: bug
priority: none
labels: [bug, screamingface-engine]
created: 2026-10-09
closed: 2026-10-09
---

# A garbled judge reply on healthbench, gdpval-text or draco is retried from the cache, so the retry never fixes it

No parent epic (a `bug` ticket). One PR.

Ledger: `docs/work/2026-10-09-fresh-judge-retry.md`.

- 2026-10-09: fixed for healthbench and gdpval-text — a retry after `judge_reply_invalid` now
  opts out of the AI Gateway cache, so it reaches the Judge. draco needed no change: its verdict
  route records a garbled reply as invalid Evidence and never retries it (pinned by a test). No
  Benchmark revision moved. The first paid run after merge is the owner's check (see the ledger).
