# SB-meta — edit submission metadata: authors and paper URL (E14a, OME-1307) — implementation plan

Epic: [OME-1307](https://linear.app/openmined/issue/OME-1307) · Component: `apps/scoreboard` ·
Wave: 2 · Stack card: `scoreboard` (skill `sdlc-python`, companion `tortoise-dev`).

Spec (the rubric): `docs/spec/2026-09-29-e14-reproducible-submission/prd/edit-metadata.md`
(read in full), `contracts.md` C5 and C4 (the `paper_url` field only), `erd.md` §2.1, §2.5,
`test-plan.md` §1.

Delivery (D1): build this unit in its own temporary worktree on the branch `unit/SB-meta`,
made from the HEAD of `e14-reproducible-submission-spec`
(`git checkout -B unit/SB-meta e14-reproducible-submission-spec`). Do not open a PR. Do not
file a Linear issue. After wave 2, the integrator merges `unit/SB-meta` into
`e14-reproducible-submission-spec` (before `unit/SB-registry`, see §2 "Integration notes") and
runs the gates. The plan is this file,
`docs/plan/2026-09-29-e14-reproducible-submission/SB-meta.md`. Ledger:
`docs/work/2026-09-29-e14-sb-meta.md`; start it before the first RED.

Identity (D5): production runs `SCOREBOARD_AUTH_MODE=cloudflare_headers`
(`apps/scoreboard/src/scoreboard/core/auth/cloudflare_identity.py`: the peer check against
`SCOREBOARD_ALLOWED_NETWORKS` comes before the `X-User-Email` read). The owner check and the
event `actor` use that verified identity. The `disabled` mode is a dev/local fallback only:
keep today's behavior there (§4.5 step 3). The main-path tests run in `cloudflare_headers`
mode. Each flow (PATCH, history) has exactly one test for the `disabled` fallback.

One SDLC unit, one stack (`scoreboard`): backend plus one portal file. RED before GREEN.

## 1. Scope

### 1.1 In scope (test ids from `prd/edit-metadata.md` §7)

MD-1, MD-2 (CHAR), MD-3, MD-4, MD-5, MD-6, MD-7, MD-8, MD-9, MD-10, MD-11, MD-12, MD-13,
MD-14, MD-15, MD-16, MD-17, MD-18, MD-20.

Supporting rows (not PRD ids): MD-4a and MD-17a, the one `disabled`-fallback test of each flow
(D5).

### 1.2 Out of scope

- MD-19 (SDK `update_submission`): unit SDK-meta.
- MD-21 (E2E): unit E2E.
- Editing a `ReportedResult` (PRD §5). Clustering, receipts, names (SB-submit, SB-registry).
- Title, abstract, code URL, DOI, BibTeX, co-author confirmation (PRD §5).
- The same-owner **replay** path that already rewrites `authors` (`store.py:199-219`,
  OME-1054). This unit does not change it. See OD-M1.
- Prometheus counters (PRD §4 NFR). Decided: D7 X-15 (counters stay in process, no exporter,
  no `/metrics` route). `scoreboard/metrics.py` does not exist until SB-submit (wave 3), so this
  unit adds no counter.
- An `ETag` header on `GET /v1/scores/{id}` (C5 does not ask for it).

## 2. Depends on

- **SB-schema** must be merged: it adds `Score.paper_url`, `Score.metadata_revision`,
  `Score.metadata_updated_at`, the `ScoreMetadataEvent` model, the `ReportedResult` model
  (for MD-18), and the inert `ScoreSchema` fields.
- Contracts: implements **C5** (server side) and the `paper_url` field of **C4**.
- Consumer: SDK-meta (MD-19) reads the error body shape of §4.6. It already plans to read
  `detail.code` when `detail` is a mapping (SDK-meta plan §4.6).
- C11: this unit imports nothing from `url4` or `screamingface`.
- Later units that reuse this unit: SB-grants and SB-publish use `WriteIdentity` (§4.6a).
  SB-submit replaces the body of `_coded` with its shared `coded_error` helper.

### Integration notes (D2)

SB-registry is in the same wave and changes two of the same files. The integrator merges
**SB-meta first, then SB-registry**. Both changes are additive:

| Shared file | This unit adds | SB-registry adds |
|---|---|---|
| `apps/scoreboard/src/scoreboard/main.py` | `app.state.metadata_store = ScoreMetadataStore()` and `include_router(score_metadata.router)` | `app.state.system_registry = ...` |
| `.github/workflows/scoreboard-tests.yml` | `tests/portal/paper-link.test.js` on the `node --test` line; `tests/unit/scores/test_metadata_edit_postgres.py` in the `postgres` job | `packages/url4/**` path filters; its PostgreSQL module in the `postgres` job |

Keep your lines in their own block with a `FEATURE: OME-1307 (E14a)` comment, so the merge
has no overlapping hunk. `.claude/sdlc.local.md` is changed only by this unit in wave 2
(SB-submit changes it in wave 3).

## 3. Files

| Path | Change | Exemplar to imitate |
|---|---|---|
| `apps/scoreboard/src/scoreboard/scores/schemas.py` | change: `PaperUrl` type + validator; shared `_validate_authors`; `ScoreSubmission.paper_url`; `ScoreSchema.metadata_revision` always present; `LeaderboardEntry.paper_url`; new `MetadataValues`, `MetadataHistoryEvent`, `MetadataHistoryResponse`, `CodedErrorDetail`, `CodedErrorResponse` | `schemas.py:551-562` (validator), `schemas.py:674-745` (read DTO fields) |
| `apps/scoreboard/src/scoreboard/scores/metadata_store.py` | create: `ScoreMetadataStore`, outcome types, exceptions | `scores/baseline_store.py:37+` (a separate store), `scores/store.py:1091-1145` (locked, filtered update) |
| `apps/scoreboard/src/scoreboard/scores/store.py` | change: `_submission_to_kwargs` stores `paper_url`; both selects of `_build_leaderboard_query` add `paper_url`; `list_owned_entries` passes `paper_url` | `store.py:296-332`, `store.py:618-660`, `store.py:1502-1535` |
| `apps/scoreboard/src/scoreboard/routes/write_identity.py` | create: `write_identity`, `WriteIdentity` (§4.6a), the one verified-identity dependency for new write routes | `routes/scores.py:87-118` (`_resolve_submitter`, its AIDEV-NOTE asks for this extraction), `routes/dependencies.py:29-40` (`ReadIdentity`) |
| `apps/scoreboard/src/scoreboard/routes/score_metadata.py` | create: `PATCH /v1/scores/{score_id}`, `GET /v1/scores/{score_id}/metadata-history` | `routes/scores.py:287-353` (private-read rules) |
| `apps/scoreboard/src/scoreboard/routes/leaderboard.py` | change: `paper_url` on `RankedLeaderboardEntry` and `HistorySubmission`; `_history_submission` maps it | `leaderboard.py:54-93`, `leaderboard.py:120-134`, `leaderboard.py:175-187` |
| `apps/scoreboard/src/scoreboard/main.py` | change: `app.state.metadata_store = ScoreMetadataStore()`; `include_router(score_metadata.router)` | `main.py:179-194` |
| `apps/scoreboard/src/scoreboard/export_private_submissions.py` | change: `format_jsonl` drops `metadata_revision` when it is 1 | `export_private_submissions.py:44-57` |
| `apps/scoreboard/portal/leaderboard-logic.js` | change: add pure `paperLink(value)` to the exported API | `leaderboard-logic.js:17-60` |
| `apps/scoreboard/portal/benchmark.js` | change: render the paper link in the authors cell | `benchmark.js:185`, `main.js:97-117` |
| `apps/scoreboard/tests/unit/test_score_metadata_routes.py` | create: MD-1, MD-3 to MD-10, MD-13 to MD-18 | `tests/unit/test_scores_routes.py:1-121` (fixtures) |
| `apps/scoreboard/tests/unit/scores/test_metadata_schemas.py` | create: MD-2, MD-11, MD-12, MD-14 (schema half) | `tests/unit/scores/test_schemas.py` |
| `apps/scoreboard/tests/unit/scores/test_metadata_edit_postgres.py` | create: MD-6 on PostgreSQL | `tests/unit/test_delete_scores_postgres.py:1-120` |
| `apps/scoreboard/tests/portal/paper-link.test.js` | create: MD-20 | `tests/portal/leaderboard-logic.test.js:1-30` |
| `.github/workflows/scoreboard-tests.yml` | change: add `tests/portal/paper-link.test.js` to the `node --test` line; add `tests/unit/scores/test_metadata_edit_postgres.py` to the `postgres` job | `scoreboard-tests.yml:95`, `:166-174` |
| `.claude/sdlc.local.md` | change: add `tests/portal/paper-link.test.js` to the scoreboard `node --test` gate (Decided: D7 X-19, this edit is allowed) | `.claude/sdlc.local.md` scoreboard `gates:` |

WHY a **new** JS test file and not new cases in `leaderboard-logic.test.js`: the append-only
gate cannot parse JS, so any edit of an existing JS test file fails
(`.claude/scripts/run_gates.py:436-446`; only `.ts`/`.tsx` have an approval path).
`tests/unit/test_portal_ci_wiring.py` then requires the new file name in both call sites.

## 4. Signatures and data shapes

### 4.1 Validators (`schemas.py`)

```python
_PAPER_URL_MAX_CHARS = 2048
_PAPER_URL_SCHEMES = frozenset({"http", "https"})

def validate_paper_url(value: str) -> str:
    """INVARIANT (MD-E5): an absolute http(s) URL, at most 2048 chars, no credentials.
    Deliberately syntax-only: it never resolves or fetches the URL (PRD §5)."""
```

Rules, in this order (each raises `ValueError` with the message in quotes):

1. `len(value) > 2048` → `"paper_url must be at most 2048 characters"`.
2. `value != value.strip()` or any char with `ord(c) < 0x21` or `ord(c) == 0x7F` →
   `"paper_url must not contain whitespace or control characters"`.
3. `parts = urllib.parse.urlsplit(value)`; `parts.scheme.lower() not in {"http","https"}` →
   `"paper_url must be an absolute http or https URL"` (this also rejects `javascript:`,
   `data:`, `ftp:` and a relative URL).
4. `not parts.netloc` or `not parts.hostname` → same message as rule 3.
5. `parts.username is not None or parts.password is not None` →
   `"paper_url must not contain credentials"`.
6. Return `value` unchanged (no normalization).

`PaperUrl = Annotated[str, AfterValidator(validate_paper_url)]`.

Shared authors rule — move the body of `ScoreSubmission.validate_distinct_authors`
(`schemas.py:551-562`) into a module function and call it from both places:

```python
def _validate_authors(value: list[str] | None) -> list[str] | None: ...   # same body, same messages
```

### 4.2 Submit field (C4, MD-16)

`ScoreSubmission.paper_url: PaperUrl | None = None`. Store it in `_submission_to_kwargs`
(`store.py:296`). Do **not** add it to `_content_hash` (I-S3: identity excludes metadata).
Do **not** add it to `_REPLAY_FIELDS` (OD-M1).

### 4.3 PATCH body (C5)

```python
_EDITABLE_FIELDS = frozenset({"authors", "paper_url"})

class ScoreMetadataPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authors: Annotated[list[AuthorEmail], Field(min_length=1)] | None = None
    paper_url: PaperUrl | None = None

    @field_validator("authors")
    @classmethod
    def validate_authors(cls, value): return _validate_authors(value)
```

Use `patch.model_fields_set` to know which keys the client sent. An explicit `null` is a
sent key (MD-E7): `"paper_url": null` clears it; `"authors": null` stores `NULL`, so reads
derive `[submitted_by]` again (`store.py:283-287`).

### 4.4 Read DTOs

- `ScoreSchema.metadata_revision: int = 1` — change SB-schema's `exclude_if` so the field is
  **always** present in API JSON (C4 response shows `"metadata_revision": 1`, MD-H1).
- `ScoreSchema.paper_url`, `metadata_updated_at` stay excluded when `None` (SB-schema).
- `LeaderboardEntry.paper_url: str | None = Field(default=None, exclude_if=lambda v: v is None)`.
  Add the **same** declaration, with the same `exclude_if`, to `RankedLeaderboardEntry` (it
  splats `LeaderboardEntry`, `leaderboard.py:170-172`; a missing field is a 500) and to
  `HistorySubmission`, and map `paper_url=score.paper_url` in `_history_submission`
  (`leaderboard.py:175-187`).
  WHY `exclude_if` on all three: existing append-only tests assert the **exact** key set of a
  board entry and a history item (`tests/unit/test_leaderboard_routes.py:196`, `:699`
  `_PUBLIC_BOARD_ENTRY_FIELDS`, `:721` `_PUBLIC_HISTORY_ITEM_FIELDS`, `:786`, `:805`). A row with
  no paper URL must keep that exact key set, so `"paper_url": null` must never appear.
- `format_jsonl` (`export_private_submissions.py:54-56`): after `model_dump(mode="python")`,
  `if payload.get("metadata_revision") == 1: del payload["metadata_revision"]`.
  INVARIANT anchor: a certified export of an unedited legacy row must keep its bytes, so an
  earlier export still authorizes its purge (the trap `schemas.py:689-702` records).

```python
class MetadataValues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authors: Authors = None          # published form (local part), schemas.py:314-317
    paper_url: str | None = None

class MetadataHistoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: SubmittedBy               # published form, schemas.py:240-243
    at: datetime
    from_revision: int
    to_revision: int
    before: MetadataValues
    after: MetadataValues

class MetadataHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[MetadataHistoryEvent]
    next_cursor: str | None

class CodedErrorDetail(BaseModel):
    model_config = ConfigDict(extra="allow")   # 412 adds "current"; 422 adds "fields"
    code: str
    message: str

class CodedErrorResponse(BaseModel):
    detail: CodedErrorDetail
```

### 4.5 Store — `scores/metadata_store.py` (the Tortoise adapter)

```python
class MetadataEditOutcome(NamedTuple):
    score: ScoreSchema
    changed: bool                    # False for the MD-D4 idempotent resend

class ScoreNotFound(Exception): ...                  # unknown id, or private and not the owner
class NotSubmissionOwner(Exception): ...             # public board, caller is not the owner
class MetadataRevisionConflict(Exception):
    def __init__(self, current: ScoreSchema) -> None: ...

class ScoreMetadataStore:
    async def update_metadata(
        self,
        score_id: UUID,
        *,
        changes: Mapping[str, object],   # only the keys the client sent: "authors" / "paper_url"
        expected_revision: int,
        editor: str | None,              # verified X-User-Email (cloudflare_headers, D5);
                                         # None only in the disabled dev/local fallback
    ) -> MetadataEditOutcome: ...

    async def metadata_history(
        self,
        score_id: UUID,
        *,
        reader: str | None,              # ReadIdentity
        before_revision: int | None,     # the decoded cursor
        limit: int,
    ) -> tuple[list[ScoreMetadataEvent], int | None]: ...   # (events, next cursor revision)
```

`update_metadata` algorithm (one `async with in_transaction() as conn:` block):

1. `row = await _lock_row(conn, score_id)`, where the module-level seam is
   `async def _lock_row(conn: BaseDBAsyncClient, score_id: UUID) -> Score | None: return await Score.filter(id=score_id).using_db(conn).select_for_update().first()`.
   `None` → raise `ScoreNotFound`. WHY a module-level function: the PostgreSQL MD-6 test
   replaces it (pattern `_delete_rows` in `delete_scores.py:140` and its use in
   `tests/unit/test_delete_scores_postgres.py:118-160`).
2. `benchmark = await Benchmark.filter(id=row.benchmark_id).using_db(conn).only("visibility").first()`.
   `private = benchmark is None or benchmark.visibility == "private"`.
3. Owner rule (MD-E1, MD-D7):
   - `private` and (`editor is None` or `editor != row.submitted_by`) → `ScoreNotFound`.
     WHY `editor is None` too: in `disabled` mode a private board stays inert, the same rule
     that `submit` applies (`store.py` `PrivateBoardRequiresIdentity`, `routes/scores.py:265-272`).
   - not `private` and `editor is not None` and `editor != row.submitted_by` →
     `NotSubmissionOwner`.
   - not `private` and `editor is None` (disabled dev/local fallback only) → allowed (MD-E2),
     and the event stores `actor = NULL`. In `cloudflare_headers` mode `editor` is never
     `None`: `WriteIdentity` answers 401 before the store runs.
   - The owner is `Score.submitted_by` only. A `ReportedResult.reporter` is never an owner.
4. `before = {"authors": row.authors, "paper_url": row.paper_url}` (raw stored values).
   `after = {**before, **changes}`.
5. MD-D4: `after == before` → return `MetadataEditOutcome(_score_to_schema(row), changed=False)`.
   Do this **before** the revision check, so a resend after a lost response is `200` even with
   a stale `If-Match`. Write no event.
6. `row.metadata_revision != expected_revision` → raise
   `MetadataRevisionConflict(_score_to_schema(row))`.
7. Conditional update (MD-D2):
   `updated = await Score.filter(id=score_id, metadata_revision=expected_revision).using_db(conn).update(**changes, metadata_revision=expected_revision + 1, metadata_updated_at=now)`.
   `updated != 1` → re-read the row and raise `MetadataRevisionConflict`.
   WHY both the lock and the `WHERE`: the lock serializes on PostgreSQL; the `WHERE` is the
   rule the PRD names, and it holds on SQLite, where `select_for_update` is a no-op.
8. `await ScoreMetadataEvent.create(using_db=conn, score_id=score_id, actor=editor, from_revision=expected_revision, to_revision=expected_revision + 1, before=before, after=after)`.
   An exception here rolls back step 7 (MD-D3).
9. Re-read the row inside the transaction and return `(_score_to_schema(row), changed=True)`.
   Import `_score_to_schema` from `scores.store` (it is the one row→DTO mapper).

Keep the method under the complexity caps: extract `_authorize(row, private, editor)` and
`_conflict(conn, score_id)`.

`metadata_history`: apply the same read rule as `GET /v1/scores/{id}`
(`routes/scores.py:328-351`): private board → only `reader == row.submitted_by`, else
`ScoreNotFound`. Query `ScoreMetadataEvent.filter(score_id=…)`, add
`to_revision__lt=before_revision` when a cursor is given, `order_by("-to_revision")`,
`limit(limit + 1)`. When `limit + 1` rows come back, drop the last and return the last kept
row's `to_revision` as the next cursor.

### 4.6 Routes — `routes/score_metadata.py`

```python
router = APIRouter(prefix="/v1", tags=["scores"])

@router.patch("/scores/{score_id}", response_model=ScoreSchema, responses=PATCH_METADATA_RESPONSES)
async def update_score_metadata(
    score_id: UUID,
    request: Request,
    response: Response,
    editor: WriteIdentity,
    payload: Annotated[dict[str, Any], Body()],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ScoreSchema: ...

@router.get("/scores/{score_id}/metadata-history", response_model=MetadataHistoryResponse)
async def score_metadata_history(
    score_id: UUID,
    response: Response,
    identity: ReadIdentity,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> MetadataHistoryResponse: ...
```

PATCH order of checks (each check needs no database until step 5):

1. Identity — the route parameter `editor: WriteIdentity` (§4.6a). FastAPI runs it before the
   body. `cloudflare_headers`: untrusted peer → `403` with the existing `UNTRUSTED_PEER_DETAIL`
   string; no `X-User-Email` → `401` coded `identity_not_verified` (MD-E2, MD-4); else the
   verified email. `disabled`: `None` (MD-4a).
2. `If-Match` — missing, blank, or `*` → `428` coded `precondition_required` (MD-E4).
   Parse `^"([1-9][0-9]{0,9})"$`. A value that does not match → call the store in step 5 with
   `expected_revision=0`. Revisions start at 1, so 0 never matches: the store raises
   `MetadataRevisionConflict` with the current state (→ `412`), except for the MD-D4 resend of
   equal values, which the store answers `200` before the revision check.
3. Keys — `set(payload) - _EDITABLE_FIELDS` not empty → `422` coded `field_not_editable` with
   `"fields": sorted(extra keys)` (MD-E8). Nothing is read or written.
4. Values — `ScoreMetadataPatch.model_validate(payload)`; on `ValidationError` →
   `422` coded `invalid_metadata` with `"errors": [{"field": <loc[0]>, "message": <msg>}]`,
   where each message is the validator's text (MD-E5, MD-E6 share the submit messages).
5. Store call. Map: `ScoreNotFound` → `404` with the plain `SCORE_NOT_FOUND_DETAIL` string and
   `PRIVATE_CACHE_HEADERS` (the same bytes as `GET`, `routes/scores.py:318-341`);
   `NotSubmissionOwner` → `403` coded `not_submission_owner`;
   `MetadataRevisionConflict` → `412` coded `metadata_revision_conflict` with
   `"current": {"metadata_revision": n, "authors": <published>, "paper_url": …}`;
   `OperationalError` → `503` `STORE_UNAVAILABLE_DETAIL`.
6. Success: `200`, header `ETag: "<metadata_revision>"`, body `ScoreSchema`.

History: `cursor` must match `^[1-9][0-9]{0,9}$`, else `422` coded `invalid_cursor`.
`next_cursor` is `str(revision)` or `None`. Unknown or unreadable score → the same `404` as
`GET /v1/scores/{id}`. A private-board response carries `PRIVATE_CACHE_HEADERS`.

Coded error helper (module-private):

```python
def _coded(status_code: int, code: str, message: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra})
```

Logging (PRD §4): one `logger.info("score metadata edited", extra={"score_id": …, "actor_is_owner": True, "author_count": n})`
per successful edit. Never log an email or the author list.

### 4.6a Write identity — `routes/write_identity.py`

```python
async def write_identity(request: Request) -> str | None:
    """The verified caller of a write route (D5).

    cloudflare_headers: untrusted peer -> 403 UNTRUSTED_PEER_DETAIL (plain string); no
    X-User-Email -> 401 {"detail": {"code": "identity_not_verified", "message": ...}};
    else the verified email. disabled: None (dev/local fallback only; no header is read).
    INVARIANT: the peer check comes BEFORE the header read (cloudflare_identity.py:89-90)."""

WriteIdentity = Annotated[str | None, Depends(write_identity)]
```

- Body: `settings = cast(Settings, request.app.state.settings)`; `if not identity_is_verified(settings.auth_mode): return None`
  (`routes/scores.py:76-84`); then `peer_in_networks(...)` and `identity_from_headers(...)`
  exactly as `routes/scores.py:106-118`, with the coded 401 body (D7 X-8).
- Import `UNTRUSTED_PEER_DETAIL` and `identity_is_verified` from `scoreboard.routes.scores`.
  WHY a new module and not `routes/dependencies.py`: `routes/scores.py` imports
  `routes/dependencies.py` (`routes/scores.py:30`), so the reverse import would be a cycle.
- Do not change `_resolve_submitter`: the legacy submit route keeps its body fallback and its
  plain-string 401 (append-only tests pin it).

### 4.7 Portal — MD-20

`leaderboard-logic.js`, add to the exported API:

```js
// Returns {href, rel} for a safe absolute http(s) paper URL, else null. Pure; no DOM.
function paperLink(value) {
  if (typeof value !== "string" || value.length === 0 || value.length > 2048) return null;
  var u;
  try { u = new URL(value); } catch (e) { return null; }   // no base: relative URLs fail
  if (u.protocol !== "http:" && u.protocol !== "https:") return null;
  if (u.username || u.password) return null;
  return { href: u.href, rel: "noopener noreferrer nofollow" };
}
```

`benchmark.js` (authors cell, `:185`): build the `td` with `P.el("td", null, P.formatAuthors(entry.authors))`,
then when `L.paperLink(entry.paper_url)` is not null, append a text node `" · "` and an
anchor from `P.link("paper-link", link.href, "paper")`, then `a.setAttribute("rel", link.rel)`.
Never use `innerHTML`. The label is fixed text; the URL never becomes text.

### 4.8 Ports and adapters

The scoreboard has no metadata port today, and the PRD does not ask for one. The route is
the inbound adapter; `ScoreMetadataStore` is the Tortoise adapter. Keep all Tortoise code in
`scores/metadata_store.py` and all FastAPI code in `routes/score_metadata.py`.

### 4.9 Ed25519 JWS

None in this unit.

## 5. Migrations

None. SB-schema owns 0017-0019 and adds every column and table this unit needs. Do not run
`makemigrations`; if it writes a file, the models drifted — stop and ask.

## 6. TDD order (RED first, in risk order)

First create the empty `routes/score_metadata.py` router (a `PATCH` that returns `501`, a
history `GET` that returns `501`), register it in `main.py`, and create
`scores/metadata_store.py` with the classes and `raise NotImplementedError`. So every RED
below fails on an assertion. Route tests copy the fixtures of `tests/unit/test_scores_routes.py`
into the new file (do not import test modules):

- Main path (D5): `cf_app` / `cf_client` = a copy of `app_with_cloudflare_auth` and
  `cloudflare_score_client` (`tests/unit/test_scores_routes.py:65-107`), with its WHY on
  `monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")` and
  `"allowed_networks": "127.0.0.1/32"` (ASGITransport reports the peer `127.0.0.1`).
  `untrusted_cf_client` = a copy of `untrusted_peer_score_client` (`:110-120`, peer
  `203.0.113.5`). The same mode in a read-only test app: `tests/unit/routes/test_read_identity.py:34-48`.
- Fallback: `score_client` (`tests/unit/test_scores_routes.py:43-62`, `disabled` mode). Only
  MD-4a and MD-17a use it.
- `ANA = "ana@x.org"`, `BRUNO = "bruno@y.org"`, `def as_user(email) -> dict[str, str]: return {"X-User-Email": email}`.
- `_seed(client, *, owner, visibility="public")` registers the benchmark and submits one score
  with `headers=as_user(owner)`, so `Score.submitted_by == owner` (the route replaces the body
  value, `routes/scores.py:197-198`). Every PATCH and history call of a main-path test sends
  `as_user(...)`.

Unless a row says otherwise, a route test uses `cf_client`.

| # | Id | Test file :: name | RED reason |
|---|---|---|---|
| 1 | MD-1 (CHAR) | `test_score_metadata_routes.py::test_md1_char_resubmit_by_another_submitter_ignores_new_authors` | CHAR: passes on today's code. Pins that a replay of the same public recipe by a **different** `submitted_by` keeps the stored authors (`store.py:1018-1023`). See OD-M1 for the same-owner case. |
| 2 | MD-2 (CHAR) | `test_metadata_schemas.py::test_md2_char_public_json_strips_author_domains` | CHAR: passes today (`schemas.py:276-317`). |
| 3 | MD-3 | `test_md3_patch_by_non_owner_is_403_public_404_private_no_change` | stub returns 501. Assert 403 `not_submission_owner` on public, the plain 404 on private, and unchanged row + zero events after both. |
| 4 | MD-4 | `test_md4_patch_unverified_identity_401_except_disabled_mode` | 501. `cf_client` with no header → 401 `identity_not_verified`; `untrusted_cf_client` with `as_user(ANA)` → 403 with the plain `UNTRUSTED_PEER_DETAIL`. The row and the event count do not change. |
| 4a | MD-4a (disabled fallback, PATCH) | `test_md4a_disabled_fallback_public_edit_ok_actor_null_private_404` | 501. `score_client`: public board PATCH with `If-Match: "1"` → 200, revision 2, one event with `actor is None`; private board → the plain 404. This is the only `disabled` test of the PATCH flow. |
| 5 | MD-5 | `test_md5_patch_owner_adds_authors_bumps_revision_and_etag` | 501. Assert 200, new authors (published form), `metadata_revision == 2`, `ETag == '"2"'`. |
| 6 | MD-6 | `test_md6_concurrent_patches_one_wins_one_412` (SQLite, `asyncio.gather` of two PATCH calls with `If-Match: "1"` and different values) and `test_metadata_edit_postgres.py::test_md6_concurrent_patches_one_wins_one_412_on_postgres` | 501 / `NotImplementedError`. Assert sorted statuses `[200, 412]`, revision 2, one event. The PostgreSQL test calls `ScoreMetadataStore.update_metadata` from two tasks. It monkeypatches `metadata_store._lock_row` with a wrapper that calls the real `_lock_row`, then (in the first task only) sets `locked` and awaits `release` (two `asyncio.Event`s; pattern `_PausedDelete`, `test_delete_scores_postgres.py:118-160`). Start task 1, await `locked`, start task 2, assert after `asyncio.wait_for(asyncio.shield(task2), 0.5)` times out that task 2 is not done (it waits on the row lock), then set `release`. Always set `release` in `finally`. Use its own `Tortoise.init(config=build_tortoise_config(DATABASE_URL))` + `generate_schemas(safe=True)` and clean up its rows, like that module. |
| 7 | MD-7 | `test_md7_stale_if_match_412_with_current_state` | 501. Revision 3, `If-Match: "2"` → 412 with `detail.current.metadata_revision == 3` and current values; no change. |
| 8 | MD-8 | `test_md8_missing_if_match_428` | 501. Also `If-Match: *` → 428. |
| 9 | MD-9 | `test_md9_edit_does_not_change_content_hash_score_or_rank` | 501. Snapshot `content_hash`, `score`, `spec_id` and `GET /v1/leaderboard/{id}` ranks before; PATCH; assert all equal after. |
| 10 | MD-10 | `test_md10_history_event_written_in_same_transaction` | `NotImplementedError`. Monkeypatch `ScoreMetadataEvent.create` to raise `OperationalError`; assert 503 and the score row still has revision 1 and the old authors. |
| 11 | MD-11 | `test_metadata_schemas.py::test_md11_paper_url_rules` (parametrized) | `validate_paper_url` does not exist → create a stub that returns the value, so RED is the failed `pytest.raises`. Accept: `https://arxiv.org/abs/2609.01234`, `http://x.org/p`, a 2,048-char https URL. Reject: `ftp://x.org`, `javascript:alert(1)`, `data:text/html,x`, `https://user:pass@x.org`, `https://user@x.org`, `/relative`, `https://`, a 2,049-char URL, `" https://x.org"`, `"https://x.org/a b"`. |
| 12 | MD-12 | `test_metadata_schemas.py::test_md12_patch_authors_uses_submit_validator` | Same messages for 11 distinct people, 4,097 bytes, a bad email and `[]`, asserted on both `ScoreSubmission` and `ScoreMetadataPatch`. RED: `ScoreMetadataPatch` stub has no validator. |
| 13 | MD-13 | `test_md13_patch_null_clears_paper_url_and_resets_authors_default` | 501. After `{"paper_url": null}` the key is absent from `GET`; after `{"authors": null}` `GET` shows `[submitted_by]` (published form). |
| 14 | MD-14 | `test_md14_patch_immutable_field_422` (route) and `test_metadata_schemas.py::test_md14_patch_model_forbids_extra` | 501 / stub without `extra="forbid"`. `{"score": 1}` and `{"url4_expression": "x", "paper_url": "https://x.org"}` → 422 `field_not_editable`, `fields` lists the bad keys, nothing changes. |
| 15 | MD-15 | `test_md15_idempotent_resend_same_values_200_no_event` | 501. PATCH → rev 2; resend the same body with `If-Match: "1"` → 200, rev 2, still one event. |
| 16 | MD-16 | `test_md16_submit_accepts_paper_url` | `ScoreSubmission` has no field → the POST is 422. Assert 201, then `GET` shows the URL and `metadata_revision == 1`. Also assert a bad `paper_url` on submit is 422. |
| 17 | MD-17 | `test_md17_metadata_history_lists_newest_first_paged` | 501. Make 3 edits as `ANA`; `limit=2` → events `to_revision` 4, 3 and `next_cursor == "3"`; next page → 2 and `next_cursor is None`. Assert `before`/`after` and the published `actor` (`"ana"`). Private board: `BRUNO` → 404 with `PRIVATE_CACHE_HEADERS`; `ANA` → 200. |
| 17a | MD-17a (disabled fallback, history) | `test_md17a_disabled_fallback_history_public_readable_private_404` | 501. `score_client`: the history of a public-board score is 200 with no header; a private-board score is 404 for every caller, also with a forged `X-User-Email` (`ReadIdentity` ignores it in `disabled` mode, `cloudflare_identity.py:92-96`). This is the only `disabled` test of the history flow. |
| 18 | MD-18 | `test_md18_reporter_of_cluster_cannot_edit_head` | 501. Create `ReportedResult(head=score, is_original=False, reporter=BRUNO, …)` directly; `BRUNO` PATCH → 403 `not_submission_owner`; `ANA` → 200. |
| 19 | MD-20 | `tests/portal/paper-link.test.js` | `paperLink` is undefined → TypeError is a harness failure, so first add `function paperLink() { return null; }` to the API; then RED is the failed `assert.deepEqual` for a valid https URL. Cases: https ok with rel `"noopener noreferrer nofollow"`; http ok; `javascript:alert(1)`, `data:…`, `ftp://…`, `https://u:p@x.org`, `"/relative"`, `null`, `42`, a 2,049-char URL → `null`. |

Then GREEN each in order. After MD-16, add `paper_url` to the leaderboard projections
(§4.4) and run the whole suite: `test_every_score_field_reaches_at_least_one_read_dto` and the
leaderboard route tests must stay green.

## 7. Edge cases, what not to do, gates

### 7.1 Edge cases

- Cross-plan finding (append-only guard): `tests/unit/test_multiple_authors.py:225-250` asserts
  that every NULLABLE `LeaderboardEntry` field has a non-default value in its fixture. The new
  `LeaderboardEntry.paper_url` (default `None`) makes that guard fail, because its fixture
  `_submission(authors=[ALICE, BOB], ...)` sets no `paper_url`. `tests/unit/scores/test_store.py:1939-1968`
  stays green (`paper_url` is a `Score` column and `list_owned_entries` copies it). Run
  `test_multiple_authors.py` right after the DTO change. If it fails, STOP and ask (OD-M7). Do not
  edit the guard's logic.
- Empty body `{}` with a valid `If-Match`: `after == before` → 200, no event (MD-D4 rule).
- `authors` with duplicates by case (`A@x.org`, `a@x.org`): stored raw; published as one
  (`schemas.py:276-310`). Equality in step 5 compares raw lists, so a case change is an edit.
- `authors: null` on a row that already has `NULL`: no change, 200, no event.
- `If-Match: "0"`, `"01"`, `W/"2"`, `2` (unquoted): not the pattern → 412 with current state.
- A private board in the `disabled` fallback: 404 (§4.5 step 3, MD-4a).
- `cloudflare_headers` with a blank `X-User-Email: "  "`: counts as absent → 401
  (`identity_from_headers`, `cloudflare_identity.py:64-69`).
- A legacy row (revision 1 from the migration default) is editable (MD-D8, covered by MD-5).
- A board that turns private between the read and the write: the row lock plus the visibility
  read inside the same transaction decide once. No extra re-check is needed on a write.
- Plan gap found in review (guard registry): `tests/unit/guards/test_visibility_exit_guard.py`
  walks every function that reads `visibility` and lists its unguarded exits in
  `EXPECTED_UNGUARDED`. A new store method that reads `visibility` (here `update_metadata` and
  `metadata_history`) needs registry rows, and that edit is to an existing test file, so the
  append-only gate flags it and needs the user's approval. This plan did not say so. SB-grants and
  SB-publish also read visibility in new functions: plan the same registry edit and ask for the
  approval up front. A read that queries AFTER the visibility decision (a history, a list) is not
  "reads it fresh": return the decision (`benchmark_id`, `private`) and re-check it with
  `turned_private` in the route, as `get_score` does. The exit guard matches source text, so never
  write the name of a re-check helper in a docstring or comment of the store function.

### 7.2 What not to do

- Do not add `paper_url` to `_content_hash` or `_REPLAY_FIELDS`.
- Do not change `_replay_updates` or `_apply_replay_updates` (OD-M1).
- Do not trust `submitted_by` from a body on PATCH (the body cannot hold it: MD-E8).
- Do not log emails or author lists. Log counts only.
- Do not render `paper_url` with `innerHTML`, and do not show the URL text.
- Do not edit any existing test body or the existing JS test file. Append or create.
- Do not import `url4` or `screamingface` (C11). Do not import `routes` from `scores`.
- No migration in this unit.

### 7.3 Gates

```sh
uv run .claude/scripts/run_gates.py scoreboard --base "$(git merge-base HEAD e14-reproducible-submission-spec)"
```

WHY the merge base: the append-only check compares with the point where `unit/SB-meta` left
the e14 branch, which can move during the wave (D1).

(`ruff check`, `ruff format --check`, `pyright`, `pytest --cov=scoreboard --cov-fail-under=80`,
and `node --test tests/portal/leaderboard-logic.test.js tests/portal/pareto-chart.test.js tests/portal/pareto-chart-review.test.js tests/portal/paper-link.test.js`.)

## 8. Verification and "done"

```sh
cd apps/scoreboard
uv run pytest tests/unit/test_score_metadata_routes.py tests/unit/scores/test_metadata_schemas.py -v
uv run pytest tests/unit/test_portal_ci_wiring.py tests/unit/guards -v
node --test tests/portal/paper-link.test.js
SCOREBOARD_TEST_DATABASE_URL=postgres://scoreboard:scoreboard@localhost:5432/scoreboard_test \
  uv run pytest tests/unit/scores/test_metadata_edit_postgres.py -v
cd ../.. && uv run .claude/scripts/run_gates.py scoreboard --base "$(git merge-base HEAD e14-reproducible-submission-spec)"
```

Live probe (the OME-770 lesson: drive the real endpoint): run the app in the production mode
on a file SQLite database after `uv run tortoise migrate`:
`SCOREBOARD_AUTH_MODE=cloudflare_headers SCOREBOARD_ALLOWED_NETWORKS=127.0.0.1/32 FORWARDED_ALLOW_IPS=192.0.2.1 uv run uvicorn scoreboard.main:app --port 8765`.
Send every call with `-H "X-User-Email: ana@x.org"`. Submit one score, `PATCH` it with
`If-Match: "1"`, then `GET /v1/leaderboard/{id}` and `GET /v1/scores/{id}/metadata-history`.
Also send one `PATCH` without the header (expect 401 `identity_not_verified`). Run it twice
from a clean database and diff the output.

Done when MD-1 to MD-18, MD-4a, MD-17a and MD-20 are green, MD-1 and MD-2 are unchanged CHAR tests, the full
suite and gates are green, the probe output matches the PRD scenarios MD-H1 to MD-H5, and the
ledger Outcome is filled. Commit on `unit/SB-meta` (conventional commits, no `Refs:` line, no
`Co-Authored-By`), ready for the integrator (D1).

## 9. Open decisions

- **OD-M7 — the owned-entries guard needs a fixture value (open, STOP point).** Adding
  `paper_url` to `LeaderboardEntry` breaks `tests/unit/test_multiple_authors.py:225-250`
  (nullable field left at its default). The plan default was an owner-approved one-line
  fixture change, `paper_url="https://example.org/p"` in that `_submission(...)` call. That
  default cannot pass the gate: the append-only check never exempts a Python test
  (`.claude/scripts/approved_test_changes.py:48-52`). The user must choose: (a) approve the
  edit and run the gate once with `--skip-append-only`, recorded in the ledger; or (b) put
  `paper_url` only on `RankedLeaderboardEntry` and `HistorySubmission` (not on
  `LeaderboardEntry`), and fill it in `get_leaderboard` with one extra read by `source_id`
  inside the same snapshot (the SB-submit §4.10 pattern). Until then, run
  `test_multiple_authors.py` right after the DTO change and STOP if it fails (§7.1).

## 10. Decided

- **OD-M1 — decided (default).** Do not change the same-owner replay path
  (`_replay_updates`, OME-1054). MD-1 pins the true behavior (another submitter's replay is
  ignored). Known limit, recorded in the ledger: a same-owner replay can change `authors`
  with no revision bump and no event, so a client's next `If-Match` can get a 412.
- **OD-M2 — Decided: D7 X-8.** New errors use `{"detail": {"code", "message", ...}}`. The 404
  keeps the plain `SCORE_NOT_FOUND_DETAIL` string (the OME-894 byte-identical refusal), and the
  untrusted-peer 403 keeps the plain `UNTRUSTED_PEER_DETAIL` string. SDK-meta reads
  `detail.code` when `detail` is a mapping.
- **OD-M3 — Decided: D5.** Production is `cloudflare_headers`: the owner check and the event
  `actor` use the verified `X-User-Email`. The `disabled` fallback keeps today's behavior:
  a public-board edit skips the owner check and stores `actor = NULL`; a private board is 404.
- **OD-M4 — decided (default).** The 412 body holds the published (local-part) authors, the
  same form as every other API response.
- **OD-M5 — Decided: D7 X-15.** No metrics exporter and no `/metrics` route. This unit adds no
  counter (see §1.2).
- **OD-M6 — Decided: D7 X-19.** Editing `.claude/sdlc.local.md` is allowed.
