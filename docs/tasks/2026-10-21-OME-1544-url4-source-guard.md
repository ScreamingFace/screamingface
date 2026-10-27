---
id: OME-1544
linear_url: https://linear.app/openmined/issue/OME-1544/fetch-remote-url4-sources-once-per-run-with-an-ssrf-guard
status: in_review
type: feature
priority: medium
labels: [screamingface-engine, url4-sdk, agentic, autonomous]
created: 2026-10-09
closed:
---

# url4 source destination guard (SSRF) for https sources and url4:// peer calls

Every url4 source fetch goes through one guard in `HttpIOLayer`'s transport (spec #1450 F1b):
- `https` only;
- DNS answers vetted against loopback, private, link-local and metadata, CGNAT, reserved and NAT64/6to4
  ranges, with the connection pinned to the vetted IP;
- every redirect re-checked, at most 3 hops, no downgrade;
- one total deadline;
- a raw cap and a decoded byte cap, with bounded gzip/deflate decoding;
- `url4://` peer calls only to an allowlist that is empty by default.

Typed errors: `x.source_destination_blocked`, `x.source_redirect_limit`, `x.source_too_large`,
`x.source_timeout`. Also fixes bug `OME-1704`.

The "fetched once per run" acceptance moved to `OME-1543`. Parent epic `OME-1529`.
Ledger: `../work/2026-10-21-url4-source-guard.md`.
