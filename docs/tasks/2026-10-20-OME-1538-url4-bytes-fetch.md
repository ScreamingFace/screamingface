---
id: OME-1538
linear_url: https://linear.app/openmined/issue/OME-1538/fetch-url4-sources-as-bytes-with-their-media-type
status: in_progress
type: task
priority: high
labels: [url4-engine, agentic, autonomous]
parent: OME-1529
created: 2026-10-09
closed:
---

# Fetch url4 sources as bytes with their media type

`HttpIOLayer` decoded every response with `.text`, so a PNG or PDF source reached the model as
mangled text, and `;accept=` was never sent. Adds an internal bytes port
(`fetch_bytes` → `FetchedBytes(bytes, media_type)`), binary-safe HTTP and static adapters, a
refusal (`unsupported_content_type`, C8) when a text path meets a binary type, and `Accept`
from `;accept=`. Internal port only (`OME-1534` point 4).

Ledger: `docs/work/2026-10-20-url4-bytes-fetch.md`.

- 2026-10-20: implemented; PR opened (branch `OME-1538-url4-bytes-fetch`).
