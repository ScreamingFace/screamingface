# OME-1161 — Engine observation foundation

Owner approved this interface design on 2026-09-10 and subsequently approved two sequential
main-based PRs, explicitly no stacked PRs. PR 897 delivers the foundation below; it does not
yet enable researcher activity. The activity adapter follows after this PR merges.

## Purpose and ownership

The model connector owns request/retry/outcome facts; the executor owns transport-loss facts.
Expose these through narrow Engine-owned interfaces so optional telemetry implementations
can observe execution without becoming dependencies of execution code. The core imports no
activity schema, policy, session or heartbeat implementation.

`build_executor` accepts an immutable tuple of observer factories, defaulting to empty.
Each execution calls its factories to obtain fresh run observers. Factories are supplied
through composition, not a process-global registry. Removing registration requires no edits
to the connector, executor or run wrapper and preserves existing operator diagnostics.

## Lifecycle and facts

A run observer supplies context binding, cleanup, model-call observation and bridge-loss
attributes. Bindings surround each inner generator advancement and close; tokens never cross
outward yields. Nested runs mask inherited observer dispatch, including with empty registration.

Model observations receive start, actual selected retry attempt/delay, completion finish
reason, safe failure code and scope exit (including cancellation). They own their own resources;
the core guarantees cleanup dispatch. Model-call association cannot leak to another execution.
Bridge loss decorates the existing closing diagnostic with validated scalar attributes; its
count covers all Logs dropped by the bridge. Empty registration preserves the original record.

Ordinary observer exceptions cannot replace work results, exceptions or cancellation. Even
fault reporting is best-effort, bounded to one warning attempt per execution and excludes
exception text. Process-control exceptions retain their semantics. Operator heartbeat ownership,
provider requests, retries, results and accounting remain in their existing execution owners.

## Acceptance and next PR

Test registered observers against actual connector retries/outcomes and closing loss facts;
test an unregistered installation, concurrent/cross-task lifetime and callback faults. Pass
all existing Engine tests independently, without the activity package or deployment changes.

After merge, create a fresh branch from origin/main for the preserved activity implementation
(commit 01b3a0f1, local branch `OME-1161-activity-preserved`). It owns the approved v1 schema,
sessions, rate limits, fixed heartbeat, full/off policy and deployment wiring, under the parent
activity contract in `docs/spec/2026-09-09-OME-887-evaluation-activity.md`. OME-1161 stays open
until that follow-up lands. Client, benchmark-stage and provisional-score work remain separate.
