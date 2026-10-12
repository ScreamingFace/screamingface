---
id: OME-1576
linear_url: https://linear.app/openmined/issue/OME-1576/studio-sidecar-lock-misses-ijson-so-a-frozen-build-ships-without-it
status: done
type: bug
priority: none
labels: [bug, desktop]
created: 2026-10-12
closed: 2026-10-12
---

# Studio sidecar lock misses ijson, so a frozen build ships without it

No parent epic (a `bug` ticket). One PR.

Ledger: `docs/work/2026-10-12-studio-runtime-lock.md`.

- 2026-10-12: fixed — `apps/screamingface-studio/runtime/uv.lock` re-locked so it carries
  `ijson`, which `packages/screamingface` requires since `e7833e35c`. No other package version
  moves. A `build-sidecar.sh` build now bundles `ijson` (see the ledger).
