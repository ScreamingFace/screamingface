# OME-1161 — Optional Engine observation interfaces

Approved 2026-09-10. Each sequential main-based PR must change at most 500 lines
(additions plus deletions, including tests/docs). No stacked PRs.

PR 897 introduces only Engine-owned observation ports and fault-isolated dispatch.
Execution integration and the concrete activity adapter arrive in later PRs.
The interfaces have a known consumer preserved at 01b3a0f1, not a speculative event bus.

Factories create fresh run observers. Run binding masks inherited observer dispatch;
call binding is tied to its owning run. Adapters supply context binding, cleanup,
model-call observation and scalar bridge-loss attributes. They own telemetry policy
and resources; the Engine retains requests, retries, results and accounting.

Model observations accept start, actual retry attempt/delay, completion finish reason,
failure code and scope exit. Ordinary observer faults cannot replace execution results
or errors; process-control exceptions propagate. Diagnostic failures are contained and
warning attempts are bounded to one per execution. Invalid loss attributes are discarded.

Tests cover callback/factory faults, nested context isolation, startup cancellation and
loss validation. Existing Engine behavior is unchanged: this PR wires no observers into
execution. Integration tests follow with the execution hooks, including cross-task cleanup.
The overall feature remains OME-1161; merging this foundation does not complete it.
