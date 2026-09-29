# ScreamingFace Studio — frontend

The Next.js (static export) UI that runs inside the Studio Tauri shell. It talks to the local
ScreamingFace Engine that the shell starts as a sidecar.

Only the Models page uses real data today. It reads `/v1/connections` and `/v1/models` from the
Engine. The other pages are still the mock, and are being moved to real data one feature at a
time (OME-1308; see `docs/plan/2026-09-29-OME-1308-studio-library-parity.md`).

## Run against a local runtime

Inside the Tauri shell, the frontend gets the Engine address from the shell's
`runtime_services` command. To work on the UI in a plain browser instead, start a runtime
yourself and point the dev server at it:

```sh
# terminal 1: the local runtime (Gateway :9105, Scoreboard :9106, Engine :9108)
cd packages/screamingface
uv sync --extra runtime
.venv/bin/screamingface --data-dir /tmp/sf-studio up --foreground

# terminal 2: the frontend
cd apps/screamingface-studio/frontend
npm ci
npm run dev   # http://localhost:3000
```

The dev server calls `http://127.0.0.1:9108` by default. To use another address, set
`NEXT_PUBLIC_SCREAMINGFACE_ENGINE_URL`. The Engine grants CORS to `http://localhost:3000` and the
Tauri origins.

## Checks

```sh
npm run lint
npm run typecheck
npm test               # Vitest + Testing Library
npm test -- --coverage # 80% threshold on the un-mocked code
npm run build          # static export to out/
```

Studio has no CI workflow yet, so run these before opening a PR.
