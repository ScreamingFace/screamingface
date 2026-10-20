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
