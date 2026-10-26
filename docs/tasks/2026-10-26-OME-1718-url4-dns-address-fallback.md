---
id: OME-1718
linear_url: https://linear.app/openmined/issue/OME-1718/try-remaining-vetted-dns-addresses-after-connection-failure
status: in_review
type: bug
priority: medium
labels: [bug, url4-sdk, agentic, autonomous]
created: 2026-10-22
closed:
---

# Try remaining vetted DNS addresses after connection failure

`GuardedTransport` vetted every DNS answer but connected only to the first. Every answer is still vetted before
any attempt (a mixed public/private set is refused before a connection). A connection-phase failure
(`ConnectError`/`ConnectTimeout`) now falls back to the next vetted address, at most `MAX_ADDRESS_ATTEMPTS` (3)
per hop. Host and SNI are kept, there is no second lookup, nothing is retried after the request was sent, and
the one total deadline bounds all attempts.

Follow-up to `OME-1544` (PR #1521). Parent epic `OME-1529`.
Ledger: `../work/2026-10-26-url4-guard-followups.md`.
