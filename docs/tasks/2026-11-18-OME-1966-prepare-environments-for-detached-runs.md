---
id: OME-1966
linear_url: https://linear.app/openmined/issue/OME-1966/prepare-each-environment-for-detached-runs-e5-p2
status: todo
type: task
priority: high
labels: [screamingface-engine, human, design-session, task]
parent: OME-1837
created: 2026-11-18
closed:
---

# Prepare each environment for detached Runs (E5 P2)

Detached Runs need some setup in each environment where Runs are on. None of it blocks merging
#1759 or #1878.

**When the Engine PR deploys**

- The broker's JetStream file store holds the outcome stream's 512 MiB beside `events.maxBytes`
  (staging and prod).

**Before the new Client is released**

- Staging and prod: decide what backs the run-results store in prod (Azure Blob needs its own
  adapter); create the bucket with a 31-day lifecycle rule and a write-only key for the runner
  pool. In prod, `runnerPool.drainGraceS` (with its termination grace) covers the 16 h job
  deadline.
- Every environment with Runs on: the App and the runner pool reach the store (NetworkPolicy);
  the email key stays the same across renders (`database.emailKey.existingSecret` and
  `runResults.storage.s3.existingSecret` where the chart renders without `lookup`); the database
  pool is sized (`?maxsize=` on the URL); the edge passes `X-User-Email` on the WebSocket upgrade
  to `/runs/{id}/events`.

Spec: `docs/spec/2026-11-04-e5-p2-detached-run.md` §8, §9.

- 2026-11-18: filed as an owner action under `OME-1837`.
- 2026-11-18: the email key and database pool items added, from a review of #1759.
- 2026-11-18: retitled from "Provide a durable run-results bucket in prod for detached Runs" and
  rewritten to cover every environment, with the rest of spec §9's environment actions.
- 2026-11-18: "roll the runner pool before the App" dropped: the new Client is released only once
  the Engine is deployed everywhere, and only its Runs send the messages an older pool refuses.
