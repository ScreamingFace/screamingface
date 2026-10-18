---
title: Plan — public score read outside the Cloudflare Access path
status: proposed, pending owner approval
created: 2026-10-18
ticket: unfiled
branch: fix-public-score-read-access-gate
spec: docs/spec/2026-10-18-fix-public-score-read-access-gate.md
stack: scoreboard (sdlc-python), root apps/scoreboard
---

# Plan — public score read outside the Cloudflare Access path

Do the steps in this order. Write each RED test first, run it, and see it fail for the
expected reason before you change source code.

Working directory for every command: `/Users/junior/workspace/screamingface/.claude/worktrees/public-score-read/apps/scoreboard`.

## Step 1. RED: Python route tests

Create `tests/unit/test_public_score_read.py`. Copy the fixture style of
`tests/unit/test_scores_routes.py` (lines 23-108: `_valid_payload`, `app_with_benchmark`,
`score_client`, `app_with_cloudflare_auth`, `cloudflare_score_client`, `_private_score` at
lines 511-525). Copy the fixtures into the new file. Do not import them from the other test
module.

Constants: `PUBLIC_PATH = "/v1/public/scores/{}"`, `PRIVATE_HEADERS = {"cache-control": "private, no-store", "vary": "X-User-Email, Origin"}`.

Tests (all `pytest.mark.asyncio` through `pytestmark`):

1. `test_public_read_serves_a_public_score_anonymously` — POST a score with `score_client`,
   GET the alias. Expect 200 and `body["id"]`, `body["url4_expression"]`.
2. `test_public_read_body_equals_the_canonical_read` — set a paper URL on the payload
   (`paper_url="https://arxiv.org/abs/2610.01234"`, see `tests/unit/test_score_paper_url.py`
   for a valid value), POST, then assert `alias.json() == canonical.json()` where canonical is
   `GET /v1/scores/{id}` with no headers.
3. `test_public_read_of_a_public_score_is_not_marked_private` — `"cache-control" not in
   response.headers` on a 200.
4. `test_public_read_carries_the_reproduction_count` — POST a public score, then
   `monkeypatch.setattr(ScoreStore, "reproduction_aggregate", fake)` where
   `async def fake(self, score_id): return (2, datetime(2026, 10, 6, 12, 30, tzinfo=UTC))`
   (`app.state.score_store` is a `ScoreStore()` instance, `main.py:186`). GET the alias.
   Assert `body["reproduction_count"] == 2` and `body["last_reproduced_at"]` starts with
   `"2026-10-06T12:30:00"`. Do not record a real reproduction (it needs a complete capture).
5. `test_public_read_unknown_id_is_the_private_404` — GET the alias with `uuid4()`. Expect 404,
   body `{"detail": "score not found"}`, and the two `PRIVATE_HEADERS`.
6. `test_public_read_hides_a_private_score_from_an_anonymous_caller` — `_private_score` with
   `cloudflare_score_client`, GET alias with no header. Expect 404, body
   `{"detail": "score not found"}` and `cache-control: private, no-store`.
7. `test_public_read_ignores_the_owner_identity` — same private score, GET the alias with
   `X-User-Email: alice@example.test` (the owner, trusted peer). Expect 404, body
   `{"detail": "score not found"}` and `cache-control: private, no-store`. Then GET
   `/v1/scores/{id}` with the same header and expect 200 (the canonical owner read stays).
8. `test_public_read_private_refusal_is_indistinguishable_from_unknown` — private score refusal
   and `uuid4()` miss through the alias, each with `X-User-Email: bob@example.test`. Assert same
   status, same JSON, same `cache-control`, same `vary`, AND assert
   `refused.json() == {"detail": "score not found"}` and
   `refused.headers["cache-control"] == "private, no-store"` (so the test cannot pass while the
   route is missing and both answers are the framework's `{"detail": "Not Found"}`). Copy the shape of
   `test_the_unknown_id_404_is_indistinguishable_from_the_private_refusal`
   (`tests/unit/test_scores_routes.py:674`).
9. `test_public_read_refuses_a_board_that_turned_private_mid_read` — POST a public score, then
   `monkeypatch.setattr("scoreboard.routes.scores.turned_private", <async fn returning True>)`.
   GET the alias. Expect 404, `{"detail": "score not found"}`, `cache-control: private, no-store`.
10. `test_public_read_store_unavailable_is_503` — `monkeypatch.setattr(Score, "get_or_none",
    <async fn raising OperationalError("database is locked")>)`. Expect 503 and
    `{"detail": "score store unavailable"}`.
11. `test_public_read_rejects_a_non_uuid_id` — GET `/v1/public/scores/not-a-uuid`. Expect 422.
12. `test_public_path_is_read_only` — POST and PATCH to the alias give 405.
13. `test_openapi_documents_the_public_read` — `GET /openapi.json`; the path
    `/v1/public/scores/{score_id}` has `get`; its 200 schema `$ref` ends with `/ScoreSchema`; its
    404 and 503 schema `$ref` end with `/MessageErrorResponse`; it has no other method.

RED check: `uv run pytest tests/unit/test_public_score_read.py -q`. Before Step 3 the route
does not exist, so FastAPI answers 404 `{"detail": "Not Found"}` with no private headers.
All 13 tests must fail (11 and 12 get 404, not 422 or 405). If any test passes before Step 3,
make it stricter.

## Step 2. RED: portal tests

File `tests/portal/reproduced-count.test.js`:

- Change the stub key `["/v1/scores/" + SCORE_ID]` to `["/v1/public/scores/" + SCORE_ID]`.
- In `renderSpecPage`, add `const requested = [];` and push `key` inside the `fetch` stub before
  the lookup. Return `{ content, portal: context.ScorePortal, requested }`.
- Add a test:

```js
test("the spec page reads the latest run from the public path, never from /v1/scores", async () => {
  const { requested } = await renderSpecPage(scoreDetail({}));

  assert.ok(requested.includes("/v1/public/scores/" + SCORE_ID), requested.join(", "));
  assert.deepEqual(requested.filter((key) => key.startsWith("/v1/scores")), []);
});
```

File `tests/portal/paper-link.test.js`: change the stub key
`"/v1/scores/11111111-1111-1111-1111-111111111111"` to
`"/v1/public/scores/11111111-1111-1111-1111-111111111111"`. Make no other change.

RED check: `node --test tests/portal/paper-link.test.js tests/portal/reproduced-count.test.js`
fails (the page still fetches `/v1/scores/...`, gets the stub 404, and renders nothing).

Do NOT add a new portal test file. A new file must be wired into
`.github/workflows/scoreboard-tests.yml` and `.claude/sdlc.local.md` by name
(`tests/unit/test_portal_ci_wiring.py`).

## Step 3. GREEN: backend

File `src/scoreboard/routes/scores.py`.

3a. Extract the body of `get_score` (current lines 374-441, from the `try:` to the final
`return`) into a private helper placed directly above `get_score`:

```python
async def _read_score(
    request: Request, response: Response, score_id: UUID, identity: str | None
) -> ScoreSchema:
    """The score detail ``identity`` may read, or the 503 / 404 refusal (OME-894).

    Shared by `GET /v1/scores/{id}` and `GET /v1/public/scores/{id}` so the access rules exist
    once. ``identity`` None means an anonymous caller.
    """
    ...  # the existing body, unchanged, with all its comments
```

Keep every line, comment and order of the old body. Change nothing in the logic.

3b. `get_score` keeps its decorator, signature and docstring. Its body becomes:

```python
    return await _read_score(request, response, score_id, identity)
```

3c. Add the alias directly below `get_score`:

```python
@router.get(
    "/public/scores/{score_id}", response_model=ScoreSchema, responses=GET_SCORE_RESPONSES
)
async def get_public_score(score_id: UUID, request: Request, response: Response) -> ScoreSchema:
    """Return a public score by id, for anonymous readers such as the portal.

    FEATURE: the production Cloudflare Access application is scoped to the path `/v1/scores`
    and covers every subpath. Access cannot scope by method, so an anonymous GET of
    `/v1/scores/{id}` gets a 302 to the login page. This path is outside that scope.

    INVARIANT: this route NEVER reads the caller's identity. No step verifies identity on a path
    Access does not cover, so a private-board score is the same 404 here for every caller, the
    owner included. The owner reads it through `GET /v1/scores/{id}`.
    """
    return await _read_score(request, response, score_id, identity=None)
```

3d. Update the module docstring first paragraph with one sentence: the public alias
`GET /v1/public/scores/{id}` exists because Access gates every `/v1/scores` subpath.

File `src/scoreboard/scores/schemas.py` (lines ~1018-1032): in the comment and in the two
`description=` strings, change "only `GET /v1/scores/{id}`" to
"only `GET /v1/scores/{id}` and `GET /v1/public/scores/{id}`". Text only.

## Step 4. GREEN: portal

File `portal/spec.js`:

- Line 71: `P.fetchJson("/v1/public/scores/" + encodeURIComponent(latestId))`.
- Header comment (lines 3-8): say the run link comes from
  `GET /v1/public/scores/{submissions[0].id}`, and add one sentence: "`/v1/scores/*` is behind
  Cloudflare Access in production, so an anonymous page must not call it."

## Step 5. Docs

- `apps/scoreboard/README.md`, section "Portal And Public Artifacts": add one sentence after the
  first paragraph: `GET /v1/public/scores/{id}` is the anonymous score read. It returns the same
  body as `GET /v1/scores/{id}`, never reads identity, and answers 404 for every private-board
  score. The portal uses it because production Cloudflare Access gates every `/v1/scores` path.
- `apps/scoreboard/DEPLOYMENT.md`, near line 215 (portal calls `/v1/*` same-origin): add one
  short paragraph: production Access has a path-scoped application on `/v1/scores` (all
  subpaths, all methods). Anonymous pages must use `/v1/public/scores/{id}`, `/v1/benchmarks`
  and `/v1/leaderboard/*`.

## Step 6. Gates

Run in `/Users/junior/workspace/screamingface/.claude/worktrees/public-score-read/apps/scoreboard`:

```bash
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pytest --cov=scoreboard --cov-fail-under=80 -q
node --test tests/portal/leaderboard-logic.test.js tests/portal/featured-benchmarks.test.js tests/portal/pareto-chart.test.js tests/portal/pareto-chart-review.test.js tests/portal/pareto-origin.test.js tests/portal/index-cards.test.js tests/portal/analytics.test.js tests/portal/subscribe.test.js tests/portal/paper-link.test.js tests/portal/reproduced-count.test.js tests/portal/pareto-chart-launch-copy.test.js tests/portal/benchmark-chart-isolation.test.js
```

All must exit 0. No SDK gate is needed: no file under `packages/` changes.

## Step 7. Close the ledger

Fill the "Outcome" section of `docs/work/2026-10-18-fix-public-score-read-access-gate.md`.
Do not commit until the user says so. Do not file a Linear issue until the PR is opened and the
user says yes.
