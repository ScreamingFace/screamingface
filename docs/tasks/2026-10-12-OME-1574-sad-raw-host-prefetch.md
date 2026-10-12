---
id: OME-1574
linear_url: https://linear.app/openmined/issue/OME-1574/benchmark-image-builds-fail-when-github-refuses-the-sad-dataset
status: done
type: bug
priority: none
labels: [bug, screamingface-engine]
created: 2026-10-12
closed: 2026-10-12
---

# Benchmark image builds fail when GitHub refuses the SAD dataset

No parent epic (a `bug` ticket). One PR.

Ledger: `docs/work/2026-10-12-sad-raw-host-prefetch.md`.

- 2026-10-12: fixed — a SAD replay now fills its empty cache with the five SAD zips from
  GitHub's raw host before the task function runs, verified against upstream's pinned
  checksums, so SAD's loader never calls the rate-limited contents API. No Benchmark revision
  moved. The next benchmark image build is the owner's check (see the ledger).
