# Provider admission and execution budgets

OME-886 / OME-1162 / OME-1163: non-streaming model calls wait for provider capacity
separately from executing upstream. A queued call does not consume its execution
allowance. The slot remains held across upstream overload retries and their backoff;
all of that time consumes the execution allowance.

Gateway admission (OME-1162) and Engine integration (OME-1163) ship in separate
PRs, each based on `main`. Merge and deploy Gateway first. The Engine sections
below describe the shared wire contract implemented by that follow-up.

## Configuration and wire contract

- `AIGW_PROVIDER_EXECUTION_TIMEOUT_S`: finite positive seconds, default 600.
- `AIGW_PROVIDER_QUEUE_TIMEOUT_S`: optional finite positive seconds. When absent,
  admission uses the effective execution allowance.
- Engine `[aigateway].timeout_s` declares execution seconds. Its new optional
  `queue_timeout_s` declares admission seconds and defaults to `timeout_s`.
- Engine sends `x-aigw-execution-timeout-s` and `x-aigw-queue-timeout-s`. Gateway
  clamps these to its operator limits. They are HTTP headers, never provider
  parameters, and do not alter response cache keys.
- For an explicit caller deadline Engine also sends `x-aigw-remaining-timeout-s`,
  recomputed for each transport attempt. Gateway caps both phases together to
  that allowance. Engine's own wall-clock deadline remains authoritative.
- Engine allows admission + execution + 5 seconds for the HTTP round trip, capped
  by the caller deadline. The small margin lets Gateway return a classified error.

For example, execution 600s with admission unset allows up to 600s waiting and then
600s executing; Engine's transport allowance is 1205s unless the caller ends it sooner.
A shorter provider-specific transport timeout or explicit provider `timeout` can still
end execution earlier. This is an upper bound, not a guarantee of available capacity.

Deploy Gateway before Engine so declared phase budgets are enforced before Engine
begins allowing the larger combined transport interval. Existing Gateway clients
without the new headers use the operator defaults. The concurrency settings are
unchanged: repository default four slots; Helm overrides OpenRouter to fifty. Limits
are per provider per Gateway process, shared across callers, not cluster-global.

## Failures and retry ownership

Admission expiry returns HTTP 503 with `detail.code = provider_queue_timeout` and
`Retry-After: 1`. No provider attempt is dispatched. Execution expiry returns HTTP
504 / `provider_execution_timeout`; caller-budget expiry returns HTTP 504 /
`caller_deadline_exceeded`. Invalid budget headers return HTTP 400 /
`invalid_timeout_budget`. None of these messages contain provider exception text.

Engine's existing connector retry loop permits at most two attempts total, shared
between transport failures and explicit queue timeouts. Queue retries honor the
Gateway's delta-seconds suggestion with the existing 0.5–8s bounds; malformed or
nonfinite values use backoff. No retry starts unless a full attempt plus delay fits
an explicit caller deadline. Other HTTP failures retain the existing caller-declared
URL4 retry behavior. A benchmark's explicit URL4 retry policy may add attempts; this
change does not create another independent retry loop or enable infinite retries.

Task cancellation and HTTP disconnect cancel the waiter/provider task and release
any held slot. Cancellation cannot undo provider work already accepted remotely.
Expired or cancelled queued calls never dispatch upstream.
Admission checks absolute deadlines after acquiring a slot, even if an event-loop
stall delays the timeout callback. Disconnect observation cancels the request task
immediately, including when capacity returns in the same event-loop turn.

## Observation and scope

One `provider call finished` log reports provider, effective concurrency limit,
`queue_wait_ms`, `provider_execution_ms` and a safe outcome (`success`, `error`,
`cancelled`, or the timeout classification). Existing call/trace correlation applies.
Execution time includes overload retries/backoff. Logs contain no request body,
credentials, caller identity, or raw provider error text.

This applies to the non-streaming evaluation dispatch path. Cache hits do not require
provider admission. SSE keeps its existing separate dispatch path; this change does
not add streaming retry or change streaming behavior.

Tests use fake providers/transports only, including 32 simultaneous requests,
phase timing, saturated admission, queue cancellation/disconnect, execution timeout,
caller deadlines, capped Retry-After and the shared connector attempt limit.
