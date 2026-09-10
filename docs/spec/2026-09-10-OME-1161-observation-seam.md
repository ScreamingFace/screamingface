# OME-1161 — Removable Engine activity observation

Approved direction, 2026-09-10. This documents the execution interface supporting the
activity contract in `docs/spec/2026-09-09-OME-887-evaluation-activity.md`.
PR 897 is documentation-only. Code follows in sequential main-based PRs, each at most
500 added plus deleted lines including tests/docs. No stacked PRs.

## Problem and useful behavior

A researcher waiting on an evaluation needs to distinguish a long model call, a retry,
and a terminal outcome. Existing operator logs do not provide the structured, node-associated
activity stream needed by the Client widget. The connector already knows request start,
actual selected retry delay, completion finish reason and failure code.

An activity adapter can turn these facts into started, running, retrying and terminal
observations on the current URL4 node. Occurrence IDs associate updates with one call;
producer timestamps support freshness checks. A heartbeat proves the Engine is still
waiting, not that the provider is making internal progress. Missing telemetry is not failure.

The Engine must expose facts without importing the activity schema, privacy policy,
admission limits or heartbeat implementation. This keeps activity removable and prevents
researcher-facing telemetry changes from becoming changes to request execution.
URL4 continues carrying generic structured Logs; its protocol needs no further changes.

## Interfaces and ownership

| Owner | Interface responsibility | Why it belongs here |
| --- | --- | --- |
| Composition | Inject an immutable tuple of observer factories; empty registration is valid | Wiring is explicit and run inputs cannot invent adapters |
| Run wrapper | Construct fresh observers per execution, bind context, dispatch cleanup | Execution owns lifetime; adapters own their resources |
| Model connector | Report request start, actual retry attempt/delay, completion and failure | It already owns these facts across benchmarks |
| Executor | Offer the dropped-Log count at the existing closing diagnostic | Consumers should not parse transport-loss prose |
| Activity adapter | Own schema, policy, sessions, identities, validation, admission and timers | Those choices belong to optional activity, not core execution |

A run observer exposes context binding, asynchronous cleanup, model-call observation and
optional bridge-loss attributes. A model observation accepts start, retry, completion,
failure and scope exit, including exception/cancellation information for cleanup.
These are narrow interfaces for known execution facts, not a general payload event bus.

## Lifetime, isolation and failure behavior

Each top-level Engine execution creates its own run observers. Activity uses one session
for that execution; nested candidates/calls share its budget but get distinct operation IDs.
This prevents fan-out from multiplying the allowance and gives cleanup one lifetime to revoke.
A Client connection or reconnect does not create an Engine activity session.

Bindings surround each inner generator advancement and close, and restore context before
outward yields. A different task may advance or close the generator, so ContextVar tokens
must never cross those yields. Nested executions mask inherited observer dispatch, including
empty registration. Call association is checked against its owning execution.

Ordinary observer failures cannot replace requests, results, original exceptions or
cancellation. Process-control exceptions retain their semantics. Failure diagnostics are
also best-effort, omit exception text, and attempt at most one warning per execution.
The adapter must release its resources through the supplied lifecycle; run cleanup revokes
activity and joins remaining heartbeat tasks, including those held by abandoned call scopes.

Existing operator diagnostics keep their original heartbeat/backoff independently. Activity
owns a separate fixed 60-second timer. Removing activity therefore cannot change operator
behavior. The execution layer never branches on activity-enabled state.

Bridge-loss decoration accepts validated scalar attributes on the existing closing Log.
The count covers all bridge-dropped Logs, not just activity; empty registration preserves
the original diagnostic. The activity adapter supplies the versioned, saturated snapshot.
Loss reporting is best-effort and closure-time; its absence does not certify loss-free delivery.

## Activity policy and follow-ups

The parent v1 contract remains authoritative: rolling 100/s, burst-200 admission, 40 tokens
reserved from routine records for retries/outcomes, no lifetime cutoff, safe allowlisted
fields and deployment-owned full/off policy defaulting off. Capacity refills during long
runs; suppression affects telemetry, not evaluation. No activity archive is introduced.
Off controls the new producer, not all existing telemetry. Aggregate mode remains deferred.

Benchmark loading/answering/grading/aggregation facts belong in later benchmark producers.
OME-1135 owns Client interpretation, bounded history/deduplication, loss disclosure and
freshness display. OME-699 owns exact case/member/role attribution; unknown identity stays
absent. OME-932 owns provisional scores. None is implied by merely defining activity kinds.

## Acceptance

Test generic dispatch with ordinary callback/diagnostic faults, nested context isolation,
startup cancellation and malformed loss attributes. Test actual connector retries/outcomes,
concurrent executions and cross-task cleanup when integration lands. Test an installation
without the activity package/registration: requests, retries, results, accounting,
cancellation and operator diagnostics must still work without core edits.

The activity PRs add fake-provider streams, heartbeat/revocation, pressure/recovery, privacy,
long-duration simulation and deployment tests. Each PR passes its own gates independently.
The preserved implementation is evidence that these interfaces have a concrete consumer;
it is not shipped by this docs PR. OME-1161 stays open until the feature deliveries land.
