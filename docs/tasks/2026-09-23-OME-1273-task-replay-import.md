---
id: OME-1273
linear_url: https://linear.app/openmined/issue/OME-1273/import-the-single-turn-benchmarks-the-importer-still-refuses
status: in_progress
type: feature
priority: medium
labels: [screamingface-engine, human]
parent: OME-1299
created: 2026-09-23
closed:
---

# Import the single-turn benchmarks the importer still refuses

The importer refuses 34 inspect_evals packages because it can't see where their Cases come
from. The fix runs the eval's own task to fetch the Cases, records every Case Source,
fingerprints the result as a Case Digest, and re-checks that digest at every Case Preparation.
Up to 14 packages become Imported Benchmarks here; the Judge-graded rest become fetchable for
the Judge tickets. Design: `docs/spec/2026-09-30-OME-1273-task-replay-import.md`. Delivered as a
stack of PRs (renumbered 2026-10-01 in the spec's Delivery: R8 dropped, the 11 split in two);
this mirror closes with the last one. Amended 2026-10-02: Task-replay Cases are captured from
the eval's own solvers (`docs/plan/2026-10-02-OME-1273-capture-rendering.md`, ledger
`docs/work/2026-10-02-ome-1273-capture-rendering.md`).

## Progress

- Spec merged (#1147); image side merged (#1150).
- Import side: the importer imports an eval by Task replay (recorder, double run, generated
  declaration, license gate, `--task-replay`). Plan:
  `docs/plan/2026-10-01-OME-1273-task-replay-import-side.md`.
- First ten Benchmarks (agieval ×8, medqa, mgsm_en) by capture: ledger
  `docs/work/2026-10-02-ome-1273-task-replay-benchmarks-1.md`.
