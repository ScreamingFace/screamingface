# Colab SDK adapter and dev verification — 14 October 2026

Draft PR #1116; do not merge. Parent OME-1305; Colab work OME-1378.

## Implementation

The SDK chooses a Colab browser adapter instead of direct runtime HTTP. Explicit
setup reads remembered consent in a daemon worker. Unknown consent is off with a
nonblocking disclosure; explicit controls asynchronously persist acceptance/decline
or reset the browser ID. A memory-only bounded queue sends four allowlisted events
through the server's cookie-checked bridge. There is no local consent file in Colab,
no fallback to direct ingestion, and no cookies copied into Python.

Every browser exchange validates frame source, exact origin, nonce, command and
protocol version. It removes the frame/listener on success or deadline. Python
control generations ignore stale results after disable/reset; event dispatch checks
current consent/session. Browser/server requests already dispatched can finish.
Colab session-only opt-in is explicitly unsupported because the bridge requires
browser consent; process-only disable is supported. DNT suppresses all requests.

## Verified evidence

- Full SDK regression run: 1,999 passed, 26 skipped, 26 paid-lane tests deselected;
  coverage 95.93% (95% gate passed). The final focused analytics run included two
  additional tests and passed all 69. Node parent-script suite: five passed.
- Full SDK lint/format, Pyright, deterministic notebook check, wheel/sdist build,
  distribution validation, and verification notebook schema/syntax checks passed.

- Focused Python consent/transport tests and Node parent-script tests cover unknown
  consent, acceptance, malformed IDs, DNT, reset, late results, timeout cleanup,
  spoofed messages, decline and unavailable/revoked bridge behavior.
- Local SDK success fixtures sent four events through real dev ingestion; each
  returned 202. PostHog MCP read back both successful operation pairs, installation
  `cbec4493-5504-4a2a-aac8-163de74bb329`.
- Colab adapter/server integration used an isolated curl cookie jar in place of
  eval_js. Four browser-scoped events returned 202 and were read back through MCP,
  browser ID `b19ecd63-f423-4b48-8f87-3318a2e7d199`. Explicit decline then rejected a
  replay with 403. Both checks emitted zero events for subsequent SDK operations.
- These used deterministic Engine/Scoreboard success fixtures. They did not execute
  paid inference, write a scoreboard submission, or verify actual Colab scheduling.
- Earlier user-run Chrome/Safari notebook tests demonstrated cookie persistence;
  they did not exercise this new background-worker adapter. Safari's first-run
  JavaScript output warning also reproduced without the ScreamingFace bridge.

## Outstanding acceptance gates

1. Run `docs/verification/analytics-colab-sdk.ipynb` in actual Colab in Chrome and
   Safari. Verify that background eval_js runs while the main kernel cell continues,
   events arrive, decline is remembered, fresh runtimes recover the accepted ID,
   and blocked storage leaves analytics off. Read back returned event IDs in PostHog.
2. Dev PostHog project 601604 has `anonymize_ips=false`. Existing and today's test
   events contain an IP property although GeoIP is disabled and person processing
   is propertyless. Consent to enabling IP discard was requested; no settings change
   is claimed here. The server adapter does not forward an SDK-supplied IP; this
   check did not prove which network hop supplied PostHog's stored IP.
3. The agreed 90-day raw-event maximum is **not verified/enforced**. Current PostHog
   docs say event retention follows the plan (free: one year; paid: seven years),
   cannot be shortened on request, and is not a deletion mechanism. The project
   API's session-recording retention is unrelated. This requires a supported
   deletion solution or an explicit revised policy before rollout; a 90-day query
   filter is not deletion. No historical events were deleted by these tests.

Sources checked via PostHog MCP:
- https://posthog.com/docs/data/events-retention
- https://posthog.com/docs/privacy/data-storage
- https://us.posthog.com/project/601604/activity/explore

The SDK README/disclosure now avoid claiming that the 90-day target is enforced.
The implementation remains dev-only, anonymous, and draft; website analytics and
identity linking are not included in this change.

## 20 October 2026 — main reconciliation and review

Rebased the two analytics commits onto `c77a85222f6cd04c08059cce41b9edf188ad71e5`.
Resolved overlapping SDK imports/exports and README/changelog additions while preserving
main's report/reproduction APIs, default-client validation and submission handling.
The rebased tree matches the separately validated conflict-resolution snapshot.

Validation completed: Pyright; Ruff lint/format; deterministic notebook check; build
and distribution validation; 69 focused analytics tests; five Node browser-script tests.
Full SDK regression: 4,265 passed, 33 skipped, 75 paid-lane tests deselected;
97.00% coverage (95% gate passed). Refreshed remote CI remains separate from
these completed local checks.

Read-only review using `.claude/agents/sf-code-review.md` found a Colab opt-out race:
when a pending state/accept response resolves after `analytics.disable()`, JavaScript
can still issue its subsequent `id` request. Python's generation guard ignores the
result but cannot prevent that new request. Reproduced with real SDK disable and the
actual parent script against a simulated iframe transport; no external cookies or
services changed. This remains an action-required finding, not fixed by the rebase.
No review comments were posted and the PR remains draft.


## 20 October 2026 — consent review fixes

Addressed the follow-on-ID review finding and the separately reported crashed-writer
lock defect. Colab JavaScript now performs exactly one command per exchange; Python
sequences state/accept/reset and ID retrieval, rechecking generation, opt-out and DNT
between commands. A single two-second budget covers the sequence rather than resetting
on each command. Persisted preference writes now use nonblocking OS locks (flock on
POSIX, byte-range locking on Windows) with the existing bounded wait. The lock inode
remains in place; ownership is released by the OS on process exit, including a kill.

Regression evidence: the killed-writer test failed against the prior implementation
with the reported busy error. With the fix it persists decline and a fresh interpreter
reports analytics disabled. Separate forged source/origin/version/nonce/command/data
tests now assert the request remains unresolved before sending a valid response.
Removing the entire message guard in a disposable copy makes all six forged-message
tests fail. State/accept/reset cancellation and DNT regressions ensure no subsequent
ID request; timeout regressions pin the shared budget. Native Windows execution and
real Colab browser scheduling are not covered by these local tests.

Final validation of the consent fixes: 4,274 SDK tests passed, 33 skipped, 96.97%
coverage (95% gate passed); ten Node browser-script tests passed. Type checking,
lint, formatting, deterministic notebooks, build and distribution checks passed.
Paid tests remained excluded by the suite's default collection guard. The six
forged-message mutation failures were observed only in the disposable copy.


## 20 October: explicit analytics destination

Owner approved replacing engine-derived routing with one explicit HTTPS origin,
`SCREAMINGFACE_ANALYTICS_ENDPOINT`, defaulting to production. Native delivery and
Colab use the same process-cached origin; switching requires a restart. No engine
hostname inference or cross-environment fallback. Local consent remains shared;
use a separate config file for isolated test preferences. The verification notebook
explicitly selects dev before any analytics use. Production retention/IP gates
remain unresolved; this change does not verify remote staging/production services.

Validation: 90 focused analytics tests and 10 Node browser-script tests passed.
Full SDK regression: 4,286 passed, 33 skipped, 96.97% coverage (local HTTP fixture
permissions required outside the sandbox). Pyright, Ruff lint/format, notebook
checks, wheel/sdist build and distribution checks passed. No live production or
staging events were sent, and no new real-browser verification is claimed.


### Review corrections: notebook observer and origin serialization

The notebook observer now accepts and forwards the adapter's `timeout_sec`.
A smoke test extracts the actual notebook function and runs four event dispatches
through the real adapter/exchange with only Colab eval_js stubbed. The old observer
fails this regression test; the fixed observer records all four acknowledgements.
The endpoint resolver canonicalizes host case and default HTTPS ports, and the
parent script uses URL.origin before its strict message-origin comparison.
Regression coverage includes explicit :443, uppercase hosts, nondefault ports and
IPv6. All 95 focused analytics tests and 12 Node tests passed; no real Colab or
live PostHog check was performed for these corrections. Existing release gates
remain unchanged; PR stays draft.

### Pending opt-out verification and current SDK dev read-back

The notebook now asserts `pending is False` after the browser decline deadline,
then checks the declined choice. A regression executes the actual notebook opt-out
tail with the real adapter and a blocked decline exchange. The former notebook
falsely passes; the corrected notebook raises AssertionError. All 96 focused
analytics tests, Pyright, Ruff and notebook checks pass.

Ran the current checkout's local Python SDK against the explicit dev endpoint:
unknown consent emitted zero events; `sf.analytics.enable()` followed by fixture
evaluation/submission produced four HTTP 202 acknowledgements; persisted disable
followed by the same operations emitted zero additional events. Product work was
stubbed (no paid evaluation or real scoreboard submission), analytics delivery was
real. PostHog MCP project 601604 returned all four exact event IDs with matching
session and expected outcomes after an ingestion/read-back delay:

- evaluation_started: a8473f04-566f-4c88-85bf-9b2399146464
- evaluation_finished: f7f4c2f2-43ec-4e3f-80ea-dbb5aa44e3c0
- submission_started: 5d7b1f4e-daf7-4c93-a352-a5ffa79f31d3
- submission_finished: 3c8dccab-d73e-4c22-9585-b04ac3ad3896

Session: 50f6407f-3458-41f4-acb5-f83801e79987. Both finishes succeeded with
under_1s duration; origin python, mode byok, scope installation. The current
Chrome/Safari notebook run remains outstanding; no staging/production test events
were sent. This verifies local dev analytics delivery, not production readiness.


### Owner-approved retention revision — 20 October 2026

Owner approved replacing the 90-day raw-event deletion commitment with
PostHog-managed retention. Current SDK disclosure, verification notebook, SDK and
service READMEs, and governing specs/plans now reflect that policy. Historical
entries above describe the previous requirement and are superseded by this entry.
No fixed deletion deadline or indefinite-storage guarantee is asserted; query
retention is not physical deletion. Data allowlist, opt-in consent, opt-out behavior,
IP-handling gate, browser verification gate and historical-deletion procedure are
unchanged. No PostHog settings or stored events were changed by this amendment.

### Unavailable stdin regression — 20 October 2026

Owner requested a fix for the optional disclosure crashing connection-panel setup
when GUI/pythonw provides no stdin. Plan: treat missing/closed/unavailable terminal
input as noninteractive, preserve local Jupyter disclosure, and verify both public
connect entry points with analytics initially off. No consent or event schema changes.

Outcome: `_interactive_stdin()` treats absent stdin and AttributeError/OSError/
ValueError from terminal detection as noninteractive. Local Jupyter bypasses this
terminal-only check. The regression exercises real connection-panel creation via
both `sf.connect()` and `client.connect()`, for missing, closed and erroring stdin
in Python and local Jupyter, while asserting analytics stays off and no consent
file is created. All 12 cases failed before the fix and passed afterward.

Validation: `uv run .claude/scripts/run_gates.py screamingface` passed all gates:
append-only tests, Ruff lint/format, Pyright, full parallel SDK suite with the 95%
coverage floor, notebook checks, build and distribution validation. `git diff
--check` passed. Root cause was an unconditional terminal probe in optional setup;
no public API, consent semantics, or browser transport changes were needed.

### Confirm explicit Colab opt-in — 20 October 2026

Owner approved a bounded wait in `sf.analytics.enable()` so the next evaluation
can start with confirmed consent. Plan: keep automatic initialization, events and
opt-out asynchronous; wait only on explicit acceptance for at most three seconds
(including queue delay), cancel stale acceptance on timeout, and print a clear
success/failure message. Preserve the returned status dictionary for callers.
Test success, unavailable browser, bounded timeout, late responses, concurrent
opt-out, and immediate evaluation readiness; update quickstart/notebook guidance.

Outcome: added condition-based confirmation around explicit Colab acceptance only.
Timeout clears local pending acceptance and invalidates its generation; a late
browser reply cannot enable tracking. Opt-out wakes waiting callers immediately.
The status dictionary remains compatible, and Colab prints a clear result. The
verification notebook now asserts the returned state without a polling cell.

All four new regression scenarios failed before implementation and passed after;
56 focused analytics tests passed. The complete `screamingface` gate runner passed
append-only tests, lint/format, Pyright, full parallel tests with the 95% coverage
floor, notebook validation, build and distribution checks. No live Colab rerun of
this revised confirmation flow was performed in this iteration; prior browser
results do not constitute verification of this new wait behavior.

### Confirmation-only enable output — 20 October 2026

Owner approved hiding the returned dictionary: public `enable()` now returns None
and prints its result; `status()` remains the explicit details API. Keep CLI JSON
output through the same internal consent operation. Existing return-value tests
and the verification notebook will be migrated to status() without removing their
consent, identity or race assertions. This owner-approved API change supersedes
the previous dictionary-return compatibility decision.

Outcome: enable() now returns None and prints one confirmation line; status() is
unchanged. The CLI invokes the shared private consent operation and still prints
JSON. Updated notebook/docs and migrated old return-value assertions to status()
while preserving identity, consent, cancellation and concurrency checks.

Validation: both new output tests failed before the fix; all 58 focused analytics
tests passed afterward. An actual local IPython run_cell display check (consent
operation stubbed) produced exactly `Analytics enabled.` and no rich display output.
The full SDK gate runner passed lint/format, Pyright, complete parallel tests with
95% coverage floor, notebook checks, build and distribution checks. It ran with
--skip-append-only specifically for the owner-approved return-contract test
migration; no test was removed or behavior assertion relaxed. No live browser
persistence or PostHog revalidation was claimed for this output-only change.

### Confirmation-only disable output — 20 October 2026

Owner reported the remaining status dump from disable(). Apply the same command/
status split: public disable returns None and confirms local tracking has stopped;
if browser persistence is pending, say the choice is still being saved, not that
it has been persisted. Keep immediate opt-out, detailed status(), and CLI JSON.
Migrate existing disable return-value assertions without weakening opt-out checks.

Outcome: public disable() now returns None. Its message confirms immediate local
opt-out and separately describes pending or failed browser persistence. CLI JSON
uses the shared private operation. Two new display tests failed before the fix;
all 60 focused tests passed afterward. Local IPython run_cell with a stubbed
consent result confirms one message and no rich-display dictionary.

The full SDK lint/format, type, parallel test/95% coverage, notebook, build and
distribution gates passed. The append-only check was skipped only for migrating
the existing, owner-approved disable return-contract assertions to status(); all
underlying consent and crash-recovery assertions remain. No live browser rerun or
new PostHog-delivery claim is made for this presentation change.
