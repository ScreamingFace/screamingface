---
ticket: OME-1768
---

# Colab analytics recovery regression contract

Filip requested failing tests after production Colab observations on SDK 0.1.11:
automatic setup ended unknown/disabled; manually repeating normal setup succeeded;
a real client validation failure reached PostHog; a subsequent client loop found
tracking disabled before its first operation. The precise browser error is unknown.
Local fault injection reproduces both setup failures and delivery failures.

This unit adds tests only. It does not change production behavior, implement
diagnostics, modify the service, send production events, or replay missed events.
The recovery expectations extend the original one-attempt setup policy; they are
the target behavior requested in this conversation, not proof of a previously
documented recovery guarantee.

## Expected behavior

- A later evaluation can recheck browser consent after temporary setup failure,
  including an expired two-second setup attempt, without manual enable/setup calls.
- After temporary event-delivery failure, later evaluations can resume delivery
  when the browser is healthy and still accepts tracking.
- Recovery never overrides saved decline, process-only disable, or DO_NOT_TRACK.
- The initial setup wait stays within two seconds, allowing scheduling tolerance
  in the test. A late reply from an expired attempt cannot restore consent.
- Recovered evaluations deliver their own start/finish pair with matching operation
  IDs. Missing events from previous evaluations are not replayed.
- The tests exercise synchronous and asynchronous public clients. Browser exchange
  is simulated; invalid evaluation inputs avoid paid model calls.

Tests require recovery on the next evaluation with an immediately healthy browser.
A future backoff design may need an explicit clock seam; these tests do not invent
a retry timer or prescribe preserving consent during an uncertain browser response.

