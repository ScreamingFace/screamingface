---
status: approved 2026-09-29
ticket: unfiled (leaf under epic OME-1308)
spec: docs/spec/2026-09-29-studio-models-unmock.md (approved 2026-09-29)
base: origin/OME-1403-engine-cors-studio (PR #1120)
---

# Plan — Studio Models page on the local Engine

All paths below are relative to `apps/screamingface-studio/`. Each task runs RED → GREEN →
refactor and ends with the frontend gates passing (§Gates).

## Checked against the live runtime (2026-09-29)

The runtime was run from source (`packages/screamingface` with the `runtime` extra) against
this branch.

| Check | Result |
|---|---|
| `GET /v1/connections` | 7 rows: `anthropic` (api_key, oauth), `antigravity` (oauth), `codex` (oauth), `gemini-cli` (api_key, oauth), `huggingface` (api_key), `openai` (api_key), `openrouter` (api_key) |
| `GET /v1/models` | 109 models: `anthropic` 10, `antigravity` 1, `codex` 5, `gemini-cli` 4, `huggingface` 24, `openrouter` 65. In every model, `owned_by` equals the id's prefix, which settles spec §7. |
| Models while not connected | The catalog lists all declared models whatever the connection status. |
| `openai` | Has a connection row but **0 models**, because the Engine's built-in world has no OpenAI seed. |
| OAuth start | Every redirect is on localhost. `anthropic` → `:9105/callback`, `codex` → `:1455/auth/callback`, `gemini-cli` and `antigravity` → `:9105/oauth2callback`. `expires_in` is 600. The status becomes `pending`, and `DELETE` returns it to `not_connected`. This confirms D7. |
| Bad key | `PUT` gives 401 `application/problem+json` with `detail: "the provider connection was rejected"`. The CORS header is present. |
| CORS | The preflight from `tauri://localhost` is granted (PR #1120). |
| `X-Profile` | Rejected with 400. The client must never send it. |

**UI decisions that follow from these results** (they refine spec §4.3 and §4.4; they are not
new scope):

- **U1.** A provider's model list is shown **even when it is not connected**, as a read-only
  preview. Star is disabled until the provider is `connected`, with the tooltip "Connect to use".
  An unconnected model would only fail later, inside a run.
- **U2.** A connected provider with no models (today, `openai`) shows "This Engine lists no
  models for OpenAI yet." instead of an empty list.
- **U3.** `antigravity` stays in the presentation table under "Local & Sessions".

## Tasks

### T1 — Test harness

- `frontend/package.json`:
  - devDeps `vitest`, `@vitejs/plugin-react`, `jsdom`, `@testing-library/react`,
    `@testing-library/dom`, `@testing-library/jest-dom`, `@testing-library/user-event`, pinned to
    the versions `apps/aigateway-ui` uses;
  - scripts `test` (`vitest run`) and `typecheck` (`tsc --noEmit`).
- `frontend/vitest.config.ts` and `frontend/vitest.setup.ts`, copied from `aigateway-ui`,
  including the `MemoryStorage` shim. The coverage threshold is 80%, scoped to `src/lib/**` and
  `src/app/(studio)/models/**`. The rest of the mock app is not in scope yet.
- `frontend/tsconfig.json`: add `vitest/globals` types.
- RED check: a placeholder test fails, then the harness runs.

### T2 — Engine client: `frontend/src/lib/engine/`

- `types.ts`: `Connection`, `ConnectionStatus`, `AuthMethod`, `OAuthAuthorization`,
  `EngineModel` (`id`, `owned_by`, `supported_parameters`, `supported_tools`), `ProblemDetails`.
- `errors.ts`: `EngineError {kind, status?, detail}`. The kind is one of `unreachable` (fetch
  threw), `invalid` (400/422), `unauthenticated` (401/403), `not_found` (404), `unavailable`
  (502/503/504) or `unknown`. `detail` comes from problem+json, otherwise a generic string.
- `client.ts`: `createEngineClient(baseUrl, fetchImpl = fetch)` with `listConnections`,
  `connectApiKey(provider, apiKey)`, `startOAuth(provider)`, `disconnect(provider)`,
  `listModels()` and `health()`.
  - Provider ids go through `encodeURIComponent`.
  - `cache: "no-store"` on connection calls.
  - The client never adds an `X-Profile` header.
- Tests (`client.test.ts`):
  - one happy path per call, checking method, URL, body and headers;
  - problem+json mapped to each error kind;
  - a non-JSON error body;
  - a fetch rejection reported as `unreachable`;
  - **the API key never appears** in any `EngineError` message or `detail`, including when the
    server echoes it back;
  - no `X-Profile` header on any request.

### T3 — Finding the Engine

**Rust side** (`src-tauri/src/runtime_process.rs`, `state.rs`, `commands.rs`, `lib.rs`):

- `parse_ready_line(line) -> Option<RuntimeServices>` parses the JSON after `READY_PREFIX`.
  `RuntimeServices {engine: String}` is serde-deserialized, and extra fields are ignored.
- The stdout reader thread sends `StartupEvent::Ready(services)`. On readiness,
  `Mutex<Option<RuntimeServices>>` is stored in managed state. The hard-coded `9108` log line
  logs the parsed URL instead.
- The new `#[tauri::command] runtime_services` returns `Option<RuntimeServices>`. It is
  registered in `lib.rs`.
- `#[cfg(test)]` tests: a valid line, a line with no prefix, malformed JSON, a missing `engine`
  field, and the timestamp prefix before the marker (the real log format).

**Frontend** (`frontend/src/lib/runtime.ts`):

- `getEngineUrl()`: inside Tauri it calls `invoke("runtime_services")`. Null means
  `EngineError{kind:"unreachable"}` ("runtime starting"). Outside Tauri it uses
  `process.env.NEXT_PUBLIC_SCREAMINGFACE_ENGINE_URL ?? "http://127.0.0.1:9108"`.
- This is the single seam for the D5 follow-up.
- Tests: Tauri present or absent (mock `@tauri-apps/api/core` `invoke`), the env override, and
  the null result.

### T4 — Presentation table: `frontend/src/lib/provider-presentation.ts`

- `providerPresentation(id) -> {group, description, color}`, with the table from spec §4.3,
  including `antigravity` (U3). The colors are re-keyed from the old `PROVIDER_COLORS`.
- Unknown ids get `{group: "Other", description: "", color: FALLBACK}`.
- `GROUP_ORDER` is "Local & Sessions", "Providers", "Hubs", "Other".
- Tests: each known id maps to its group; an unknown id falls back.

### T5 — Store rewrite: `frontend/src/lib/model-store.ts`

The whole file is replaced. The mock data, `ALL_MODELS`, `discoverProvider`, `patchProvider`
and `PROVIDER_COLORS` are deleted.

- **Server slice** (never persisted): `connections`, `models`, and a `load` status of
  `idle | loading | ready | error` plus `error?: EngineError`.
  - `refresh()` fetches connections and models in parallel.
  - `connectApiKey`, `startOAuth`, `cancelOAuth` and `disconnect` each call the client and then
    `refresh()`.
  - The API key is passed straight through and never stored in the store.
- **`selectProviders(state) -> ProviderView[]`** (pure; exported for tests). Each view is
  `{id, name, group, description, color, authMethods, status, accountLabel, connected, keyless,
  models: SavedModel[]}`.
  - The views are the union of the connection rows and the `owned_by` values with no connection
    row. Those extra ones are marked `keyless: true` and `connected: true`.
  - They are sorted by `GROUP_ORDER`, then by `display_name`.
  - The field names that `ensembles/new` already reads (`id`, `name`, `connected`, `models`) are
    kept, so the picker works unchanged.
- **Library slice** (persisted as `screamingface-models`, `version: 2`):
  - `library: SavedModel[]`, with `toggleLibraryModel` and `addLibraryModels`.
  - `migrate(v1)` returns `{library: []}`, which drops the mock ids and the old `providers`
    array.
  - `partialize` persists `library` only.
- **`toSavedModel(model, connection?)`**: `{id: model.id, name: model.id, providerId:
  owned_by, providerName: display_name ?? owned_by}`.
- Tests:
  - `selectProviders`: the grouping, the keyless owner, a connection with zero models (U2),
    `connected` true only for `status === "connected"`, and the sort order;
  - migrating v1 to v2;
  - the persisted JSON never contains `connections`, `models` or any key;
  - `refresh` error handling;
  - `connectApiKey` calls the client and then refreshes.

### T6 — OAuth flow: `frontend/src/lib/engine/oauth.ts`

- `runOAuth(client, provider, {open, intervalMs = 1000, signal})`:
  1. calls `startOAuth`;
  2. calls `open(authorize_url)`;
  3. polls `listConnections` until the provider's `status !== "pending"`, the `expires_in`
     deadline passes, or `signal` aborts;
  4. resolves with the final `Connection`, or throws `EngineError{kind:"invalid", detail:"sign-in
     expired"}`.

  On abort it calls `disconnect(provider)`, which is the Cancel.
- `open` is `@tauri-apps/plugin-opener`'s `openUrl` inside Tauri and `window.open(url, "_blank",
  "noopener")` outside.
- Tests (fake timers): `pending` → `connected`; `pending` → `error`; the expiry; abort calls
  `DELETE`; a transient `unreachable` during a poll is retried, not fatal.

### T7 — Opening the sign-in page from the Tauri shell

- Add `tauri-plugin-opener` (Rust crate) and `@tauri-apps/plugin-opener` (npm).
- Register the plugin in `lib.rs`.
- In `capabilities/default.json`, add `opener:allow-open-url`, scoped to `https://*`.
- Check that `@tauri-apps/api` is already a direct dependency; add it if not.

### T8 — The Models page: `frontend/src/app/(studio)/models/page.tsx`

- Keep the layout (Starred rail row, grouped provider rail, detail pane, compose bar) and the
  SFDS styling. Replace only the data and the controls.
- On mount it calls `refresh()`.
  - While loading, it shows a skeleton in the rail.
  - On `error.kind === "unreachable"` it shows a single empty state, "The local ScreamingFace
    runtime isn't reachable.", with a Retry button.
- `ProviderConnect` covers these cases:
  - **OAuth:** a "Sign in with <name>" button runs `runOAuth`. While it runs the button reads
    "Waiting for sign-in…" and a Cancel button (which aborts) is shown.
  - **API key:** a password field and a Connect button, with the error `detail` shown inline.
    The input clears when the call finishes, whether it succeeded or failed.
  - **Both methods:** OAuth is shown first, then "or use an API key".
  - **Keyless:** a note that the models come from the local runtime.
  - **Connected:** the `account_label` and a Disconnect button.
  - **`needs_reauth` / `error`:** a reconnect prompt.
  - **Hosted-credits switch:** stays, disabled, labelled "Coming soon" (D4).
- The model list applies U1 (a preview when not connected, star disabled) and U2 (the empty
  message).
- A starred model that is missing from the current catalog is shown as "Unavailable" in the
  Starred view.
- The "Discover Models" button is removed. The page has a Refresh icon button instead.
- Tests (Testing Library, with a mocked client module):
  - the unreachable state and Retry;
  - an API-key connect, which refreshes and shows the connected label;
  - a bad key showing the problem detail inline, with the input cleared;
  - the OAuth button showing the waiting state and Cancel calling disconnect;
  - star disabled when not connected;
  - the hosted-credits switch disabled;
  - an unknown provider rendered under "Other".

### T9 — Other code that reads the store

- `ensembles/new/page.tsx`:
  - `parseRecipe` resolves model ids against `useModelStore.getState().models` (mapped with
    `toSavedModel`) instead of `ALL_MODELS`.
  - If the catalog hasn't loaded, the page calls `refresh()` first.
  - Unknown ids are reported in the import error ("Unknown models: …") instead of being silently
    dropped.
  - The page's `providers` prop takes `ProviderView[]` from `selectProviders`.
  - `PROVIDER_COLORS[...]` becomes `providerPresentation(...).color`.
- `ensembles/page.tsx`: `hasProviderConnected` is `selectProviders(state).some(p => p.connected
  && !p.keyless)`, falling back to `library.length > 0`. It triggers `refresh()` once on mount.
  The colors come from the presentation table.
- `components/app-sidebar.tsx`: the connected count comes from `selectProviders`. The
  OpenMined store section is unchanged.
- `leaderboard/page.tsx`: its colors come from `providerPresentation`.
- The recipe builder's own tests don't exist yet. `tsc` and `next build` are the check here, and
  the manual end-to-end run covers import.

### T10 — Close out

- Ledger: the outcome, gates, and deviations.
- Frontend `README.md`: replace the create-next-app boilerplate with how to run against a local
  runtime (`screamingface up`, or `NEXT_PUBLIC_SCREAMINGFACE_ENGINE_URL`) and how to run the
  tests.

## Gates (all run locally before PR; Studio has no CI — spec §6)

```sh
cd apps/screamingface-studio/frontend
npm ci && npm run lint && npm run typecheck && npm test -- --coverage && npm run build
cd ../src-tauri && cargo fmt --check && cargo clippy -- -D warnings && cargo test
```

Manual end-to-end run: `npm run tauri dev`, or `next dev` plus a runtime started from source.
Screenshots go in the PR. Steps:

1. Start with the runtime stopped: check the unreachable state, then start the runtime and
   press Retry.
2. OpenRouter key: connect, check its 65 models are listed, then star two.
3. A bad key: check the inline error.
4. Codex OAuth: sign in in the browser, and check the page moves to connected. Also check that
   Cancel works.
5. Anthropic OAuth, the same way.
6. In a new ensemble, pick the starred models, then check the copied `url4://` recipe shows the
   real ids and re-imports cleanly.
7. Disconnect.

## Out of scope / follow-ups to file

- The D5 follow-up leaf: switching between local and hosted Engines, and Cloudflare Access
  hosted credits, which replace the disabled switch (spec §6).
- The Studio CI workflow and an SDLC card stack (spec §6).
- **Separate bug seen during verification.** `apps/screamingface-studio/runtime/uv.lock` is
  stale. `.venv/bin/screamingface up` fails with `ModuleNotFoundError: No module named
  'opentelemetry'`, raised from `aigateway/tracing.py`. The frozen sidecar build likely breaks
  the same way. It is filed as a `bug` in Triage, not fixed here.
