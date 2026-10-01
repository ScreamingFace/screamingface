---
status: approved 2026-09-29
ticket: OME-1403 (leaf under epic OME-1308)
date: 2026-09-29
---

# Engine CORS for the Studio frontend

## 1. Problem

The Studio frontend (`apps/screamingface-studio/frontend`, Next.js static export in a Tauri 2
webview) uses mock data today. To replace the mocks it must call the Engine's REST surface
from the webview. The webview origin differs from the Engine origin, and the Engine sends no
CORS headers, so the browser blocks every such call.

## 2. Decision

Add Starlette's `CORSMiddleware` to the Engine app in `create_app`. Both entrypoints — the
deployed `create_app_from_env` and `serve --local` — go through `create_app`, so both get it.

| Setting | Value | Why |
|---|---|---|
| `allow_origins` | `Settings.cors_allowed_origins` | configurable per deployment |
| default origins | `http://localhost:3000`, `tauri://localhost`, `http://tauri.localhost`, `https://tauri.localhost` | Studio dev server (`devUrl`); Tauri 2 packaged origin on macOS/Linux, Windows, Windows with `useHttpsScheme` |
| `allow_credentials` | `False` | Engine auth is header-borne (`Authorization` + secondary header), never cookies; wildcard headers/methods stay safe without credentials |
| `allow_methods` | `*` | — |
| `allow_headers` | `*` | carries `Authorization` and the secondary credential header |

Env var: `URL4_CLOUD_CORS_ALLOWED_ORIGINS` (JSON list, pydantic-settings default parsing),
replacing the defaults entirely. An empty list grants no origin.

## 3. Non-goals

- No origins for any other product (no syft-space/syft-hub entries, no regex).
- WebSocket endpoints: CORS middleware does not apply to WS upgrades; unchanged.
- Helm chart values: the env var can be set when a hosted Studio origin exists; not now.

## 4. Risks

- A permissive default on a hosted Engine: the defaults are loopback/Tauri origins only,
  which a remote website cannot claim. Without credentials, a grant exposes nothing a
  holder of the bearer token could not already fetch.
