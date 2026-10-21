---
id: OME-1695
linear_url: https://linear.app/openmined/issue/OME-1695/remove-every-profile-document-writer-and-make-the-index-offline-only
status: in_progress
type: task
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1138
created: 2026-10-21
closed:
---

# Remove every Profile document writer and make the index offline-only (Stage E, E4b)

Landing E4b of Stage E (`OME-1209`), after E4a (`OME-1685`) made every reader Connection-only. No
runtime path writes or removes a legacy Profile document any more: the native OAuth callback, the
native key replacement and delete, and the D18 PUT and DELETE work on the pair's Connection alone,
and the opt-in credential import at startup is retired (a set
`AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE` only logs a warning). The app
no longer wires `ProfileIndexStore`; the index, its read models and the backfill tools stay for E5,
reachable only from the offline tools. The plugin hook names are E4c; no document or blob is
deleted.

Ledger: `docs/work/2026-10-21-e4b-no-profile-writer.md`.
