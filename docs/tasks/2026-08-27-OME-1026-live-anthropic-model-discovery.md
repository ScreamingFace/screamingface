---
id: OME-1026
linear_url: https://linear.app/openmined/issue/OME-1026/aigateway-automatically-discover-models-offered-by-anthropic
status: In Progress
type: feature
priority: 2
labels: [aigateway]
created: 2026-08-27
closed:
---

# AIGateway: automatically discover models offered by Anthropic

Opt-in live model discovery for the Anthropic provider — the **second** implementation of the
`ModelListingProvider` port delivered by OME-972 (`cc9deb4a`), reusing the existing process-local
`ModelCatalog` (TTL 300 s, stale 3600 s, failure damping 30 s, single-flight) unchanged. A healthy
snapshot changes only the Anthropic **ID set** published by `GET /v1/models`; chat dispatch,
admission, and `anthropic:static` parameter evidence are untouched.

Anthropic's catalog is credentialed-only (401 without `x-api-key`), so discovery is strictly
opt-in behind one dedicated operator secret, `AIGW_ANTHROPIC_DISCOVERY_API_KEY`. Account API keys
(`credential_blobs`) and Claude-subscription OAuth tokens never feed the shared snapshot. The
three off-switches — no key configured (the default), `AIGW_ANTHROPIC_LIVE_MODELS=false`, and the
global `AIGW_DISCOVERY_ENABLED=false` — each mean zero Anthropic catalog egress and the exact
compiled seed listing. Anthropic has no provider-disable flag and introducing one is out of scope.

Completeness without a census: Anthropic's envelope carries no `total_count`, so completeness is a
strict `has_more`/`last_id` cursor walk under bounded pages, models, bytes, ID length, and one
aggregate deadline, with a cursor-progress guard over the SET of seen cursors. Cursors are
upstream-controlled URL material and must clear the same safe charset as publishable IDs before
being URL-encoded into the next dial. Aliases and date-stamped snapshots publish unfolded as
separate dispatchable IDs in upstream order, deduplicated on first occurrence (D7, owner-approved
2026-08-26) — no alias folding is inferred.

- Ledger: `docs/work/2026-08-27-OME-1026-live-anthropic-model-discovery.md`
- Planning pack: `.agent-team-AIGW/live-anthropic-model-discovery/` (local, untracked)
- Baseline: OME-972 / PR #739 merged as `cc9deb4a`; branch
  `OME-1026-live-anthropic-model-discovery`
- Related: OME-972 (foundation), OME-479 (§6.3 superseded for the model LIST only), OME-818
  (current seed catalog), SF-284 (Settings dropdown consumer)

## Deviation accepted at start (owner decision, 2026-08-27)

The credentialed Anthropic Models probe named as this issue's "First implementation step" was
**not run** — `AIGW_ANTHROPIC_DISCOVERY_API_KEY` is not available in the execution environment,
and the Claude Code OAuth token is off limits for discovery by locked decision D2. The owner chose
to proceed without it. U3/U4 fixtures derive from the Context7-verified official Models API
contract recorded in the planning pack's `research_notes.md`. Real page-2 behavior and the
observed alias/snapshot interleaving remain unverified against production; every unverified shape
fails closed to stale-then-seeds. Zero credentialed egress occurs in this unit.

## Implementation status (2026-08-27)

Implemented through units U1–U8 and gate-green on branch
`OME-1026-live-anthropic-model-discovery` (baseline `cc9deb4a`). **Not committed** — no
authorization to stage, commit, push, or open a PR was given. Full detail in the ledger.

- 141 new tests; full non-live suite 4194 passed / 0 failed; pyright 0 errors; coverage ≥80.
- `run_gates.py aigateway --skip-append-only` → ALL GATES GREEN.
- **PR waiver required, one file:** `apps/aigateway/tests/conftest.py`. The autouse no-egress
  tripwire hardcoded the legacy `get(self, url, *, timeout_s, max_bytes)` signature, so it gains
  and forwards an optional `headers` (`AssertionError` check still first). This is the CC-1
  blocker resolution disclosed in plan D1; the change is signature-compatible and alters zero
  test cases. Without it, every header-carrying dial through the real adapter would raise
  `TypeError`, which `ModelCatalog` sanitizes into a quiet seeds listing — a test that genuinely
  reached the internet would pass green.
- Deviation of note: D1's narrowing device is `cast`, not `isinstance` — pyright rejects the
  isinstance form as an unsafe protocol overlap (the static form of CC-2's finding). The
  argument-binding `TypeError` boundary remains the only runtime guarantee, exactly as D1 specified.
