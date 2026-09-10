# OME-1161 — Removable activity observation

Owner approved this revision on 2026-09-10 after the architecture review of PR 897.
It supersedes the concrete core/activity integration and shared operator/activity timer
in the initial implementation, while retaining the approved v1 wire contract.

Execution owners expose narrow lifecycle, model completion/failure/retry and bridge-loss
interfaces. Composition registers observation factories. Each execution creates its own
observers; context bindings do not cross outward generator yields. Generic cleanup closes
observers even on failure/cancellation. No core execution module imports activity, knows
its policy, or selects behavior based on whether activity is enabled.

The activity adapter owns ActivitySession, schema, full/off behavior, operation identities,
validation, admission and fixed 60-second heartbeat tasks. The connector retains its existing
operator diagnostics and timer independently. Two independent timers in full mode are
intentional: removing researcher activity must not change operator diagnostics.

Bridge loss is an integer fact supplied by the executor. Registered observers may decorate
its existing diagnostic with safe scalar attributes; the activity adapter supplies the
versioned, saturated loss snapshot. No activity observer means the original diagnostic.

Ordinary observer failures must not affect requests, retries, results, accounting or
cancellation. Call correlation is scoped to the current execution and call; nested disabled
executions mask inherited observers. No global mutable registration or payload event bus.

Acceptance: remove the activity package and its composition registration, then execute
success/retry/failure/cancellation paths without editing core. Verify operator diagnostics,
accounting and output preservation; all existing behavioral contracts still pass. Tests
that encode the superseded concrete constructor or shared timer migrate to the approved
interfaces without weakening their underlying isolation or cleanup assertions.
