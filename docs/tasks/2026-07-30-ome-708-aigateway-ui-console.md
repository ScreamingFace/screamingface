---
id: OME-708
linear_url: https://linear.app/openmined/issue/OME-708/scaffold-appsaigateway-ui-nextjs-admin-console-over-the-bff
status: done
type: task
priority: P2
labels: [autonomous, agentic]
created: 2026-07-30
closed: 2026-08-31
---

# OME-708 — Scaffold `apps/aigateway-ui`: Next.js admin console over the BFF

The frontend half of `OME-705`. Blocked by `OME-706` (the API it consumes) and `OME-707` (the CI
and release lane it lands into).

> **Missing landing label.** This issue should carry `app › aigateway-ui`, which does not exist
> yet. Agents cannot create labels. Owner action: create it under parent `app`, apply it to
> `OME-708`, and register its UUID in `.claude/task-board.local.md` in the same change. Filed with
> no landing leaf rather than a wrong one, so the gap stays visible.

## Stack

Next.js 16 App Router · React 19 · TypeScript `strict` · npm · Tailwind v4 · vitest + Testing
Library. Port **9107**. Mirrors `apps/screamingface-studio/frontend/` for toolchain shape, but
`output: "standalone"`, not `"export"` — the BFF needs a server.

## Trust path

The browser never reaches the admin API. Cloudflare Access authenticates, Envoy injects
`X-User-Email`, the Next.js server reads it and re-asserts it toward aigateway. `peer_in_networks`
checks the **TCP peer**, so the UI pod's IP must fall inside `AIGW_ALLOWED_NETWORKS` — the chart
default (private ranges + CGNAT) already admits an in-cluster pod. Both charts ship
`ingress.enabled=false`; the UI is reachable only through the mesh gateway.

## Key files

- `src/lib/aigateway/client.ts` — `import "server-only"`; base URL from `AIGATEWAY_ADMIN_BASE_URL`;
  reads `X-User-Email` via `headers()`; typed against types generated from aigateway's OpenAPI
- `src/lib/auth.ts` — `requireAdmin()`; on 403 render the not-an-admin page. No allowlist copy
- `src/app/page.tsx` — accounts table, search, create-account form
- `src/app/accounts/[id]/page.tsx` — account detail, active toggle, profiles table
- `src/app/accounts/[id]/credentials/new/page.tsx` — provider · profile name · API key
  (`type="password"`, write-only) · optional `ProfileDefaults`
- `src/app/healthz/route.ts` — for the container `HEALTHCHECK`
- Mutations are server actions + `revalidatePath`. No client-side fetching to aigateway

## Design law

The `screamingface-design` skill is binding and **explicitly overrides shadcn/Tailwind defaults**:
radius `0`, hairline borders, no shadows/gradients/blur, no purple, IBM Plex Sans for prose and IBM
Plex Mono for data/labels/tables, EB Garamond for `h1` only, semantic tokens never raw hex. Light
and dark are co-equal. An admin console is dense-table work — use the `table` + `.num` + `.btn`
recipes in `reference/style.css`; do not ship the stock shadcn look.

## Error surfaces

- **503** → allowlist unset, or aigateway is in `jwt` mode. Show the configuration problem
- **403** → not an admin. Dedicated page, no retry affordance
- **503 `profile_index_conflict`** → CAS exhaustion on a concurrent profile write. Surface as retry

## Acceptance

`npm run lint && npx tsc --noEmit && npm test` green. Then, running both services: create an
account, attach an OpenAI API key, confirm the key is never rendered back, and confirm
`GET /v1/auth/profiles` as that account now returns the profile. Verify light and dark.
