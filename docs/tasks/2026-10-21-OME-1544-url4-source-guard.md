---
id: OME-1544
linear_url: https://linear.app/openmined/issue/OME-1544/fetch-remote-url4-sources-once-per-run-with-an-ssrf-guard
status: done
type: feature
priority: medium
labels: [screamingface-engine, url4-sdk, agentic, autonomous]
created: 2026-10-09
closed: 2026-10-22
---

# url4 source destination guard (SSRF) for https sources and url4:// peer calls

Every url4 source fetch goes through one guard in `HttpIOLayer`'s transport (spec #1450 F1b):
- `https` only;
- DNS answers vetted against loopback, private, link-local and metadata, CGNAT, reserved and NAT64/6to4
  ranges, with the connection pinned to the vetted IP;
- every redirect re-checked, at most 3 hops, no downgrade;
- one total deadline for the fetch (known gap: compressed-body decoding can finish after it;
  correction tracked as OME-1720);
- a raw cap and a decoded byte cap, with bounded gzip/deflate decoding;
- `url4://` peer calls only to an allowlist that is empty by default.

Typed errors: `x.source_destination_blocked`, `x.source_redirect_limit`, `x.source_too_large`,
`x.source_timeout`. Also fixes bug `OME-1704`.

Delivered by #1521: the destination guard above plus the empty-by-default `url4://` peer
allowlist; an off-list peer gets `x.source_destination_blocked`. The hard remote-node refusal
(`x.remote_node_unsupported`) is owned by `OME-1539` (#1482), not this unit. Follow-ups, all in
PR #1555: `OME-1720` (deadline through decompression), `OME-1718`, `OME-1719`.

The "fetched once per run" acceptance moved to `OME-1543`. Parent epic `OME-1529`.
Ledger: `../work/2026-10-21-url4-source-guard.md`.

Merged in PR #1521 as `506c09178` on 2026-10-22.
