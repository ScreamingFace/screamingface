---
ticket: OME-1768
---

# Colab analytics recovery regression contract

Filip requested failing tests after production Colab observations on SDK 0.1.11:
automatic setup ended unknown/disabled; manually repeating normal setup succeeded;
a real client validation failure reached PostHog; a subsequent client loop found
tracking disabled before its first operation. The precise browser error is unknown.
Local fault injection reproduces both setup failures and delivery failures.

The initial unit added failing tests. Filip subsequently authorized implementing
the fix in PR #1703 and confirmed both decisions on 2026-11-06: retry on a later
evaluation and include safe local diagnostics. He then authorized five seconds
for both consent setup and background delivery, replacing the initial two-second
setup budget. Healthy exchanges return sooner; explicit enable uses the same budget.
The fix does not modify the service, send diagnostic uploads, or replay missed events.
The recovery expectations extend the original one-attempt setup policy; they are
the target behavior requested in this conversation, not proof of a previously
documented recovery guarantee.

## Expected behavior

- A later evaluation can recheck browser consent after temporary setup failure,
  including an expired five-second setup attempt, without manual enable/setup calls.
- After temporary event-delivery failure, later evaluations can resume delivery
  when the browser is healthy and still accepts tracking.
- Recovery never overrides saved decline, process-only disable, or DO_NOT_TRACK.
- The initial setup wait stays within five seconds, allowing scheduling tolerance
  in the test. A late reply from an expired attempt cannot restore consent.
- Recovered evaluations deliver their own start/finish pair with matching operation
  IDs. Missing events from previous evaluations are not replayed.
- The tests exercise synchronous and asynchronous public clients. Browser exchange
  is simulated; invalid evaluation inputs avoid paid model calls.

Tests require recovery on the next evaluation with an immediately healthy browser.
A future backoff design may need an explicit clock seam; these tests do not invent
a retry timer or prescribe preserving consent during an uncertain browser response.

## Implementation contract

- One setup attempt per entry-point call when consent is unknown; no autonomous
  retry loop. Accepted or declined consent and pending control work are left alone.
- Concurrent evaluations share pending setup. Each waits at most five seconds.
  Expiry/cancellation of an old waiter must not cancel a newer setup generation.
- A delivery failure invalidates local consent and drops pending events. A later
  evaluation rechecks the browser; it never forces explicit acceptance.
- Consent carries a process-local revision so recovery cannot revive an operation
  that began before the failure, even when the browser ID is unchanged. This
  revision is never transmitted or persisted.
- Malformed responses, deadlines exceeded by late replies, worker-start failure,
  queue saturation, declined persistence failure and ID changes receive coverage.
- Colab status gains last_error, last_error_stage and setup_attempts. Codes contain
  no exception messages, paths, URLs, prompts, tokens or identifiers. Successful
  consent setup/control clears the prior error; queue drops and delivery failures
  remain visible until a subsequent successful operation.
- Recoverable browser failures remain fail-closed; opt-outs always win.

