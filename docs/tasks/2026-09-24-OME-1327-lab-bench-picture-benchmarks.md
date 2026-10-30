---
id: OME-1327
linear_url: https://linear.app/openmined/issue/OME-1327/import-the-two-lab-bench-benchmarks-that-need-image-inputs
status: done
type: feature
priority: low
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1330
created: 2026-09-24
closed: 2026-10-26
---

# Import the two LAB-Bench benchmarks that need image inputs

FigQA and TableQA were left out of the six text LAB-Bench Benchmarks (OME-1264) because a Case
could not carry a picture. OME-1271 PR 2 (#1554) saves an eval's pictures inside the Case at
import, so the two are now plain data rows, imported like their six siblings.

- 2026-10-26: imported by Task replay at the siblings' dataset commit and policy seeds (7, 7):
  FigQA 181 Cases (one JPEG each), TableQA 244 Cases (one to three PNGs each), licence
  cc-by-sa-4.0. Tier `medium` for both (the best published models pass 0.83 to 0.89), failure
  policy `withhold` like the siblings. One PR, stacked on #1554, merging after it.
- Owner verify after merge: on the first paid FigQA run, read the run's peak memory against
  the 2,560 MiB per-run budget; loading only the selected Cases (OME-1675) is the fix if it goes
  over.
