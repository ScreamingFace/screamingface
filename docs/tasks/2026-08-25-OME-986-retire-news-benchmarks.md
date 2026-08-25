---
id: OME-986
linear_url: https://linear.app/openmined/issue/OME-986/retire-the-legacy-news-demo-benchmarks-from-the-scoreboard-catalogue
status: planned
type: task
priority: P1
labels: [scoreboard, agentic, autonomous, task]
created: 2026-08-25
closed:
---

`hle`, `livetruth` and `livetruth-latest` are leftovers from the previous SF project and still
appear on the public catalogue. Requested by Irina in `#scream-dev` on 2026-08-25, the same
morning the internal testing notebook went out.

Removing them from the chart's seed list is necessary but not sufficient: seeding only registers
and updates, so the rows persist and `GET /v1/benchmarks` keeps serving them. A deletion path has
to exist first.

Spec: `docs/spec/2026-08-25-OME-986-retire-news-benchmarks.md`
Plan: `docs/plan/2026-08-25-OME-986-retire-news-benchmarks.md`
Ledger: `docs/work/2026-08-25-OME-986-retire-news-benchmarks.md`
