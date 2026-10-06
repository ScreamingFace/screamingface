# Contracts — E14 reproducible submission

One section for each connection that E14 adds or changes. Source tags follow `00-overview.md` §3.
Test numbers point at the TDD tables in the PRDs (`gw` = `prd/gateway-cache-revision.md`,
`md` = `prd/metadata-ownership.md`, `cv` = `prd/cache-version-capture.md`, `rp` = `prd/reproduce.md`).

## K1 — Engine → AI Gateway, sync, `POST /v1/chat/completions` (changed)

- Shape, request: the body `cache` object gains two optional fields `[stated ans:Q2]` `[stated ans:Q1]`.

  ```json
  {"cache": {"only-if-cached": true, "cache-revision": "cr-0123456789ab"}}
  ```

  `use-cache` keeps its meaning. A request with no new field is unchanged (gw G17).
- Shape, response: a new header, `X-AIGW-Cache-Revision: cr-<12 hex>`, on every response that ran
  the cache stage. The existing `X-AIGW-Cache*` headers are unchanged. `[proposed]`
- New errors (FastAPI `HTTPException`, `detail` object with `code` and `message`, the same shape as
  `apps/aigateway/src/aigateway/routes/chat.py:425`):

  | Status | `detail.code` | When |
  |---|---|---|
  | 504 | `cache_miss` | `only-if-cached` and no row |
  | 504 | `cache_bypass` (+ `reason`) | `only-if-cached` and the request would bypass |
  | 400 | `unknown_cache_revision` | the label is not in the registry |
  | 400 | `cache_revision_requires_only_if_cached` | an old label without `only-if-cached` |
  | 400 | `conflicting_cache_controls` | `only-if-cached` with `use-cache: false` |
  | 400 | `malformed_cache_controls` | a new field has the wrong type |

- Policies: no retry on any of these (they are deterministic). With `only-if-cached`, the gateway
  checks before credential resolution, so it never reads a credential or calls a provider for these
  errors. `[proposed]`
- Failure behaviour:
  - The engine maps `cache_miss`, `cache_bypass` and `unknown_cache_revision` to the case failure
    `replay_cache_miss` (or the code itself for the `400`s), and the case fails (rp R8, R11).
  - An older gateway (before B1) turns an unknown `cache` field into a **bypass**
    (`global_controls.py:72`), and a bypass calls the provider. A replay must never reach such a
    gateway. So at replay start the engine calls K10 once. If K10 is missing, or the label is not
    listed, the engine fails the run before the first chat call (rp R11, R17). `[proposed]`
- Contract tests: gw #9–#17, #20; rp #2, #3, #5, #6.

## K2 — Engine → AI Gateway, sync, Tavily `POST /v1/retrieval/tavily/cache/lookup` and `/entries` (B2 new caller, B1 changed)

- Shape: as OME-1044 defines (`apps/aigateway/src/aigateway/routes/tavily_retrieval_cache.py:189`,
  `:215`). The lookup body gains the optional `cache_revision: "cr-…"`. The response gains the
  `X-AIGW-Cache-Revision` header. `[proposed]`
- Policies: the lookup is called before each Tavily call. The fill is called after each successful
  Tavily call, and only in normal mode. A fill failure never fails the case (OME-1045). In replay
  mode there is no fill, and a lookup miss or bypass fails the case without a Tavily call.
  `[stated ans:Q4]` `[proposed]`
- Failure behaviour: a fill with an old label returns `422 cache_revision_read_only` (gw G12).
- Contract tests: gw #18, #19; cv #3, #10; rp #4.

## K3 — SDK → Engine, sync, run start (changed)

- Shape: a new optional request header, `X-Cache-Replay: cr-<12 hex>`, sent beside `X-Answer-Seed`
  (`packages/screamingface/src/screamingface/_engine/transport.py:1197`). It is sent only by
  `reproduce`. `[proposed]`
- Run summary (engine → SDK): two new attributes, `cache.revision` (a string or absent) and
  `cache.reproducible` (`complete` | `partial`), plus the `cache.partial.*` counts. A replay run
  also carries `cache.replay = <label>`; the SDK treats a replay summary without it as
  `failed/replay_unsupported` (a worker older than its App ignored the replay env). Deploy rule:
  workers before the App. `[proposed]`
- Failure behaviour: an older engine ignores the header, so the replay would run as a normal run
  and could pay providers. To stop this, the engine acknowledges replay mode in the run-start
  response (the header `X-Cache-Replay` echoed back). The SDK cancels the run when the ack is
  missing. B3 checks that no case starts before the start response is sent. `[proposed]`
- Contract tests: rp #2, #16; cv #14.

## K4 — SDK → Scoreboard, sync, `POST /v1/scores` (changed)

- Shape: new optional fields `paper_url` (A2), `cache_revision`, `reproducible` and `answer_seed`
  (B5). Each is omitted when NULL. `[stated prompt]` `[stated ans:Q3]`
- Policies: idempotent by `Idempotency-Key = run_id` (unchanged). On a same-owner resubmit,
  `paper_url` replaces when given, and the cache-version fields only fill (`erd.md` I2).
- Failure behaviour: `422` for a bad URL, label or status pairing (md M10, cv C10). An old board
  returns `422` for any unknown field, so the SDK omits NULL fields (cv C13).
- Contract tests: md #3–#5, #19; cv #15–#18.

## K5 — SDK → Scoreboard, sync, `PATCH /v1/scores/{id}` (new)

- Request (`extra="forbid"`, at least one field):

  ```json
  {"authors": ["a@x.org", "b@y.org"], "paper_url": "https://arxiv.org/abs/2610.01234"}
  ```

  An absent key means "unchanged". `paper_url: null` clears the link. `authors: null` is `422`.
- Response: `200` with `ScoreSchema` (including `paper_url` and `metadata_updated_at`).
- Policies: `VerifiedIdentity` is required, and it must equal `submitted_by`. The row is locked
  (`FOR UPDATE`), the score is updated and one event is inserted, all in one transaction. A PATCH is
  idempotent by value. `[stated ans:Q5]` `[stated ans:Q7]`
- Failure behaviour: `401`, `403` (`untrusted peer`, `not_score_owner`), `404` (missing, or a
  private board that is not the caller's), `422`.
- Contract tests: md #7–#17, #20, #21.

## K6 — SDK → Scoreboard, sync, `GET /v1/scores/{id}/metadata-events` (new)

- Response: `200`, a list (newest first) of
  `{id, edited_by, edited_at, source, old_authors, new_authors, old_paper_url, new_paper_url}`.
  `[stated ans:Q7]`
- Policies: owner only (`VerifiedIdentity == submitted_by`). There is no pagination, because the
  list is small. Revisit above 100 events for one score. `[stated ans:Q10]` `[proposed]`
- Failure behaviour: `401`, `403`, `404`, the same as K5.
- Contract tests: md #18, #22.

## K7 — SDK → Scoreboard, sync, `POST /v1/scores/{id}/reproductions` (new)

- Request:

  ```json
  {"run_id": "…", "score": 0.83, "total_questions": 200, "cache_revision": "cr-0123456789ab",
   "client": {"name": "screamingface", "version": "0.2.0", "platform": "darwin"}}
  ```

- Response: `201` with
  `{id, score_id, reproduced_by, reproduced_at, run_id, cache_revision, client_version}`, or `200`
  with the existing row for a repeated `run_id`.
- Policies: `VerifiedIdentity` is required (any identity, including the submitter). There is no cap
  `[stated ans:Q9]`. The pair `(score_id, run_id)` is unique. The score must be `complete`, and the
  numbers and the revision must match exactly `[stated ans:Q8]`.
- Failure behaviour: `401`, `403`, `404` (missing, or private and not the owner), `409`
  `not_reproducible`, `422` `not_exact`. The SDK catches all of them and sets
  `Reproduction.record_error` (rp R16).
- Contract tests: rp #7–#13, #18, #19.

## K8 — Scoreboard read DTO, `GET /v1/scores/{id}` and leaderboard rows (changed)

- `ScoreSchema` gains `paper_url`, `metadata_updated_at`, `cache_revision`, `reproducible`,
  `answer_seed`, `reproduction_count` and `last_reproduced_at`. Each one is nullable, except
  `reproduction_count`, which defaults to `0`. `[proposed]`
- The SDK `LeaderboardScore` decodes them. An older board leaves them absent, and the SDK treats
  absent as NULL (or 0).
- Contract tests: md #3, #20; cv #16; rp #13.

## K10 — Engine → AI Gateway, sync, `GET /v1/cache/revisions` (new, B1)

- Response: `200` `{"current": "cr-…", "known": ["cr-…", …]}`, the registry labels, oldest first.
  `[proposed]`
- Policies: the same account auth as the other gateway routes. The result is static for one
  deployment, so the engine calls it once for each replay run.
- Failure behaviour: `404` (a gateway before B1), or a label that is not in `known`, makes the
  engine fail the replay run with `unknown_cache_revision` before any chat call.
- Contract tests: gw #21; rp #6.

## K9 — Dependency rules (no payload)

- `apps/aigateway`: the registry lives in core (`core/request_cache/revision_registry.py`). Plugins
  register their adapter revisions into `core/request_cache/revisions.py`. **Core never imports a
  plugin.** A frozen projection is registered by its plugin under a label, and core looks it up by
  name. Checked by the existing layering gate (`check_layering.py`).
- `apps/scoreboard`: `VerifiedIdentity` lives in `routes/dependencies.py`, and every new write
  route uses it (the `scores.py:101` AIDEV-NOTE).
