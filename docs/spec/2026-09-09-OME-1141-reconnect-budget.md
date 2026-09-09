# OME-1141 — Recovery budgets measure outages

Approved by the user in this session: implement the diagnosed recovery-budget fix and
open a PR. The current deadline begins at run start; a first failure at 1085 seconds
therefore immediately stops active runs rather than resuming them.

## Contract

- Start the 90-second recovery deadline on the first observed connection failure.
- Preserve that deadline across failed attempts and short-lived reattachments.
- Once a successfully attached connection lasts at least the configured recovery budget,
  treat a subsequent failure as a new outage: reset the deadline and backoff attempt.
  This uses the existing budget as the stability threshold, avoiding a new setting and
  preventing a repeatedly restarting Engine from retrying forever.
- Reuse the Run capability and lifecycle cursor; never restart the Run on recovery.
- Preserve abort, terminal protocol errors, exhaustion cleanup, and error diagnostics.
- Apply identical policy to synchronous and asynchronous transports.

## Scope

Heartbeat tuning and the runtime cause of delayed Pongs are separate investigations.
This change makes the existing reconnect mechanism usable for long Evaluations.
It retains existing handshake timeouts and retry pacing; the deadline governs retry
eligibility, not cancellation of in-flight network calls.
