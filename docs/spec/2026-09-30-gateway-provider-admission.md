# OME-1162: gateway-provider-admission

Approved by the owner's request to fix both reviewed races and split PR #1151.
Scope is apps/aigateway; sibling implementation is a separate PR based on main.

Check monotonic admission/caller deadlines after acquiring capacity. Run dispatch in the request task and let the disconnect watcher cancel that task immediately. Preserve classified errors, logging, and slot cleanup.

The wire contract is 503/provider_queue_timeout with Retry-After for admission expiry,
504/provider_execution_timeout for execution expiry, and 504/caller_deadline_exceeded
for an explicit caller cap. Budgets are finite positive internal headers clamped by Gateway.
Existing concurrency limits, SSE behavior, and URL4 retry ownership remain unchanged.
Deploy Gateway first; Engine allows queue + execution + 5 seconds, capped by caller deadline.

## PR #1153 review fixes (2026-10-01)

Approved by the owner's request to fix both of Sergey's review findings. Handle only
disconnect-owned cancellation at the non-streaming HTTP boundary with a safe 499;
consume that cancellation and preserve server shutdown or concurrent cancellation.
Keep immediate watcher cancellation, capacity cleanup and INFO outcome=cancelled logs.
Expose optional `config.providerQueueTimeoutS` in Helm, leaving its default unset.
Document a shorter queue allowance for existing Engine clients so Gateway can return
503 before their 600-second transport timeout. No deployment is part of this change.
