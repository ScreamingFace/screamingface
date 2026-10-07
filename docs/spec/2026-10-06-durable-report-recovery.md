# Durable report collection and explicit recovery

Extract the second SDK slice from PR #1156 onto current main. The user approved opening this draft on 2026-10-06.

Persist completed-run provenance and artifact tickets before downloads. Stream and verify artifact downloads, incrementally index complete Cases on disk, preserve full values and report.v1 output, and expose `sf.reports.list()`, `get()`, `get_async()`, and explicit `delete()`. Group saved runs by evaluation membership and preserve healthy siblings with the named partial-report error contract. Retain nullable fusion-member totals without accumulating per-Case accounting records.

Public Clients enable saving by default and support `save_results=False`. Direct internal transports retain their legacy default to preserve inherited tests; Clients explicitly select saving. Existing assertions remain intact. Add only ijson for incremental parsing, as already implemented and approved in #1156.

Exclude notebook browsing, compact accounting context/cache, presentation state/lifecycle discovery, Engine/runtime changes, and export serializer changes. Reuse the exact atomic-file helper from #1241 while it is unmerged; do not overwrite its faster serializer. Group membership is necessary recovery metadata, not a lifecycle notification feature.

Recovery requires a retained completion manifest and a valid local raw result or an unexpired Engine artifact. No paid calls. All SDK card gates must pass; prove lazy Cases, corruption recovery, storage failures, partial results, and compatibility.

Review correction approved on 2026-10-07: the separately saved evaluation manifest
is the authority for grouped recovery. A corrupted candidate's embedded membership
must not discard healthy siblings, including when opening the public evaluation ID.
For legacy directories without that manifest, prefer a locally validated sibling's
context. Preserve the existing partial-report error contract and public API.
