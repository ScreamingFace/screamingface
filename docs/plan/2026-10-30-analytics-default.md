# OME-1768 implementation plan

Spec: ../spec/2026-10-30-analytics-default.md

1. Add failing SDK/service tests for conditional enrollment, disclosure order,
   first-operation waiting, and preservation of existing choices.
2. Service: add a conditional enrollment route and browser command, preserving
   the existing explicit accept and decline operations and event contract.
3. SDK: add conditional local storage, update the best-effort notice, hook
   import and evaluation, and add bounded automatic Colab setup.
4. Update obsolete opt-in expectations only where the authorized behavior changes;
   retain explicit-control, payload, and security assertions. Isolate test analytics.
5. Document the default and compatibility/deployment sequence; run both stack gates
   plus Node browser tests. Record any environmental limits in the work ledger.
6. Filip owns the Linear decision comment; update PR #1633 to the final behavior.

## 2 November headless amendment

Default-on applies in all environments. Remove the terminal/display gate, retain
best-effort notice output, and preserve every explicit opt-out. Update obsolete
headless-off/failed-notice expectations and add subprocess coverage for redirected,
missing and closed streams, DO_NOT_TRACK, persisted decline and process disable.
Run the SDK gates and update the existing PR; failure recovery stays out of scope.


## Review fixes

Add failing tests for default test isolation, unexpected setup errors and responsive
async local enrollment. Then update test bootstrap/CI, the setup exception boundary
and local async dispatch. Strengthen existing exact-copy and cookie assertions,
run SDK/service gates, and update the existing PR. Keep review/rollout checks open.


## Final A options

Add failing sync/async wait-error and late-reply tests, then guard the shared Colab
wait and its async scheduling boundary. Document inherited Studio enrollment,
record the known Studio UI gap with no follow-up planned for now, and prepare an
owner-review request for Filip to post.
Run SDK gates and update PR #1633; do not merge or represent approval as received.

## Dmitry review — 3 November

Add response-reordering tests across independent replicas with a shared browser
jar, then protect declined state with an explicit-only opt-out cookie. Verify
late enrollment and identity refresh cannot restore permission, while explicit
accept can. Add fork regressions and reset the process-local setup guard on PID
change. Document the full-service-upgrade requirement; run both stack gates and
browser tests. Owner sign-off and deployed browser acceptance remain open.
