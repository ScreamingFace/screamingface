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

- See `docs/plan/2026-09-29-studio-models-unmock.md`, tasks T1–T10.

## Test plan

- See the plan. Each task is RED first, except T8 (see Deviations).

## Acceptance

- In the running app against the real runtime:
  - an API-key provider connects and lists its real models;
  - an OAuth provider signs in;
  - a starred model is usable in a new ensemble.
- No mock data remains in `model-store.ts`.

## Outcome

**Actual files** (all under `apps/screamingface-studio/`):
- `frontend/`
  - `package.json`, `package-lock.json`, `tsconfig.json`, `vitest.config.ts`, `vitest.setup.ts`, `README.md`
  - `src/lib/engine/{client,errors,types,oauth,index}.ts`, plus tests
  - `src/lib/{runtime,tauri,provider-presentation,model-store}.ts`, plus tests
  - `src/app/(studio)/models/page.tsx`, plus `page.test.tsx`
  - `src/app/(studio)/ensembles/{page,new/page}.tsx`, `src/app/(studio)/leaderboard/page.tsx`, `src/components/app-sidebar.tsx`
- `src-tauri/`
  - `src/{runtime_process,commands,lib}.rs`, `Cargo.toml`, `Cargo.lock`, `capabilities/default.json`

**Commits:**
- `3ce00c9b` docs(studio): spec, plan and library parity matrix
- `9df60c17` feat(studio): Engine client, runtime address command and test harness
- `f1f80d02` feat(studio): Models page reads connections and models from the local Engine
- plus the close-out commit (README + this ledger)

**Gates** (run locally; Studio has no CI):
- `npm run lint`: clean.
- `npm run typecheck`: clean.
- `npm test -- --coverage`: 78 passed. Coverage is 91.8% lines and 86.9% branches, against an 80% threshold.
- `npm run build`: the static export succeeds (11 routes).
- `cargo test --lib`: 4 passed.
- `cargo clippy --all-targets`: 1 warning, which predates this unit (`needless_return` in `executable_path`). None are new.

**Manual end to end** (`next dev` against the runtime run from source, in Chrome):
- The 7 real providers load, grouped as specified.
- A bad OpenRouter key shows "the provider connection was rejected" inline, and the field clears.
- Codex OAuth opens `auth.openai.com`, shows "Waiting for sign-in…", and Cancel returns the Engine to `not_connected`.
- The Codex models (5) show as a preview with starring disabled.
- With the runtime stopped, the page shows the unreachable state. Retry recovers once the runtime is back.
- A `?recipe=` import with real ids loads both models into the composer, and the url4 preview shows the real ids.

**Not verified yet.** These need the owner's own credentials, or the Tauri shell window:
- a successful OpenRouter key connect;
- completing Codex and Anthropic OAuth;
- starring, then composing from Starred;
- `tauri dev` (the `runtime_services` command and the opener plugin inside the webview).

**Deviations:**
- The Tauri JS APIs go through the `window.__TAURI__` global (the existing Studio idiom), not the
  npm `@tauri-apps/*` packages. The opener is called as `plugin:opener|open_url`.
- T8: the page tests were written after the page. As a check, two deliberate breaks to the page
  (enabling the switch, keeping the key after a failed connect) were each caught by a test.
- `rustfmt --check` fails on the existing crate: its 2-space style has no `rustfmt.toml`. The
  crate was not reformatted.
- The fusions-list hint counts a provider as usable when it is connected *and* has models,
  rather than falling back to the library.
- On OAuth expiry, the flow also calls `DELETE` to clear the pending row. The SDK only raises.
- The composer's load guard is keyed on ensemble id + recipe, so that a catalog refresh can't
  reset the editor.
- Known cosmetic issue: while the catalog loads, a `?recipe=` import first shows the default
  fusion for a moment.
- Seen during verification and not fixed: `runtime/uv.lock` is stale (`No module named
  'opentelemetry'`). It is to be filed as a bug.
