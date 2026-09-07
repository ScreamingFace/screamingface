# OME-1013 — Implement one notebook reporting flow

Spec: [Notebook error reporting](../spec/2026-09-07-OME-1013-notebook-error-reporting.md).
Owner direction: combine OME-1014 into OME-1013 and replace the public receipt-management
interface with compact Copy/Report actions. This plan records the combined work; it does not
claim PR #756 already implements it.

1. Reconcile #756 with current main (including merged #842). Preserve the owner's modified
   quickstart and exported diagnostic file in its existing worktree. Use an isolated checkout
   for implementation/gates. Update the older branch spec/plan to point to this superseding spec.
2. Before implementing transport/UI, inspect report-audience credential reuse and demonstrate
   browser Turnstile/clipboard support in the supported notebook hosts. Confirm endpoint/site-key
   configuration and the dev sink through read-only deployment access. Record missing access
   explicitly; do not bypass Access/Turnstile or weaken service settings to make a demo pass.
3. Write failing tests for the private snapshot lifecycle, before-frame trace retention and
   sanitized diagnostic failure logs. Replace public lookup/receipt exports with private values,
   remove the global ring if unnecessary, and preserve bounded ownership/disposal.
4. Define a private projection into the existing service schema, including safe error.message,
   attributable primary candidate/correlation and capped extra context. Test its serialized bytes
   against the real service contract in integration tests without importing app internals into
   Client runtime code. No new public serialization contract or service schema is introduced.
5. Implement one private submission state machine for prepared/sending/received/recoverable
   failure. Freeze the exact preview payload and idempotency key, resolve authentication safely,
   submit from the kernel, parse report ref/delivery/ticket, and preserve draft on failure.
6. Build the compact SFDS toolbar and inline form, optional note/reply address, exact preview,
   identity disclosure and explicit Send. Add real frontend support for browser-owned clipboard
   and Turnstile where available, plus usable static/selectable/save fallbacks. Never add a global
   exception hook or expose credentials in widget serialization.
7. Run the Client SDLC gates and focused service-contract tests, then real notebook UX checks.
   Perform the two labelled dev submissions and idempotent replays from the spec. Inspect their
   stored identity/payload and actual delivery results. Record refs, revision, test counts and
   delivery evidence without recording tokens or unrelated reports.
8. Update #756's title/body around the complete final implementation and validation. Close
   OME-1013 and its mirrors only after the implementation lands and required verification is
   complete; close OME-1003 when its overall acceptance is met.

## Consolidation ledger

- OME-1013: surviving implementation ticket; PR #756 remains open.
- OME-1014: Duplicate of OME-1013, closed because scope moved, not because sending shipped.
- OME-1003: parent retained; completed OME-967 no longer blocks it.
- OME-416: retain version provenance; reporting acceptance moves to OME-1013 under OME-1003.
- Service closeout (OME-1005–1012), OME-976's deployment decision, OME-1072's evaluation semantics,
  OME-979's failure attribution and OME-1124's analytics remain separate; no automatic closure.

## Integration evidence — 2026-09-07

The live Engine and internal reporting route advertise the same Access audience. All 79 existing
Client authentication tests pass, including sharing one login for matching audiences. Report
authentication should use the existing per-Client token store; no separate global token store is
needed. This is feasibility evidence, not an accepted live report.

Real notebook verification awaits a working browser connection, the reporting Turnstile public
site key/allowed origin and notebook selection. Backend verification also needs deployment access
(no kubectl context is configured). Full evidence and the browser bootstrap failure are recorded
in [the integration ledger](../work/2026-09-07-OME-1013-report-auth-integration.md).
