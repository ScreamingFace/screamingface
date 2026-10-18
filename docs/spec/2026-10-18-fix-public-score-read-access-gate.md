---
title: Public score read outside the Cloudflare Access path
status: proposed, pending owner approval
created: 2026-10-18
ticket: unfiled
branch: fix-public-score-read-access-gate
related:
  - apps/scoreboard/src/scoreboard/routes/scores.py (get_score)
  - apps/scoreboard/portal/spec.js (renderRunLink)
  - OME-894 (private boards: one 404 for unknown and refused ids, private cache headers)
  - OME-1307 (reproduction count on the score detail)
---

# Public score read outside the Cloudflare Access path

## 1. Problem

Production Cloudflare Access protects `leaderboard.screamingface.ai` with one application that
is scoped to the path `/v1/scores`. That application covers `/v1/scores` and every subpath.
Cloudflare Access cannot scope by HTTP method.

Live probes on 2026-10-18 (anonymous `curl`, no cookies):

| Request | Result |
|---|---|
| `GET /` | 200 |
| `GET /v1/benchmarks` | 200 |
| `GET /v1/leaderboard/x`, `GET /v1/leaderboard/x/y/history` | 404 from the app (not gated) |
| `GET /v1/scores/x`, `/v1/scores/`, `/V1/scores/x`, `/v1//scores/x` | 302 to `openmined.cloudflareaccess.com` |
| `GET /v1/scoresx`, `/v1/scores-public/x` | 404 from the app (not gated; Access matches whole path segments) |
| `GET /v1/public/scores/x` | 404 from the app (not gated) |

`GET /v1/scores/{score_id}` takes `ReadIdentity` (optional). It is designed as a public read.
The portal spec page (`portal/spec.js`, `renderRunLink`) calls it for the newest run of a spec.
An anonymous visitor gets a cross-origin 302. The fetch fails. The page then hides the
"copy url4" button, the paper link, the "Metadata edited" line and the "Reproduced N times"
line. A reproducible url4 is the core promise of the leaderboard, so this is a product bug.

## 2. Constraints

- C1. The fix is code only, in this repository. We cannot change the Cloudflare dashboard.
- C2. Private boards must not regress. A private score, an unknown id and a refused id must give
  the same 404 body and the same `Cache-Control` and `Vary` headers (OME-894).
- C3. The change is additive. No existing route, field or status code changes.
- C4. The writes and the owner-only reads under `/v1/scores` stay behind Cloudflare Access.

## 3. Decision

Add one anonymous, read-only alias of the score detail:

`GET /v1/public/scores/{score_id}`

- It is outside the `/v1/scores` path segment, so Access does not gate it (probe above).
- It returns the same `ScoreSchema` body as `GET /v1/scores/{score_id}`, including
  `reproduction_count` and `last_reproduced_at`.
- It NEVER reads the caller's identity. It always decides as an anonymous caller. A score on a
  private board (or a board that cannot be found) is the same 404 as an unknown id, with
  `PRIVATE_CACHE_HEADERS`, for every caller, the owner too.
- It shares one implementation with `GET /v1/scores/{score_id}`. The access rules are not copied.
- The portal spec page calls the alias instead of `/v1/scores/{id}`.
- `GET /v1/scores/{score_id}` stays as it is. Owners of private-board scores use it with identity.

### 3.1 Why the alias ignores identity

The alias sits on a path that Access does not cover. On such a path no step verifies who the
caller is. If the alias read `X-User-Email`, its safety would depend on the mesh removing a
client-supplied header on an ungated path. That is an infra fact we cannot prove from this
repository. When the alias ignores identity, a private score can never leave through it, in
every auth mode and every mesh setup. Production runs `auth_mode: disabled` today
(`DEPLOYMENT.md`), where `read_identity` returns `None` already, so for production the alias
answers exactly what `GET /v1/scores/{id}` answers to an anonymous caller.

### 3.2 SDK

No SDK change. `Scoreboard.get_score` keeps `GET /v1/scores/{id}`. It is the only path that
serves a private-board score to its verified owner, and the SDK already recovers from the 302
with a browser login (`packages/screamingface/tests/test_authentication.py`). A later unit can
let anonymous SDK reads try the public alias first. That is out of scope here.

## 4. Options considered

| Option | Private-board safety | Additive | SDK impact | Size | Cloudflare change | Verdict |
|---|---|---|---|---|---|---|
| A. Public alias `/v1/public/scores/{id}` that ignores identity, one shared implementation | Safe in every auth mode; reuses the OME-894 refusal | Yes, one new route | None | Small: one route, one extracted helper, one portal line | None | **Chosen** |
| B. Add url4, paper, metadata and reproduction fields to every `HistorySubmission` row | Safe (history already gates) | Yes, but `extra=forbid` schema grows | None | Large: per-row reproduction aggregate (new batch store query), second projection of the same fields | None | Rejected: duplicates the `ScoreSchema` projection (not DRY), N rows of url4 per call, reverses the documented "history omits url4" contract |
| C. Add one `latest` score-detail object to `HistoryResponse` | Safe | Yes | None | Medium: history route takes a second projection plus an aggregate read on every call | None | Rejected: couples two resources, extra read cost on every history call, still a second copy of the detail shape |
| D. Alias that reads `ReadIdentity` (same rules as `get_score`) | Depends on mesh stripping `X-User-Email` on ungated paths, which we cannot verify | Yes | None | Small | None | Rejected: unproven trust boundary for no portal benefit (the portal is anonymous) |
| E. Move `GET /v1/scores/{id}` itself to a new path | Same as A | No: breaks the SDK and every client of the old path | Breaking | Medium | None | Rejected: not additive |
| F. Ask Cloudflare to narrow the Access app | n/a | n/a | n/a | n/a | Yes | Rejected: violates C1 |
| G. Portal sends credentials and follows the login | n/a | n/a | n/a | n/a | No | Rejected: forces every visitor to log in to see a public run |

## 5. Contract of the new route

`GET /v1/public/scores/{score_id}`

- Path parameter `score_id`: UUID. A value that is not a UUID gives 422 (FastAPI default, as on
  the canonical route).
- 200: `ScoreSchema`, the same JSON the canonical route returns to an anonymous caller for the
  same id. No `Cache-Control` and no `Vary` header is added.
- 404: `{"detail": "score not found"}` with `Cache-Control: private, no-store` and
  `Vary: X-User-Email, Origin`, for each of:
  - an unknown id;
  - a score on a private board, for any caller, with or without `X-User-Email`;
  - a score whose board row cannot be found;
  - a score whose board turned private between the read and the answer (`turned_private`).
- 503: `{"detail": "score store unavailable"}` when the store raises `OperationalError`.
- Methods other than GET (and HEAD, if FastAPI adds it) give 405. The alias is read only.
- OpenAPI: the path is documented with `response_model=ScoreSchema` and the same
  `GET_SCORE_RESPONSES` as the canonical route, tag `scores`.

## 6. Acceptance

- AC1. An anonymous browser on the spec page of a public board sees the copy-url4 button, the
  paper link (when set), the metadata-edited line (when set) and the reproduced line (when > 0).
- AC2. The spec page makes no request to any path that starts with `/v1/scores`.
- AC3. Every private-board and unknown-id case in section 5 gives the byte-identical 404, body and
  cache headers, through the alias.
- AC4. The owner of a private-board score, with a verified `X-User-Email`, gets 404 through the
  alias and still gets 200 through `GET /v1/scores/{id}`.
- AC5. All existing scoreboard tests pass unchanged, except the two portal stubs that key on the
  old path.
- AC6. After deploy: `curl -s -o /dev/null -w '%{http_code}' https://leaderboard.screamingface.ai/v1/public/scores/<a real public id>`
  gives 200, with no redirect.

## 7. Out of scope

- The Cloudflare Access application itself.
- SDK anonymous reads (section 3.2).
- Rate limits or caching rules for the new path.
