---
status: approved 2026-09-29
ticket: unfiled (leaf under epic OME-1308)
date: 2026-09-29
depends_on: OME-1403 (PR #1120, Engine CORS for Studio origins)
---

# Studio Models page — replace the mock with the local Engine

## 1. Problem

OME-1308 (E18 · A local app) turns the Studio mock into the application, feature by feature.
The Models page is first. Today it is all mock data:

- `frontend/src/lib/model-store.ts` hard-codes 10 providers and their model lists. "Discover"
  is a 900 ms `setTimeout`. API keys sit in component state and are never sent anywhere.
- The frontend makes no network calls, and the webview never learns the runtime's service
  addresses. `runtime_process.rs` reads the `SCREAMINGFACE_RUNTIME_READY` line and then
  discards its JSON.

The Studio sidecar already runs the Engine on `127.0.0.1:9108`, with a Studio-shaped contract
that the Python SDK uses. OME-1403 grants CORS to Studio's origins.

## 2. Decisions (confirmed with the owner, 2026-09-29)

| # | Decision |
|---|---|
| D1 | The webview calls the Engine directly with `fetch`, which works once OME-1403 grants CORS. No Rust proxy and no Tauri HTTP plugin. |
| D2 | **The Engine is the only source.** Connections come from `/v1/connections`, models from `/v1/models`. The page never calls AI Gateway, so what it lists is what a run can address. |
| D3 | This unit covers both **API keys and OAuth**. |
| D4 | The "Use OpenMined key (subsidized)" switch stays visible but **disabled**, labelled "Coming soon". Nothing in the backend supports it yet. |
| D5 | **Local Engine only for this unit.** A later unit adds a runtime-switchable Engine URL (local or hosted) and Cloudflare Access sign-in. This unit keeps that seam ready: every call gets its base URL from one resolver (§4.1), so the later setting plugs in without touching call sites. |
| D6 | **Provider grouping is a frontend presentation table**, not Engine metadata. The Engine sends no category, and deriving one from `auth_methods` misplaces `anthropic`, which has both oauth and api_key (§4.3). |
| D7 | **No deep link for OAuth.** On the local runtime the AI Gateway owns the redirect (§4.4), so Studio only polls. |

## 3. Engine contract used

| Call | Use |
|---|---|
| `GET /v1/connections` | Provider list: `provider`, `display_name`, `auth_methods`, `status`, `auth_method?`, `account_label?` |
| `PUT /v1/connections/{provider}` `{api_key}` | Connect or replace a key |
| `POST /v1/connections/{provider}/oauth` | Returns `authorize_url` and `expires_in` |
| `DELETE /v1/connections/{provider}` | Disconnect. Idempotent. |
| `GET /v1/models` | `{data:[{id, owned_by, supported_parameters, supported_tools, …}]}`, with ETag support |
| `GET /healthz` | Tells whether the runtime is reachable |

`status` is one of `not_connected | pending | connected | needs_reauth | error`. Errors come
back as problem+json. The page never sends the `X-Profile` header, because the Engine rejects
it with a 400.

## 4. Design

### 4.1 Finding the Engine (`src-tauri`)

- `runtime_process.rs` parses the JSON after `SCREAMINGFACE_RUNTIME_READY` and stores
  `services.engine` in managed state.
- A new command, `runtime_services`, returns `{engine: string} | null`. It returns null
  while the runtime is starting or after it has failed.
- On the frontend, `lib/runtime.ts` exports `getEngineUrl()`, the single seam for D5. It resolves the Engine URL:
  - inside Tauri, it calls `invoke("runtime_services")`;
  - in a plain browser (`npm run dev`), it uses `NEXT_PUBLIC_SCREAMINGFACE_ENGINE_URL`,
    falling back to `http://127.0.0.1:9108`.
- `tauri-plugin-opener` is added so the OAuth `authorize_url` opens in the system browser.
  In a plain browser the page uses `window.open` instead.

### 4.2 Engine client (`lib/engine/`)

- A thin typed client for the six calls in §3.
- Every problem+json error is mapped to an error kind: `unreachable | invalid |
  unauthenticated | not_found | unavailable | unknown`. This follows the pattern in
  `aigateway-ui/src/lib/aigateway/client.ts`.
- Error messages never include the API key, and the key is never logged or persisted.

### 4.3 State (`lib/model-store.ts`, rewritten)

**Server state.** `connections[]` and `models[]` are fetched and kept in memory only. They
are never written to localStorage. Refreshes happen on page mount, after every connect or
disconnect, and when an OAuth flow finishes.

**Providers shown in the side panel.**
- The panel lists every row from `/v1/connections`.
- A provider that owns models (`owned_by`) but has no connection row also gets a row, marked
  keyless. Ollama would be one, once the Engine lists its models (§6).
- The Engine decides **which** providers exist and how each one signs in. The frontend decides
  only **how they look**.

**Presentation table (D6).** `lib/provider-presentation.ts` replaces `PROVIDER_COLORS`. It maps
a provider id to `{group, description, color}`:

| id | group | description |
|---|---|---|
| `ollama` | Local & Sessions | Local models on your machine, no API key |
| `anthropic` | Local & Sessions | Claude subscription sign-in or API key |
| `codex` | Local & Sessions | ChatGPT / Codex subscription sign-in |
| `gemini-cli` | Local & Sessions | Google sign-in or Gemini API key |
| `openai` | Providers | GPT and o-series models |
| `huggingface` | Hubs | Serverless open-source inference |
| `openrouter` | Hubs | 300+ models behind one API key |
| `antigravity` | Local & Sessions | Antigravity sign-in |

- Any id not in the table goes in an **`Other`** group, with a neutral color and no
  description, so a provider added to the Engine still appears without a frontend change.
- `display_name` always comes from the Engine, never from the table.
- The mock's DeepMind and Perplexity entries are deleted, because no Engine provider backs
  them.

**A provider's models.** A provider's models are the entries in `models` where
`owned_by === provider`. "Discover Models" becomes a refresh of the catalog.

**Library (starred models).**
- The library stays in localStorage as a per-user convenience; no backend owns it yet.
- Each entry is keyed by the real model id (for example `anthropic/claude-sonnet-4-6`).
  `SavedModel` becomes `{id, name: id, providerId: owned_by, providerName: display_name}`,
  so `recipe.ts`, which builds url4 paths from `name`, works unchanged.
- Persist `version: 2`. The migration drops all v1 entries, since mock ids such as `ol-1`
  have no real equivalent. It also drops each provider's `apiKey`, `connected` and `models`
  fields.
- A starred model that is missing from the current catalog stays in the library, shown as
  "unavailable".

**Colors.** The other readers of the old color table (`leaderboard/page.tsx`, `ensembles/page.tsx`) read
`providerPresentation(id).color` instead.

### 4.4 Connect flows (models page UI)

| Auth method | Flow |
|---|---|
| `api_key` | Password field, then Connect, which sends `PUT`. On success the page refreshes connections and models. On failure it shows the problem `detail` inline. |
| `oauth` | Sign in, which sends `POST …/oauth` and opens `authorize_url`. The page then polls `GET /v1/connections` every 1 s until the provider leaves `pending` or `expires_in` runs out. A Cancel button calls `DELETE`. |
| both | Both controls are shown, with OAuth first. |
| keyless | No control. The row shows that the models come from the local runtime. |

- **Why no deep link (D7).** With no `public_url` set, the local Gateway chooses the redirect
  itself (`apps/aigateway/src/aigateway/routes/auth.py:514-527`):
  - Codex uses a temporary loopback server the Gateway opens on port 1455 or 1457.
  - Claude and Gemini use the Gateway's own `http://localhost:9105/callback` and
    `/oauth2callback`.

  In both cases the Gateway exchanges the code and serves "Authentication complete. You may close
  this window." A deep link would only bring Studio back to the front; that is out of scope.
- A connected provider shows its `account_label` (if any) and a Disconnect button.
  `needs_reauth` and `error` show a reconnect prompt.
- When the runtime can't be reached, the page shows one empty state saying the local runtime
  is not running, with a Retry button. The rail does not fall back to the old mock data.

### 4.5 Other code that reads the store (same app, same unit)

- `ensembles/new/page.tsx`: importing a `url4://` recipe resolves models by real id through
  the live catalog, not `ALL_MODELS`. `ALL_MODELS` is deleted.
- `ensembles/page.tsx` and `components/app-sidebar.tsx`: "has a provider connected" and the
  connected count come from connections where `status === "connected"`, plus keyless
  providers that have models.
- Saved ensembles in localStorage keep their embedded `SavedModel`s. An entry whose id isn't
  in the catalog shows as unavailable instead of crashing.
- `openmined-store.ts` is unchanged. It belongs to a later feature; only the models-page
  switch is affected (D4).

## 5. Testing

- The frontend has no test harness today. This unit adds Vitest, with jsdom and Testing
  Library, copied from `apps/aigateway-ui` (`vitest.config.ts` and `vitest.setup.ts`), and
  `test` / `typecheck` npm scripts.
- **Engine client:** tests with a mocked `fetch` covering the happy path for each call, the
  mapping from problem+json to error kinds, a network failure reported as `unreachable`, and
  a check that the key never appears in any thrown message.
- **Presentation:** the known ids map to their groups; an unknown id falls into `Other` with
  the neutral color.
- **Store:** building the provider list (connections plus keyless owners, and the grouping),
  the v1-to-v2 migration, and the rule that persisted state never contains keys or server
  data.
- **OAuth poll:** stops on `connected`, `error` or expiry, and Cancel calls `DELETE`. Tests
  use fake timers.
- **Page (Testing Library):** the unreachable empty state; API-key connect then refresh; the
  OpenMined switch rendered disabled.
- **Rust:** a unit test that parses the readiness line.
- **Manual end to end:** `tauri dev` against the real sidecar. Connect an OpenRouter key,
  check its models appear, star one, and use it in a new ensemble. Sign in to Codex with
  OAuth. Screenshots go in the PR.

## 6. Non-goals

- **A switchable or hosted Engine (D5).** A later unit adds the Engine URL setting, the
  hosted read-only rules from OME-883/OME-958 (providers "Available via ScreamingFace", no
  mutation controls), and Cloudflare Access sign-in. Sign-in is expected to run on the Rust
  side, because the transfer poll to `login.cloudflareaccess.org` and Access's handling of
  preflight requests both work against a webview `fetch`.
- **Follow-up leaf (parity).** The library already does both hosted-Engine tasks:
  `sf.configure(engine_url=...)`, and hosted credits through a Cloudflare Access login, as
  shown in `examples/02_connection.ipynb`. A separate leaf under OME-1308 adds an Engine
  switch between Local (your keys) and Hosted (OpenMined credits). That switch replaces the
  disabled "Use OpenMined key" control from D4.
- **Ollama.** The library does not support it today, so parity (OME-1308) does not require it.
  No example notebook or doc uses it, and the Engine's built-in model world
  (`world/models/builtins.py`) has no Ollama seed; a deployment can only add Ollama routes by
  hand in `url4.toml`. Studio shows Ollama automatically once the Engine lists its models, through
  the keyless-owner row in §4.3.
- A backend for the subsidized OpenMined key (D4). An `improvement-ideas` item can be filed.
- A backend store for the library.
- Studio CI and an SDLC card stack. Studio has no workflow and no `.claude/sdlc.local.md`
  entry; that gap is flagged as a follow-up, not fixed here.
- Other pages, which are later units under OME-1308.

## 7. Risks

- **OME-1403 not merged.** This branch is based on it. If that PR changes, rebase.
- **OAuth callback ports.** Codex needs port 1455 or 1457 free. If both are taken, the OAuth
  start fails, and the page shows the problem `detail`. The manual end-to-end run checks all
  three OAuth providers.
- **Presentation table drift.** A new Engine provider shows under `Other` until someone adds
  it to the table. That is acceptable, because nothing breaks.
- **`owned_by` vs provider id.** Grouping assumes `owned_by` equals the connection
  `provider`. This is verified against the live sidecar before the plan is written. If they
  differ, the page groups by the id's prefix before `/`.
