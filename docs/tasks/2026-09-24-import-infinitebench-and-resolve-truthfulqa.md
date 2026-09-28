---
id: OME-1328
linear_url: https://linear.app/openmined/issue/OME-1328/import-the-infinitebench-benchmarks-and-resolve-the-truthfulqa-import
status: backlog
type: feature
priority: P2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-24
closed:
---

# Import the InfiniteBench benchmarks and resolve the truthfulqa import

Remaining scope split out of OME-1264 at close: run the 9-board InfiniteBench
batch (machinery merged in PR #1033; two real TODO(review) render deviations
per board — function-built system message, run-time input truncation; GB-scale
bake downloads and very large baked cases to weigh), decide truthfulqa
(task-local record_to_sample + list target: hand-import, upstream fix, or
named exclusion), and settle two small carried review items (upstream-row-seed
reproduction claim; pins-import sort vs isort ordering).
