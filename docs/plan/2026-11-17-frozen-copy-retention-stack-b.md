# Plan: frozen copy retention, stack B (claims)

- Spec: `docs/spec/2026-11-16-frozen-copy-retention/` (owner approved 2026-11-17; owner
  decisions Q26 to Q32 of `00-overview.md` §5.4 are in this plan, see the last section). Read
  `00-overview.md` §2 and §7, `prd/score-claim.md`, `contracts.md` K4, K5, K9, K10, `erd.md`
  §2.5 (I1, I5) and §2.8, `test-plan.md` §5.2.
- Ledgers, one for each pull request, named by the branch slug (made when the code starts):
  `docs/work/2026-11-17-frozen-copy-claim-route.md` (B1) and
  `docs/work/2026-11-17-scoreboard-copy-claims.md` (B2 and B3).
- Issue: `OME-1947` (all stacks stay under it, Q26). Base: `origin/main` **after the pull
  request of stack A (#1911) is merged** (see
  "Pull request shape"). B1 paths are under `apps/aigateway/`. B2 and B3 paths are under
  `apps/scoreboard/`. A path that starts with `docs/`, `.claude/` or `.github/` is from the repo
  root. All line references are from the worktree at stack A (branch
  `OME-1947-frozen-copy-retention-stack-a`).
- Order inside each unit: RED tests first, then code, then gates. Tests are append-only. No
  existing test must change in stack B (see "Existing tests"). If an existing test fails, STOP
  and report it (file, test name, each assertion that fails).
- Commits, each with `(OME-1947)` at the end:
  `feat(aigateway): add the frozen copy claim route`,
  `feat(scoreboard): claim the frozen copy of a score at submit`,
  `feat(scoreboard): claim the copies of all scores at start`.
- Gates (`.claude/sdlc.local.md`, stacks `aigateway` and `scoreboard`): run
  `uv run .claude/scripts/run_gates.py aigateway` for B1 and
  `uv run .claude/scripts/run_gates.py scoreboard` for B2 and B3. The scoreboard gates need a
  local Node (the portal tests).
- Lint limits of the scoreboard (`apps/scoreboard/pyproject.toml:35-41`): complexity 8, 26
  statements, 7 branches and 3 `return` statements for each function. B2.2, B2.5 and B3.4 say how
  the code stays inside them. The gateway limits are wider (`apps/aigateway/pyproject.toml:43-49`).
- Postgres lane for B1: in `apps/aigateway`, `AIGW_TEST_PG=1 uv run pytest -m needs_postgres`
  (on Colima, also `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`). Stack B adds no
  Postgres test. The scoreboard lane (`SCOREBOARD_TEST_DATABASE_URL`) is not used.

## Pull request shape
- **B1 is one pull request** (gateway only). It is released before B2 and B3 (`00-overview.md`
  §7.1 step 2).
- **B2 and B3 are one pull request with one commit for each** (scoreboard only). They are
  released together (§7.1 step 3), and B3 needs the client of B2. Stacked branches are also
  possible for B2 and B3, because stack B changes no existing test and needs no approval record.
- **Cut each branch from `main` after stack A is merged.** The pre-push hook
  (`.githooks/pre-push`) compares each pushed branch with the merge base with `main`. A branch
  cut from the stack A branch contains the changed `tests/unit/test_frozen_copy_migration.py`,
  and the approval record names only the stack A branch, so the push fails.
- Branch names: `OME-1947-frozen-copy-claim-route` and `OME-1947-scoreboard-copy-claims`.
  `Refs: OME-1947` goes in each pull request body.

## Existing tests (checked on 2026-11-17)
No existing test fails because of stack B, if the code follows the three rules below.
1. **The default stays "no claim".** `SCOREBOARD_GATEWAY_URL` is empty by default, so each
   scoreboard test that submits a `frozen_copy_id` gets the result of today
   (`tests/unit/test_pinned_cache_lookup.py`, `test_score_reproductions.py`,
   `test_pinned_cache_same_owner_race.py`, `test_credit_metadata_review_round2.py`,
   `scores/test_store.py`). The new WARNING record of K-16 has no email and does not contain the
   words "score reproduction" (`tests/unit/test_score_reproductions.py:704-709` reads all
   records).
2. **The OpenAPI model of the submit 503 does not change (owner decision Q28).**
   `tests/unit/test_scores_routes.py:492-494` asserts that `responses["503"]` of `POST
   /v1/scores` is a `$ref` to `MessageErrorResponse`. A union model makes `anyOf`, and that
   assertion fails. Thus B2.5 changes only the description text of the 503 and the 422.
3. **`create_app(settings)` keeps its first positional argument** (`src/scoreboard/main.py:110`).
   The new argument is keyword-only.

Also checked, no effect: the gateway route list test compares two starts of one app
(`tests/unit/remote_endpoint/test_app_regressions.py:45-60`);
`tests/unit/test_chart_render_frozen_copy_sweep.py:114-119` pins the keys of
`config.frozenCopySweep`, so the claim list must not go into that block;
`tests/unit/test_frozen_copy_sweep_lifespan.py:95-101` refuses `frozen_copy_*` names that contain
`enabled` or end with `_from`; the scoreboard `Settings` has `extra="ignore"`
(`src/scoreboard/config.py:38-42`), and no test pins its field list. Do not name a new scoreboard
test file `*_postgres.py`, and do not use the fixture `postgres_schema_database_url`: the guard
`tests/unit/guards/test_postgres_regressions_run_in_ci.py:106` then needs a workflow change. The
engine and the SDK do not change.

## Order of work
1. B1: K-5, K-6, K-7 (guard) → K-1, K-2 → K-3, K-4 → chart → runbook → gates → Postgres lane →
   commit.
2. B2: K-8 → K-17 → CH-1, CH-2, CH-3 (confirm green before a change) → K-12, K-9, K-10, K-11 →
   K-13, K-14, K-15, K-35, K-24 → K-16, K-23 → K-26 → chart → runbook → gates → commit.
3. B3: K-18, K-19, K-20, K-21, K-27 (pass function and command) → K-22 → K-30, K-31, K-33 (task,
   unit) → K-28, K-29, K-32, K-34 (lifespan) → runbook → gates → commit.

## B1 — the gateway claim route and its guard
### B1.1 Setting (`src/aigateway/config.py`)
- After `admin_emails` (`:88-90`):
  ```python
  frozen_copy_claim_emails: Annotated[frozenset[str], NoDecode] = Field(
      default=frozenset(), validation_alias="AIGW_FROZEN_COPY_CLAIM_EMAILS"
  )
  ```
- Add the field name to the decorator of `_parse_admin_emails` (`:366-380`):
  `@field_validator("admin_emails", "frozen_copy_claim_emails", mode="before")`. Do not copy the
  function body.
- `config.py` has 506 lines (above 450 before this work). Add only these lines.

### B1.2 Guard `src/aigateway/core/auth/copy_claim.py` (new)
```python
async def require_copy_claimer(request: Request) -> None: ...
```
- It returns nothing, and it has no principal type: the route needs only the check, and uses it
  as `dependencies=[Depends(require_copy_claimer)]` (B1.4).
- Exemplar: `require_admin` (`core/auth/admin.py:79-129`). Order of the checks (`contracts.md`
  K4, `prd/score-claim.md` C13):
  1. `auth_mode == "jwt"` → 503.
  2. `auth_mode == "disabled"` → accept, with no list (loopback only).
  3. `frozen_copy_claim_emails` empty → 503.
  4. peer not in `allowed_networks` → 403 (`peer_in_networks`, `cloudflare_identity.py:39`). The
     peer is checked before the header is read.
  5. no identity (`identity_from_headers`, `cloudflare_identity.py:91`) → 401.
  6. email not in the list → 403. Use `email_is_admin(identity.email,
     settings.frozen_copy_claim_emails)` (`admin.py:49-60`).
- It makes no account row (no `account_for_identity`). It does not read `admin_emails`.
- **K-5, K-6, K-7**, new file `tests/unit/test_frozen_copy_claim.py`. Helper `_claim_client`:
  copy `_admin_client` (`tests/unit/auth/test_admin_allowlist.py:103-114`) and set
  `settings.frozen_copy_claim_emails`. K-6 sets `settings.auth_mode` to `"jwt"` and to
  `"disabled"` on the app of the fixture. K-7: an email in `admin_emails` only gets 403 on the
  claim route; an email in the claim list only gets 403 on `GET /v1/admin/accounts`.

### B1.3 Store method (`src/aigateway/core/frozen_copy/store.py`, after `seal`, `:119-143`)
```python
@dataclass(frozen=True, slots=True)
class ClaimOutcome:
    copy: FrozenCopy
    first: bool          # True when this call set claimed_at

async def claim(self, copy_id: UUID) -> ClaimOutcome | None: ...
```
- One transaction, exemplar `seal` (`:128-143`): `FrozenCopy.filter(id=copy_id)
  .select_for_update().first()` (no owner filter). `None` → return `None`. Status not `sealed`,
  or `claimed_at` set → `ClaimOutcome(copy, first=False)` with no write. Else `claimed_at =
  datetime.now(UTC)`, `save(update_fields=["claimed_at"])`, one INFO record with the copy id
  (logger of `:40`; no account name), `first=True`.
- The method does not evaluate the expiry rule (K-25 of stack C pins this).
- Do not: add a release method; write `claimed_at` in other code.

### B1.4 Route (`src/aigateway/routes/frozen_copies.py`, after `seal_frozen_copy`, `:221-231`)
```python
@router.post("/v1/frozen-copies/{copy_id}/claim", dependencies=[Depends(require_copy_claimer)])
async def claim_frozen_copy(copy_id: str, request: Request) -> dict[str, Any]: ...
```
- `copy_id: str`, parsed with `UUID(...)` as `_sealed_copy` does (`:109-112`): a malformed id is
  the 404 of `_not_found()` (`:193-199`), not a 422. No `CurrentAccount`. Add `Depends` to the
  `fastapi` import (`:18`).
- Map the outcome: `None` → `_not_found()`; status `open` → new helper `_not_sealed()` (409,
  `{"code": "frozen_copy_not_sealed", "message": "the frozen copy is not sealed"}`, next to
  `_sealed()`, `:202-206`); `abandoned` or `expired` → `_gone(copy.status)` (`:209-218`);
  `sealed` → 200 with `id`, `status: "sealed"`, `claimed_at` (ISO time, UTC) and `already`
  (`not first`).
- Add one sentence about the claim to the module docstring (`:9-10`).
- **K-1 to K-4**, file of B1.2. Fixtures `seed_copy`, `account_id_of`, `run_async`
  (`tests/unit/test_frozen_copy_support.py:33-37, 60-80`): make the copy with
  `authenticated_client`, then call the route through `_claim_client`. Set a status with the
  helper form of `tests/unit/test_frozen_copy_retention_states.py:18-29`. K-1: `claimed_at` is
  set in the row. K-2: `already` is `true` and `claimed_at` is equal to the first value. K-3:
  410 with `state: expired`, `claimed_at` stays `NULL`. K-4: `open` → 409; `abandoned` → 410
  with `state: abandoned`; a random UUID and `not-a-uuid` → the same 404.

### B1.5 Chart and runbook
- `charts/aigateway/values.yaml`, after `adminEmails` (`:91`): `frozenCopyClaimEmails: []`, with
  a comment (empty = the claim route answers 503 in `cloudflare_headers` mode). Do not put it in
  `frozenCopySweep` (`:150-153`).
- `charts/aigateway/templates/configmap.yaml`, after `AIGATEWAY_ADMIN_EMAILS` (`:35`):
  `AIGW_FROZEN_COPY_CLAIM_EMAILS: {{ join "," .Values.config.frozenCopyClaimEmails | quote }}`.
- No change to `templates/networkpolicy.yaml`. The scoreboard is admitted with one element of
  `networkPolicy.allowFrom` (`values.yaml:281`) that has both selectors. Do not use
  `clientPodNames` (one namespace only). `README.md`: one paragraph with an example element.
- New test `tests/unit/test_chart_render_frozen_copy_claim.py` (copy `_config_data`,
  `tests/unit/test_chart_render_frozen_copy_sweep.py:39-60`): the default renders the key with an
  empty value; a list renders with commas and `Settings` reads a lower-case set; an `allowFrom`
  element with a `namespaceSelector` and a `podSelector` renders as one `from` element.
- `DEPLOYMENT.md`, section of stack A (`:800-999`): add `### The claim route` (the list, the
  NetworkPolicy element, step 1 of `test-plan.md` §5.2), and replace "In this release, no claim
  exists yet" (`:996-998`).

## B2 — the scoreboard client, the submit route, settings, chart
### B2.1 Port (`src/scoreboard/core/copy_claims.py`, new; the core defines the port)
```python
class ClaimResult(StrEnum):   # claimed, already, not_sealed, abandoned, expired, not_found,
    ...                       # unavailable (the value of each member is its name in lower case)
KEPT: frozenset[ClaimResult]  # CLAIMED and ALREADY

class CopyClaims(Protocol):
    async def claim(self, copy_id: str) -> ClaimResult: ...
    async def aclose(self) -> None: ...
```
This module imports no `httpx`, no model and no route. B3.1 adds the claim pass to this file.

### B2.2 Adapter (`src/scoreboard/gateway_copy_claims.py`, new; it implements the port)
```python
class GatewayCopyClaims:
    def __init__(self, *, base_url: str, actor: str, timeout_s: float,
                 transport: httpx.AsyncBaseTransport | None = None) -> None: ...
    async def claim(self, copy_id: str) -> ClaimResult: ...
    async def aclose(self) -> None: ...

def build_copy_claims(settings: Settings) -> CopyClaims | None: ...   # None when the URL is empty
```
- It owns one `httpx.AsyncClient` (`httpx` is a runtime dependency; the only other use is
  `src/scoreboard/seed.py:12`). `POST {base_url}/v1/frozen-copies/{copy_id}/claim`, no body,
  header `HEADER_USER_EMAIL: actor` (`core/auth/cloudflare_identity.py:24`), timeout
  `timeout_s`. No retry. The call sends the copy id only.
- **The mapping fails closed** (`erd.md` I5, `prd/score-claim.md` C7 and §3.4). Write it as one
  lookup table and one `return`, so that the function stays inside the lint limits:
  ```python
  _RESULTS: dict[tuple[int, str], ClaimResult] = {
      (200, "claimed"): CLAIMED, (200, "already"): ALREADY,
      (404, "frozen_copy_not_found"): NOT_FOUND, (409, "frozen_copy_not_sealed"): NOT_SEALED,
      (410, "expired"): EXPIRED, (410, "abandoned"): ABANDONED,
  }
  # claim(): return _RESULTS.get(key, ClaimResult.UNAVAILABLE)
  ```
  A small function makes the key from the answer, or `None`:
  - 200: a key only when the body is a JSON object, `status == "sealed"`, and `already` is a
    `bool`; if the body has an `id`, it must be equal to `copy_id` (both are `str(UUID)`,
    `scores/schemas.py:503-507`, `apps/aigateway/src/aigateway/routes/frozen_copies.py:231`).
    The word is `"already"` or `"claimed"`. Each other 200 has no key.
  - 404 and 409: the word is `detail.code`. 410: the word is `detail.state`. A `detail` that is
    not an object has no key.
  - `httpx.HTTPError` and `ValueError` (a body that is not JSON) have no key. Catch only these.
  No key, and each key that the table does not name → `UNAVAILABLE`. A 200 never counts as a
  claim because of its status only.
- **K-8**, new file `tests/unit/test_copy_claims.py`, with `httpx.MockTransport` passed as
  `transport`: one case for each row of the table, and the request has the actor header and no
  body. Cases that must give `UNAVAILABLE`: `200 {}`; 200 with `status: "open"`; 200 with
  `already: "yes"`; 200 with a different `id`; 200 with a list body; `404 {"detail": "Not
  Found"}`; a 404 with a different code; 401; 403; 500; `httpx.ConnectTimeout`;
  `httpx.ConnectError`.

### B2.3 Settings (`src/scoreboard/config.py`, after `db_pool_maxsize`, `:84`)
```python
gateway_url: str = ""                      # SCOREBOARD_GATEWAY_URL; empty = no claim
gateway_actor: str = ""                    # SCOREBOARD_GATEWAY_ACTOR
gateway_timeout_s: float = Field(default=5.0, gt=0)
```
- One `model_validator(mode="after")` in the form of `_pool_bounds_are_ordered` (`:90-99`): a
  URL with an empty actor raises `ValueError`. Remove one `/` at the end of the URL.
- **K-17**, file of B2.2: `Settings.model_validate({...})` raises with the URL and no actor; it
  passes with both, and with none. `main.py:210` builds the app at import, so a wrong pair stops
  the start of the service.

### B2.4 App wiring (`src/scoreboard/main.py`)
- `def create_app(settings: Settings | None = None, *, copy_claims: CopyClaims | None = None)`
  (`:110`). After `app.state.score_store` (`:189`): `app.state.copy_claims = copy_claims if
  copy_claims is not None else build_copy_claims(settings)`. A test passes a fake here.
- The lifespan (`:100-107`) closes the client before `close_db()`. B3.3 has the full block;
  B2 writes it without the task lines.

### B2.5 Submit guard (`src/scoreboard/routes/copy_claim.py`, new)
```python
async def ensure_copy_is_claimed(request: Request, frozen_copy_id: str | None) -> None: ...
```
- `None` → return, no call (K-13). No client on `app.state` → one WARNING record ("no gateway
  URL: no claim for frozen copy <id>") and return (K-16). Else `await claims.claim(...)`:
  `KEPT` → return; `EXPIRED` → 422 `frozen_copy_expired`; `NOT_SEALED`, `ABANDONED`,
  `NOT_FOUND` → 422 `frozen_copy_unavailable`; `UNAVAILABLE` → 503
  `frozen_copy_check_unavailable` with `headers={"Retry-After": "5"}`. The three messages are the
  exact text of `contracts.md` K5. The detail shape is `{"code", "message"}`, as
  `_submission_refusal` (`routes/scores.py:279-297`). Take the refusal from a table
  (`ClaimResult` → status, code, message), so that the function has at most 3 `return`
  statements and 7 branches.
- One WARNING record for each result that is not in `KEPT`, with the result and the copy id, and
  with no email (K-23).
- `routes/scores.py` (827 lines, above 450 before this work) gets only: the import; one line
  `await ensure_copy_is_claimed(request, submission.frozen_copy_id)` after the revision read
  (`:364-365`) and before the store call (`:382-389`), inside the `try` of `:346`; and new text
  in the two descriptions of `SUBMIT_SCORE_RESPONSES` (422 `:147-155`, 503 `:156-159`). The 503
  `model` stays `MessageErrorResponse`. `submit_score` gets no new branch.
- Do not call the gateway in `ScoreStore.submit` or in a transaction. Do not add a call that
  removes a claim. Do not change `delete_scores.py` or `purge_private_benchmark.py`.
- **Tests**, new file `tests/unit/test_submit_claims_copy.py`. Fixture as
  `tests/unit/test_pinned_cache_lookup.py:56-73` (`ASGITransport`, no lifespan), with
  `create_app(settings, copy_claims=fake)`. The fake has a `result` that the test sets, and a
  list of calls. A wrapper around `ScoreStore.submit` (`monkeypatch`) records the order. The
  scoreboard has `asyncio_mode = "strict"` (`pyproject.toml:48`): mark each async test.

| Test | Assertion |
|---|---|
| CH-1, CH-2 | name the tests that pin them in the ledger (`test_pinned_cache_lookup.py:181`, the idempotency tests of `test_scores_routes.py`); they stay green with no edit |
| CH-3 | no client: a submit with a copy is stored (201), and no HTTP request is made |
| K-12 | `CLAIMED` → 201, and the order list is `["claim", "store"]` |
| K-9 | `EXPIRED` → 422 `frozen_copy_expired`, exact message, store not called |
| K-10 | `NOT_SEALED`, `ABANDONED`, `NOT_FOUND` → 422 `frozen_copy_unavailable`, store not called |
| K-11 | `UNAVAILABLE` → 503 `frozen_copy_check_unavailable`, `Retry-After: 5`, store not called |
| K-13 | no `frozen_copy_id` → no claim call |
| K-14 | the store refuses after a claim (a second Score names the copy) → one claim call in that request |
| K-15 | a repeat with the same `Idempotency-Key` → a second claim call, and 200 |
| K-35 | the fake changes to `NOT_SEALED`, then the same key → 422, and the stored row is equal |
| K-24 | a Score with no copy; the owner repeats with a copy and `NOT_SEALED` → 422, field stays `NULL` |
| K-16 | no client; `caplog` (the bridge of `tests/unit/conftest.py:58-64`): the Score is stored, and one WARNING record names the copy id and says that it has no claim |
| K-23 | `NOT_SEALED`, in `cloudflare_headers` mode with the header `X-User-Email: alice@example.test`: one WARNING record with the result and the copy id; the email is in no record |
| K-26 | with a gateway URL and an actor in the environment, patch `GatewayCopyClaims.claim` on the class and `httpx.AsyncClient.send` with recorders; `delete_scores(...)` (`src/scoreboard/delete_scores.py:155`) deletes a Score that names a copy → the two recorders have no call. The test fails if a later change adds a call |

### B2.6 Chart and runbook
- `charts/scoreboard/values.yaml`, in `config:` after `dbPoolMaxsize` (`:47`): `gatewayUrl: ""`,
  `gatewayActor: ""`, `gatewayTimeoutS: 5`. `templates/configmap.yaml`, after `:18`:
  `SCOREBOARD_GATEWAY_URL`, `SCOREBOARD_GATEWAY_ACTOR`, `SCOREBOARD_GATEWAY_TIMEOUT_S`, each
  `{{ .Values.config.<key> | quote }}`. The egress rule of the chart permits the call
  (`templates/networkpolicy.yaml:26-27`). `values-prod.yaml`: no change (the values come from
  the infrastructure repo).
- The scoreboard tests have no Helm test, and PyYAML is not a dependency. Do not add one. Add
  two checks to `.github/scripts/verify_chart_wiring.py`, in the scoreboard block
  (`:1818-1845`): the ConfigMap has the three keys, and the default URL is empty. The scoreboard
  gates do not run this script. Run it by hand from the repo root before the push:
  `python3 .github/scripts/verify_chart_wiring.py` (it needs `helm` on PATH and `pip install
  pyyaml`, as `.github/workflows/charts.yml:84-104`). In CI the workflow `charts.yml` runs it.
- `DEPLOYMENT.md`: new section `## Frozen copy claims (OME-1947)` before `## Troubleshooting`
  (`:420`): the settings, the refusals of a submit, the log records, the command, and a pointer
  to `test-plan.md` §5.2. `charts/scoreboard/README.md`: one paragraph.

## B3 — the claim pass at start and the command
### B3.1 Pass function (in `src/scoreboard/core/copy_claims.py`, the file of the port)
```python
@dataclass(frozen=True, slots=True)
class ScoreClaim:
    score_id: str; frozen_copy_id: str; result: ClaimResult | None   # None in a dry run

class GatewayUnavailable(Exception):       # it carries the results before the stop
    results: list[ScoreClaim]

async def run_claim_pass(
    claims: CopyClaims, rows: Sequence[tuple[str, str]]
) -> list[ScoreClaim]: ...
```
- **Plan decision (placement).** The spec puts the pass "next to the claim client"
  (`prd/score-claim.md` §7.1). The pass goes into the module of the port, not into the adapter
  module and not into a new module: it then depends only on the port and on rows that the store
  gives, and it imports no `httpx` and no model. There is no `scores/claim_pass.py`.
- **The query is one store method**, `ScoreStore.scores_that_name_a_copy() -> list[tuple[str,
  str]]`, after `pinned_caches_for_score_ids` (`scores/store.py:2421`):
  `Score.filter(frozen_copy_id__isnull=False).order_by("id").values_list("id",
  "frozen_copy_id")`, with each id as `str`. No filter on the board or on its visibility; ids
  only. `store.py` has 2481 lines (above 450 before this work): add only this method.
- `run_claim_pass`: one `claim` for each row, one after the other. The first `UNAVAILABLE`
  raises `GatewayUnavailable`.

### B3.2 Start task (same file)
```python
Sleep = Callable[[float], Awaitable[None]]
ReadRows = Callable[[], Awaitable[list[tuple[str, str]]]]

class ClaimPassTask:
    def __init__(self, claims: CopyClaims, read_rows: ReadRows, *, retry_s: float = 600.0,
                 sleep: Sleep | None = None) -> None: ...
    def start(self) -> None: ...
    async def stop(self) -> None: ...       # cancel, then await; it does not wait for the pass
    # read-only property: task -> asyncio.Task[None] | None
```
- Bind the default sleep when the module loads (`_ASYNC_SLEEP = asyncio.sleep`). No scoreboard
  test patches `asyncio.sleep` today; this keeps the task correct if one does. `start` and
  `stop` have the shape of `FrozenCopySweepTrigger` in the gateway (do not import it).
- Loop: `rows = await read_rows()`, then `run_claim_pass` → one INFO record with the number of
  Scores and the count of each result; if a result is not in `KEPT`, one WARNING record with the
  list of (Score id, copy id, result); then the task ends. On `GatewayUnavailable`: one WARNING
  record, `await sleep(retry_s)`, and a new pass that reads the rows again. The records have no
  email.
- **Owner decision Q29:** a database error in a pass gives one ERROR record with the type of
  the error, then the same wait of 10 minutes and a new pass (`prd/score-claim.md` C20). The
  task does not end with no claim pass done.

### B3.3 Lifespan (`src/scoreboard/main.py:100-107`)
```python
await init_db(settings.database_url, pool=settings.db_pool)
claims = app.state.copy_claims
task = (
    ClaimPassTask(claims, app.state.score_store.scores_that_name_a_copy)
    if claims is not None else None
)
app.state.claim_pass_task = task
if task is not None:
    task.start()                 # not awaited: the start and /readyz do not wait for the pass
try:
    yield
finally:
    try:
        if task is not None:
            await task.stop()    # 1. cancel the task and wait for it
    finally:
        try:
            if claims is not None:
                await claims.aclose()    # 2. close the claim client
        finally:
            await close_db()             # 3. close the database
```
With no gateway URL, `build_copy_claims` gives `None`: no task and no call.

### B3.4 Command (`src/scoreboard/claim_copies.py`, new; `python -m scoreboard.claim_copies`)
- One argument: `--dry-run`. Last lines `if __name__ == "__main__": raise SystemExit(main())`.
- Four exit statuses and the limit of 3 `return` statements: split the work in two functions.
  - `def main(argv: Sequence[str] | None = None) -> int`: parse; read `Settings()`; no gateway
    URL → a message on stderr and `return 2`, before `init_db`; else `return
    asyncio.run(_run(args, settings))`.
  - `async def _run(args, settings) -> int`: lifecycle as `_run` of `delete_scores.py:287-301`
    (`init_db`, `try`, `finally`: `aclose()` of the client, then `close_db()`). `--dry-run` →
    the rows with `result=None`, no call. Else `run_claim_pass(claims, await
    ScoreStore().scores_that_name_a_copy())`. `GatewayUnavailable` → print the lines before the
    stop, `return 1`. Else print, and `return 0 if <each result is in KEPT, or dry run> else 3`.
- Output: one JSON line for each Score (`score_id`, `frozen_copy_id`, `result`), then one
  summary line.

### B3 tests
- `tests/unit/test_claim_copies_cli.py` (exemplar `tests/unit/test_delete_scores_cli.py`: a
  database file, `main([...])`, `capsys`; patch `build_copy_claims` of the module to give the
  fake). **K-18** public and private boards, one line each. **K-19** a second run gives
  `already`. **K-20** one `expired` result → printed, the run continues, status 3. **K-21**
  `unavailable` → status 1. **K-22** no URL → status 2, no call. **K-27** `--dry-run` → no call.
- `tests/unit/test_claim_pass_at_start.py`. Unit (the task with a fake client and a fake `sleep`
  that records the delay and waits on an event): **K-30** one WARNING record, the delay is 600,
  the second pass starts at the first Score, and the task ends after it; a `read_rows` that
  raises a database error one time gives one ERROR record and the same delay (Q29). **K-31** the
  INFO record and one WARNING record with the ids, no email. **K-33** `stop()` in the wait ends
  the task. Lifespan (a `TestClient` built in the test body, as `tests/conftest.py:32-40`, with
  `create_app(settings, copy_claims=fake)`; seed the Scores before the client starts): **K-28**
  each stored Score gets one claim. **K-29** the fake sets a `threading.Event` when `claim`
  starts, then waits with `asyncio.wait_for(never.wait(), timeout=5)` and records `timed_out`.
  The test waits at most 2 s for the first event, gets 200 from `GET /healthz`, and asserts
  `timed_out is False`. A lifespan that waits for the pass starts only after the 5 s, so the test
  fails and does not hang. **K-32** no client → `app.state.claim_pass_task is None`. **K-34** the
  fake waits in `claim`; after the client exits, the order list is `["task ended", "client
  closed", "database closed"]` (record `aclose` in the fake, and wrap `close_db` of
  `scoreboard.main`).

## What stack B leaves ready for stack C
- **C1** uses `FrozenCopyStore.claim` in test S-14, and appends K-25 to
  `tests/unit/test_frozen_copy_claim.py`. The expiry rule reads `claimed_at`.
- **C1 is released only after B2 and B3 run in production** with a gateway URL, and after the
  checks 3 and 4 of `test-plan.md` §5.2. No code enforces this.

## Release notes for the operator
`00-overview.md` §7.1 steps 2 to 4, with the checks of `test-plan.md` §5.2. Handoff to the
infrastructure repo (§7.3): `AIGW_FROZEN_COPY_CLAIM_EMAILS`, one `allowFrom` element for the
scoreboard pods, the scoreboard address range in `AIGW_ALLOWED_NETWORKS`, and the three
scoreboard values. After step 3, a submit with a pinned cache that is not a sealed copy gets 422.

## Risks during the build
1. **The OpenAPI text of the 503 is not exact** (accepted, Q28). The model stays
   `MessageErrorResponse` (`detail` is text), but the new 503 has a `detail` object. Only the
   description says so.
2. **Each scoreboard pod runs the pass at each start** (three replicas in production): 376
   calls for each pod, one after the other. A pass of a second pod gets `already`.
3. **A task that is cancelled inside an `httpx` call** must end with `CancelledError`. Do not
   catch `BaseException` or `CancelledError` in `claim` or in the loop. K-34 proves it.
4. **The guard in `disabled` mode** accepts each caller. That mode is loopback only
   (`AuthDisabledLocalOnlyMiddleware`, `main.py:400`); K-6 tests the branch of the guard only.
5. **Files above 450 lines before this work:** `apps/aigateway/src/aigateway/config.py` (506),
   `apps/scoreboard/src/scoreboard/routes/scores.py` (827). Add only the lines above. Each new
   file stays at 450 lines or less.

## Owner decisions (2026-11-17)
The owner answered the open questions of this plan. The decisions are in `00-overview.md` §5.4.
- **Q26:** all work stays under `OME-1947`; no sub-issue for each app. Each pull request body has
  `Refs: OME-1947`. The issue stays open until stack C is released.
- **Q28:** the submit 503 changes only its description text in the OpenAPI document. The
  response model does not change, so no scoreboard test changes (B2.5).
- **Q29:** the claim pass at start tries again after 10 minutes also after a database error
  (B3.2).
- **Plan decision that stays (the owner did not object):** the pass function is in
  `core/copy_claims.py` with the port, and its query is a `ScoreStore` method (B3.1).
