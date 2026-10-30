---
id: OME-1772
linear_url: https://linear.app/openmined/issue/OME-1772/refuse-url4-source-urls-with-embedded-credentials-userinfo-before-any
status: in_review
type: bug
priority: high
labels: [url4-sdk, agentic, autonomous]
created: 2026-10-29
closed:
---

# Refuse url4 source URLs with embedded credentials (userinfo) before any I/O

The url4 source guard refuses `https://user:pass@host/…`, `user@`, `@` and `:@` with the permanent
`x.source_destination_blocked` before any DNS lookup or connection, on the first hop and on every redirect
hop, so no `Authorization: Basic` header is ever sent. `%40` outside the netloc is still allowed. Found by
HupBaHa's review of #1586 (`OME-1552`).

Parent epic `OME-1529`. Ledger: `../work/2026-10-29-url4-refuse-userinfo.md`.
