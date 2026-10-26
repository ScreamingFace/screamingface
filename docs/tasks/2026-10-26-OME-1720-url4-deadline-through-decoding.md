---
id: OME-1720
linear_url: https://linear.app/openmined/issue/OME-1720/enforce-source-deadline-during-compressed-body-decoding
status: in_progress
type: bug
priority: medium
labels: [bug, url4-sdk, human, autonomous]
created: 2026-10-22
closed:
---

# Enforce source deadline during compressed-body decoding

Each fetch now gets one absolute deadline. `FetchState` carries it to every redirect hop, and the capped stream
checks it on every raw chunk and every decompress call, including calls that produce no output, such as empty
gzip members. The stream also yields to the event loop on each raw step. A fetch past the deadline fails with
`x.source_timeout` and never succeeds late; a result is checked once more before it is returned. Streams close on
timeout and on cancellation, and caps and valid decoding are unchanged.

Follow-up to `OME-1544` (PR #1521). Parent epic `OME-1529`.
Ledger: `../work/2026-10-26-url4-guard-followups.md`.
