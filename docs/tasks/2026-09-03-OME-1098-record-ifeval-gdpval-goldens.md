---
id: OME-1098
linear_url: https://linear.app/openmined/issue/OME-1098/record-ifeval-and-gdpval-text-goldens-so-the-deterministic-and-gdpval
status: done
type: feature
priority: 2
labels: [py-screamingface, human, deferred]
created: 2026-09-03
closed: 2026-09-10
---

# Record ifeval and gdpval-text goldens so the deterministic and gdpval folds are e2e-guarded

Only draco-3pass and healthbench-worst30 have e2e goldens. ifeval (the sole
deterministic-grading board) and gdpval-text (touched by the first extraction PRs) have
none, so folding them onto the shared spine (OME-1101 / OME-1097) would be guarded by
unit tests alone — a shifted leaderboard number would pass CI.

Scope widened 2026-09-09 (owner-approved): the ifeval golden pins a **CorrectiveLoop**
candidate (V1 recipe) instead of a solo model. The PR therefore also carries a
fresh-dump bless mode (no re-key, candidate-shape-agnostic) and a third golden kind
`corrective_loop`.

Split: dev half (harness prep + later bless) is agent-run; the paid recordings are
owner-run — CorrectiveLoop on ifeval `limit=50` (report + pg_dump) and a Fusion on
gdpval-text `limit=25` (report only), through a Postgres-backed local stack with the
request cache ON.

Full spec: the Linear issue. Ledger:
`docs/work/2026-09-09-OME-1098-goldens-harness-prep.md`.
