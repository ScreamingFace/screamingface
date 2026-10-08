---
id: OME-1469
linear_url: https://linear.app/openmined/issue/OME-1469/approve-the-draco-3pass-rerun-spend-that-prices-its-unpriced-cache
status: done
type: decision
priority: urgent
labels: [scoreboard, human, design-session, decision]
parent: OME-1251
created: 2026-10-02
closed: 2026-10-06
---

# Approve the draco-3pass rerun spend that prices its unpriced cache hits

Under D7 on `OME-1251` a cached run publishes its full cost only when every cache hit is priced.
The 7 dev `draco-3pass` rows (`OME-1384`) hit 1,550 unpriced cache entries and 136 missing ones.
A local replay of all 7 recipes at dev's commit gave the exact cache keys and the cost of two
options: B, re-measure only the unpriced calls (estimate $215), or A, regenerate them ($1,229).

- 2026-10-02: filed with the cost table and the replay harness attached.
- 2026-10-05: Irina approved option B with a $300 limit on the team OpenRouter key.
- 2026-10-05: 1,550 entries re-measured with the cache bypassed and loaded on dev as
  `archive_matched` through the admin cache upload (two loads, verified row by row). One fable
  answer is now refused by the provider (`content_filter`); the owner chose to price it at the
  mean of 99 measured fable answers. The cached reruns then paid for the 136 missing calls and
  the judge verdicts they triggered. All 7 rows republished `complete` with their full cost.
  Total spend on the key: $135.09.
