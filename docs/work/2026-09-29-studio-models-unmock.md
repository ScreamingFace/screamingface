---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: repo   # screamingface-studio has no .claude/sdlc.local.md stack yet
status: in_progress
started: 2026-09-29
finished:
---

# studio-models-unmock — Studio Models page on the local Engine

## Intent

First feature un-mocked under OME-1308 (E18 · A local app). The Models page now shows the
local Engine's connections (`/v1/connections`) and models (`/v1/models`) instead of the
hard-coded provider and model lists. API keys and OAuth sign-in are handled for real.
Branched from `OME-1403-engine-cors-studio` (PR #1120), which lets the webview reach the
Engine. Spec: `docs/spec/2026-09-29-studio-models-unmock.md`.

## Planned changes

- See the spec, §4; the plan will list exact files.

## Test plan

- See the spec, §5.

## Acceptance

- In `tauri dev` against the real sidecar: an API-key provider connects and lists its real
  models; an OAuth provider signs in; a starred model is usable in a new ensemble; no mock
  data remains in `model-store.ts`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
