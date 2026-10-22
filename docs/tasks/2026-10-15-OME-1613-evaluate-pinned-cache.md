---
id: OME-1613
linear_url: https://linear.app/openmined/issue/OME-1613/replay-a-published-run-with-evaluatepinned-cache-and-send-author-and
status: in_review
type: feature
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1307
created: 2026-10-15
closed:
---

# Replay a published run with evaluate(pinned_cache=…) and send author and paper metadata

SDK half of the E14 follow-up. `sf.evaluate(pinned_cache=…)` / `score_id=` replays a published
run at $0 and judges it; `limit=n` replays a subset; `authors_metadata` and `paper_metadata` on
submit and edit. Breaking: `frozen_copy_id` renamed to `pinned_cache`, `sf.reproduce` removed.

- 2026-10-21: spec and plan approved; built on branch `OME-1613-evaluate-pinned-cache`; PR opened.
  Spec `docs/spec/2026-10-20-OME-1613-evaluate-pinned-cache.md`, ledger
  `docs/work/2026-10-20-OME-1613-evaluate-pinned-cache.md`.
