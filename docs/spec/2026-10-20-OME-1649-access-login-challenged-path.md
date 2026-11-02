---
title: Send the Cloudflare Access login back to the challenged path
status: proposed
created: 2026-10-20
ticket: OME-1649
branch: OME-1649-access-login-challenged-path
related:
  - packages/screamingface/src/screamingface/_access/contract.py (_access_authorization_url)
  - packages/screamingface/src/screamingface/_access/auth.py (sync_auth_flow, async_auth_flow)
  - docs/adr/0001-keep-caller-authentication-origin-scoped.md
  - docs/spec/2026-10-18-fix-public-score-read-access-gate.md (OME-1650, live probes)
  - apps/scoreboard/DEPLOYMENT.md (path-scoped production Access application)
---

# Send the Cloudflare Access login back to the challenged path

## 1. Problem

`sf.leaderboards.submit()` cannot publish to `https://leaderboard.screamingface.ai`.

Since 2026-10-07, staging and production protect the leaderboard with a separate Cloudflare
Access application. That application covers only `/v1/scores` and its subpaths, for all methods.
`/` and the read routes are public. Live probes (OME-1649 thread, 2026-10-18):

| Request | Result |
|---|---|
| `HEAD /` | 200 |
| `GET /v1/benchmarks` | 200 |
| `POST /v1/scores` | 302, `kid=f201368867767087...`, `redirect_url=/v1/scores` |
| `GET /v1/scores/x` | 302, same `kid` |

The SDK handles the 302 correctly up to the browser step. `_access_authorization_url` then sets
`redirect_url` to the origin root. After the user logs in, Cloudflare sends the browser to `/`.
Access does not run on `/`, so the edge does not put the application token in the transfer
store. The browser shows the public dashboard, and the SDK polls
`login.cloudflareaccess.org/transfer/<key>` until `access_login_timeout` (300 s).

`cloudflared access login https://leaderboard.screamingface.ai/v1/scores` works because it puts
the full application URL, path included, in `redirect_url`.

## 2. Decision context

The infra owner keeps two Access applications in staging and production (OME-1649 thread,
2026-10-20). One application would let every Engine user write scores, and a separate
application lets more people submit later without Engine access. Dev keeps one shared
application. The SDK must therefore work with an application that covers only some paths.

## 3. Requirements

R1. After a reactive challenge, the browser login must redirect to the path of the challenged
request, on the configured origin's scheme and host.

R2. The redirect must not copy the challenged request's query string. Only the transfer
parameters (`token`, `aud`, `send_org_token`, `edge_token_transfer`) are in the redirect query,
as today.

R3. The path is sent as it was encoded on the wire. The SDK does not decode it and encode it
again.

R4. An explicit `login()` keeps today's redirect (the origin, with its path if any). The Engine
application covers its whole host, so `/` stays correct there.

R5. Nothing else changes: token reuse rules by audience, replay-safety, HTTPS-only adoption, and
the in-memory token store.

R6. ADR 0001 must describe the hosted deployment correctly: dev shares one application; staging
and production use a separate leaderboard application on `/v1/scores`. The decision itself
(reuse a credential only for a matching audience) does not change.

## 4. Design

- `_access_authorization_url(origin, audience, public_key, *, redirect_path=None)`. When
  `redirect_path` is given, it replaces the origin path in `redirect_url`. The CLI endpoint stays
  `/cdn-cgi/access/cli` on the origin host.
- `sync_auth_flow` and `async_auth_flow` take the path from `request.url.raw_path`, without the
  part from `?` on. They pass it through `_authenticate_after_redirect` and
  `_login_after_challenge` to `_interactive_login`.
- Why the request path and not the `redirect_url` in Cloudflare's `Location` header:
  - Access just challenged that exact path for this audience, so it is inside the application.
  - Access rules apply to all methods, so the browser's GET to that path runs through the same
    application.
  - The SDK does not depend on the format of Cloudflare's login URL. Today it reads only `kid`
    or `cf-access-aud`.
- Concurrent challenges for one audience share one login (`_begin_login`). The first owner's
  path is used. Any challenged path of that audience is inside the application, so this is
  correct.

## 5. Out of scope

- RC-2: `login()` and `access_required()` still discover Access with `HEAD /`. A scoreboard
  login before a long run (`sf.leaderboards.login()` that checks `/v1/scores`) is a possible
  follow-up.
- A disk token cache. Each Python process still needs one browser login for each audience.
- The browser page after login. It shows what the origin returns for `GET <challenged path>`.

## 6. Verification

- Unit tests with mock transports for R1–R5 (sync and async).
- Live: one submit on staging, then one on production, with a human browser login. The result
  goes on OME-1649.
