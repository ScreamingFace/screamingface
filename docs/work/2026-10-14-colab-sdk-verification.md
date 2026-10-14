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
