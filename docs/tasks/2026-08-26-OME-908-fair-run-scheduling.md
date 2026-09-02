---
id: OME-908
linear_url: https://linear.app/openmined/issue/OME-908/fair-schedule-concurrent-engine-runs-so-one-large-benchmark-run-doesnt
status: backlog
type: null
priority: 2
labels: [screamingface-engine, human, design-session]
created: 2026-08-26
closed: null
---

# Fair-schedule concurrent Engine runs so one large benchmark run doesn't starve others

One full DRACO run (~20k judge calls, all on one `openrouter` provider key, up to 32 in
flight) fills the gateway's 4-slot per-provider FIFO queue for its whole duration. A second
concurrent run then makes little or no progress until the first drains: the queue has no
run identity, so FIFO serves the monopolizer's continuously arriving calls first, and the
second run's transient retries re-join the back of the queue.

Analysis (verified in code) and the proposed layered fix live in
`docs/spec/2026-08-26-OME-908-fair-run-scheduling.md`; staged implementation steps live in
`docs/plan/2026-08-26-OME-908-fair-run-scheduling.md`. Summary of the recommendation:

1. Layer 0 — measure first: engine per-run dispatch counters plus an ops checklist, to
   confirm the gateway queue (not k8s Job co-scheduling) is the locus.
2. Layer 1 — engine-side fair budgets: a per-run `URL4_CLOUD_IO_CONCURRENCY` budget for
   deployed Jobs (static, default 4) and a shared work-conserving fewest-in-flight gate for
   local in-process runs (default capacity 32). Solo runs keep today's full speed.
3. Layer 2 — companion ticket on the gateway: fair (identity-keyed) provider semaphore plus
   slot-wait telemetry. The gateway already receives the identity header, so no contract
   change is needed.
4. Layer 3 — ops notes: `timeout_s` guidance, the existing openrouter concurrency override,
   and runner co-scheduling requirements.

The owner approved the spec in session on 2026-08-26; the D0–D5 resolutions are recorded in
the spec. Implementation (Layer 1 + the Layer 3 docs) is PR #750: a static per-run budget on
every Runner Job (`URL4_CLOUD_IO_CONCURRENCY`, default 4 — written unconditionally, like
`EXTRA_MODELS`, so a stale ConfigMap copy can never reach a Job) and a shared
work-conserving fewest-in-flight gate for local runs (`local_io_capacity`, default 32).
Layer 2 remains the companion gateway ticket — text drafted in the work ledger, filing
pending the owner (Linear writes are owner/MCP actions).
