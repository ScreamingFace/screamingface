# aigateway-ui

Admin console for gateway accounts and the provider API keys attached to them.

> **Status: skeleton.** This is the registered, CI-gated shell (`OME-707`). The accounts table,
> credential forms and BFF client land in `OME-708`.

## What it is for

`OME-684` made Cloudflare Access the identity source for aigateway: the edge authenticates the
caller, Envoy re-verifies the assertion against Cloudflare's JWKS and injects `X-User-Email`, and
aigateway get-or-creates an `Account` keyed on that email. Nothing then provisions credentials for
that account, so a new caller authenticates successfully and immediately gets
`404 profile_not_found`.

This console is the operator-managed answer: an allowlisted admin creates accounts and attaches
**static provider API keys** to them, so a caller's first request finds a profile. There is no
OAuth in this app.

## How access works

```
Cloudflare Access (OTP) → cloudflared tunnel → Envoy (verifies JWKS, injects X-User-Email)
    │
    ├─→ aigateway-ui  ── reads the header server-side, re-asserts it ──┐
    │                                                                  │
    └──────────────────────── aigateway /v1/admin/*  ◀─────────────────┘
```

Two properties hold this together, and neither is optional:

- **The browser never reaches the admin API.** Every call is a server action or a route handler
  (`output: "standalone"`). That is why this app is not a static export like
  `apps/screamingface-studio/frontend`.
- **The UI holds no allowlist.** `AIGATEWAY_ADMIN_EMAILS` lives in aigateway. This app renders
  whatever the API returns — a 403 becomes the not-an-admin page, not a local decision.

aigateway checks the **TCP peer** against `AIGW_ALLOWED_NETWORKS` before it reads the identity
header, so this app's pod address must fall inside a declared network. The chart default (private
ranges + CGNAT) already admits an in-cluster pod.

## Develop

```bash
nvm use          # 22, pinned in .nvmrc
npm ci
AIGATEWAY_ADMIN_BASE_URL=http://localhost:9105 npm run dev
curl -sf http://localhost:9107/healthz
```

## Gates

```bash
uv run .claude/scripts/run_gates.py aigateway-ui
```

Runs `npm ci` → `npm run lint` → `npm run lint:css` → `npm run typecheck` → `npm run build` →
`npm run test:ci`, covering **both** jobs of `.github/workflows/aigateway-ui-tests.yml` — the
`test` job and the separate `Build the app` job.

`npm run build` earns its place: `tsc --noEmit` type-checks but never exercises Turbopack module
resolution, static generation, or the `output: "standalone"` bundle the Dockerfile ships, so a
build-only break passes every other gate and first appears in CI or on a release tag. It runs
before `test:ci` because it is ~5s against ~60s and the runner stops at the first red gate.

`npm ci` rather than `npm install` is deliberate: it installs from the lockfile and fails when
`package.json` disagrees, so lockfile drift cannot pass unnoticed.

## Design system

This app wears the **ScreamingFace Design System v2**, vendored from
[`brand.screamingface.ai`](https://brand.screamingface.ai) into `src/brand/tokens/`; see
`src/brand/README.md` for the version string and the one documented divergence. (It previously
wore the OpenMined brand — an owner decision, reversed by an owner decision in OME-716.)

**It is the `app` register, which is the default.** v2 ships two: `[data-brand="marketing"]` swaps
the accent family to gold, everything else takes **blue**. So blue carries every interaction, green
marks a healthy account, red marks destructive actions, and gold appears **nowhere** — gold is
"rationed to the win", and an admin console has no win. `src/app/design-system.test.ts` asserts
that, along with the no-serif / no-radius / no-shadow / no-gradient anti-rules.

Literal palette values live only in `src/brand/tokens/tokens.css`. Everywhere else references a
token via `var(--…)`, enforced by `npm run lint:css` — raw hex, named colors and `rgb()`/`hsl()`
literals on color properties all fail the build.

## Environment

| Variable | Purpose |
|---|---|
| `AIGATEWAY_ADMIN_BASE_URL` | Where aigateway's admin API lives, e.g. `http://aigateway:9105`. Server-side only. |
| `LOG_LEVEL` | `debug` \| `info` (default) \| `warn` \| `error`. Every failed admin call writes one JSON line (`msg: "bff_admin_error"`: method, path, kind, status, `x-request-id`) — refusals at `warn`, an unservable console at `error`. Never the upstream body. |

## Ports

9105 aigateway · 9106 scoreboard · **9107 aigateway-ui** · 9108 url4-cloud
