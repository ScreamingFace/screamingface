# Colab bridge service — design proposal

Status: owner approved browser-mediated delivery on 25 September 2026.
Parent: 2026-09-09-OME-1124-analytics-spec.md. Landing: apps/analytics only.

## Established behavior

Consent-only iframe/state requests may run before consent. They do not create an
analytics identifier or send PostHog events. Explicit acceptance stores a
low-cardinality versioned choice. A separate identity request then reads or creates
an opaque UUID in an HttpOnly, Secure, SameSite=None, Partitioned, host-only cookie.
Decline stores the choice and expires the ID. No identity association or login.
Browser storage loss is unknown consent, not implied acceptance.

Retain the parent spec's five bridge routes. Every response is no-store and
no-referrer. Reject foreign origins on mutations; browser messaging validates
parent source, exact allowed origin, command schema, protocol version and nonce.
Deployment supplies the verified Colab output-origin allowlist and ancestor CSP;
no guessed broad googleusercontent allowlist is a production default.

## Proposed revocation choice

Recommend browser-mediated delivery: the later Colab SDK adapter hands events to
the active iframe, which dispatches through a same-origin bridge endpoint. That
endpoint checks current consent cookies for every batch and binds browser identity
to its own ID cookie, rather than trusting an ID supplied by the runtime. Cookies
are restricted to bridge paths; existing local SDK /v1/events remains cookie-free.
The consent and ID cookies share the browser's Colab partition, so later browser
requests from another notebook observe the changed choice. Requests already sent
before the decline response may complete. Concurrent enable/disable is ordered by
browser cookie response application, not promised globally instantaneous.

The owner selected this approach. This avoids a new server database and a long-lived consent capability copied into
a Python runtime. It changes the parent's proposed capability-based revocation
architecture and requires a real Colab nonblocking delivery
spike before SDK rollout. No claim is made that the anonymous /v1/events endpoint
can prevent a modified client from misrepresenting consent.

Alternative: keep direct runtime HTTP delivery, issue short-lived capabilities and
check a shared revocation store on every Colab batch. This requires shared state
across replicas, operational ownership, expiry/cleanup, and fail-closed behavior
when the store is unavailable. A process-local dictionary is insufficient.

## Proposed expiry and acceptance

Use a renewable 180-day cookie lifetime, retaining the same ID while valid. This is
separate from the already agreed 90-day event retention and does not guarantee the
browser retains cookies that long. Browser acceptance must cover notebook/runtime
replacement, full browser restart, blocked storage, two active notebooks, consent
revocation, and no identifier creation before acceptance. No paid eval required for
service contract tests. SDK scheduling acceptance is a separate implementation.
