---
id: OME-1421
linear_url: https://linear.app/openmined/issue/OME-1421/keep-the-sdk-on-the-same-inspect-version-as-the-engine
status: done
type: fix
priority: medium
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-1299
created: 2026-09-30
closed: 2026-09-30
---

# Keep the SDK on the same inspect version as the Engine

The SDK's `inspect` extra must pin the same `inspect-ai` as the Engine, which hashes it into
every Imported Benchmark's Benchmark Revision. OME-1411 held inspect-ai in Dependabot for the
Engine only, so #1119 and #1135 moved the SDK alone to 0.3.270. The Engine's pin is now the
single source of truth: the SDK is back on 0.3.263, Dependabot holds inspect-ai in both
directories (registered in `dependabot-ignores.yml`), a conformance test twinned in both
packages fails on drift, and the review agent's Lane 6 carries the pattern.

- 2026-09-30: filed with its PR (branch `OME-1421-sdk-inspect-pin-follows-engine`, ledger
  `docs/work/2026-09-30-sdk-inspect-pin-follows-engine.md`).
