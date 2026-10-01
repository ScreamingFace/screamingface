# OME-1163: engine-provider-admission

Approved by the owner's request to fix both reviewed races and split PR #1151.
Scope is apps/screamingface-engine plus the matching SDK report-code vocabulary;
Gateway implementation is a separate PR based on main.

Preserve the reviewed Engine implementation: declare phase budgets, cap by caller deadline, share the existing two-attempt retry loop, and retain spend uncertainty after transport loss. Base directly on main; merge and deploy Gateway first.

The wire contract is 503/provider_queue_timeout with Retry-After for admission expiry,
504/provider_execution_timeout for execution expiry, and 504/caller_deadline_exceeded
for an explicit caller cap. Budgets are finite positive internal headers clamped by Gateway.
Existing concurrency limits, SSE behavior, and URL4 retry ownership remain unchanged.
Deploy Gateway first; Engine allows queue + execution + 5 seconds, capped by caller deadline.

Review acceptance: preserve connect/write/pool timeouts; recheck full retry allowance
after backoff; reject boolean budgets; retain all three Gateway timeout classifications
and Engine's `aigateway_deadline_exceeded` in Evaluation results and SDK reports.
Release the compatible SDK before or alongside Engine.
