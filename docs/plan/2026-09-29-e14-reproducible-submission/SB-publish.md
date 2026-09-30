# SB-publish — Plan: publish a cache version to GitHub, and admin takedown

- **Epic:** OME-1307 (E14).
- **Spec (the rubric):** `docs/spec/2026-09-29-e14-reproducible-submission/prd/publish-and-takedown.md`, `erd.md` §2.6, §2.7, §3.5, §4, `contracts.md` C7, C8b, C10, C11.
- **Plan:** this file, `docs/plan/2026-09-29-e14-reproducible-submission/SB-publish.md`. **Ledger:** `docs/work/2026-09-29-e14-sb-publish.md`. Start it before the first RED.
- **Delivery (D1):** build this unit in its own temporary worktree on the branch `unit/SB-publish`, made from the HEAD of `e14-reproducible-submission-spec` (`git checkout -B unit/SB-publish e14-reproducible-submission-spec`). Do not open a PR. Do not file a Linear issue. After wave 4, the integrator merges `unit/SB-publish` into `e14-reproducible-submission-spec` AFTER `unit/SB-grants` (see §2 "Integration notes") and runs the gates.
- **Component:** `apps/scoreboard` only. Wave 4 (D2), in parallel with SB-grants and SDK-replay.
- **Implementer:** Sonnet, `sdlc-python` loop. This is the largest unit of the track. Do it in the task order of §6 and commit after each task group is green.

## Global constraints

The same as `SB-submit.md` "Global constraints": stack `scoreboard`; gates through `run_gates.py` with `--base "$(git merge-base HEAD e14-reproducible-submission-spec)"`; ruff `max-returns = 3`, `max-branches = 7`, `max-statements = 26`, `max-complexity = 8`; `asyncio_mode = "strict"`; **append-only tests** (new files only); files ≤ 450 lines; the closed comment-anchor vocabulary; conventional commits on `unit/SB-publish` with no `Refs:` line and no `Co-Authored-By`; no import from another app and never `screamingface`. Plus:
- **Identity (D5).** Production runs `SCOREBOARD_AUTH_MODE=cloudflare_headers` (`apps/scoreboard/src/scoreboard/core/auth/cloudflare_identity.py`; the peer check against `SCOREBOARD_ALLOWED_NETWORKS` comes before the `X-User-Email` read). The publish owner check and the admin check use that verified email. The `disabled` mode is a dev/local fallback only: keep today's behavior there (publish and withdraw answer 503). The main-path tests run in `cloudflare_headers` mode; each flow (publish, withdraw) has exactly one `disabled`-fallback test (PB-2a, PB-12a).
- No real network in any test. GitHub is faked (port fake) or an `httpx.MockTransport` with fixture JSON. The bucket is faked or a temp directory.
- The GitHub App private key and the bucket secret key are key material: never log them, never put them in `last_error`, an exception message or a response.

## 1. Scope

**Owned test ids (`prd/publish-and-takedown.md` §7):** PB-1 … PB-20.

Supporting tests have a letter suffix (PB-7a …), listed in §6.

**Out of scope:**
- PB-21 (SDK `publish_cache_version` and the portal links; unit SDK-replay). This unit adds no portal code. See OD-6.
- PB-22 (nightly E2E against a sandbox repo).
- Writing the archive to the bucket (the gateway, C8a, unit GW-freeze).
- A DOI, Hugging Face, an owner withdraw, a release-body re-sync after a metadata edit (PRD §5).
- A `/metrics` HTTP route (SB-submit OD-3).
- Replay access after a takedown. SB-grants already reads `CacheVersionPublication.state` (RP-3). This unit only writes the state.
- Chart values and Secrets (GitHub App config, bucket read credentials, the admin allowlist, feature flags). Unit WIRING (wave 5, D6) owns them. This unit adds only the settings in `config.py`.
- The admin route that sets `Benchmark.redistributable`. Unit WIRING (D6) owns it and reuses `require_admin` and `AdminAuditRoute` from this unit (§4.10). Tests set the column on the seeded benchmark rows.

## 2. Depends on

- **Merged first:** SB-meta (it adds `routes/write_identity.py::write_identity` and `WriteIdentity`, SB-meta §4.6a) and SB-submit (and so SB-registry, SB-schema). SB-grants is in the same wave: it is NOT a code dependency (see "Integration notes"). SB-submit adds `pyjwt[crypto]` (this unit also uses it for the GitHub App RS256 JWT), `metrics.py`, `core/replay_access.py`, the coded-error helper, and the `CacheVersionPublication` row in state `private` at submit.
- **Contracts implemented:** C7 (GitHub releases, through the `ReleasePublisher` port), C8b (bucket read, through the `VersionArchiveReader` port), C10 (`POST /v1/results/{id}/publish`, `POST /v1/admin/results/{id}/withdraw`).
- **Contracts consumed:** C8a archive layout and digest (erd §3.5; GW-freeze writes it). The digest rule is Decided: D7 X-16 — `archive_sha256 == sha256(entries.jsonl.gz bytes)`, where GW-freeze writes the gzip with `mtime=0` and `compresslevel=9`. The scoreboard hashes the bytes that it reads; it never re-compresses.
- **Consumed from SB-schema:** `CacheVersionPublication` with the erd §2.6 columns (`result_id` PK, `state`, `requested_by`, `requested_at`, `attempts`, `next_attempt_at`, `lease_until`, `last_error`, `release_tag`, `release_url`, `published_at`, `withdrawn_at`, `withdrawn_by`, `withdrawn_reason`), and `Benchmark.redistributable`.

**Before RED:** open the merged models and write the real field names in the ledger. If a column of the list above is missing, STOP and ask.

### Integration notes (D2)

SB-grants is in the same wave and changes five of the same files. The integrator merges **SB-grants first, then SB-publish**. Both changes are additive. Put your lines in their own block with a `FEATURE: OME-1307 (E14) publish and takedown` comment, below the place where SB-grants adds its block, so the merge has no overlapping hunk:

| Shared file | SB-grants adds | This unit adds |
|---|---|---|
| `apps/scoreboard/src/scoreboard/config.py` | `replay_grant_signing_key`, `replay_grant_signing_kid` | `admin_emails`, `github_*`, `public_base_url`, `archive_*`, `publish_*` (§4.1) |
| `apps/scoreboard/src/scoreboard/main.py` | `app.state.grant_signer`, `app.state.replay_resolver`, `app.state.clock`, its router | `app.state.publication_store`, `app.state.release_publisher_factory`, `app.state.archive_reader`, two routers, the worker task in `_lifespan` |
| `apps/scoreboard/src/scoreboard/metrics.py` | `replay_grants` | the four fields of §4.9 |
| `apps/scoreboard/src/scoreboard/scores/schemas.py` (append at the END) | `ReplayGrantRequest`, `ReplayGrantResponse` | `PublishStateResponse`, `WithdrawRequest` |
| `apps/scoreboard/DEPLOYMENT.md` | a "Replay grants" section | a "Publish and takedown" section |

`.github/workflows/scoreboard-tests.yml` is changed only by this unit in wave 4. The worker uses its own clock argument (§4.7); if this unit also needs `app.state.clock`, add it the same way as SB-grants (`lambda: datetime.now(UTC)`), and the integrator keeps one line.

## 3. Files

| C/M | Path | What | Exemplar |
|---|---|---|---|
| M | `apps/scoreboard/src/scoreboard/config.py` | Settings (§4.1). | `admin_emails` parse: `apps/aigateway/src/aigateway/config.py:71-73,275-290` |
| C | `apps/scoreboard/src/scoreboard/core/auth/admin.py` | Pure, stdlib only: `email_is_admin(email, admin_emails)` and the frozen dataclass `AdminPrincipal(email)`. WHY no FastAPI here: `core/auth/` is pure today (`core/auth/cloudflare_identity.py:19-22` imports only the stdlib), and the PB-20a guard bans `fastapi` in `core/`. | `apps/aigateway/src/aigateway/core/auth/admin.py:47-78` |
| C | `apps/scoreboard/src/scoreboard/core/publish/__init__.py` | Package marker. | — |
| C | `apps/scoreboard/src/scoreboard/core/publish/state.py` | The pure state machine of erd §2.6. | — |
| C | `apps/scoreboard/src/scoreboard/core/publish/eligibility.py` | `publish_refusal(...)`. | — |
| C | `apps/scoreboard/src/scoreboard/core/publish/backoff.py` | `next_delay_s(...)`. | — |
| C | `apps/scoreboard/src/scoreboard/core/publish/release_body.py` | `escape_markdown`, `render_release_body`. | — |
| C | `apps/scoreboard/src/scoreboard/core/publish/ports.py` | `ReleasePublisher`, `VersionArchiveReader`, their data types and errors. | port style: `core/auth/cloudflare_identity.py` |
| C | `apps/scoreboard/src/scoreboard/adapters/github_releases.py` | `GitHubAppTokenSource`, `GitHubReleasePublisher` (httpx). | per-request client and sanitized errors: `apps/aigateway/src/aigateway/core/object_store.py:1-60,106-170` |
| C | `apps/scoreboard/src/scoreboard/adapters/sigv4.py` | A copy of `apps/aigateway/src/aigateway/core/sigv4.py` (153 lines), **by copy, not import** — the same precedent as `object_store.py:3-4` ("Mirrors the Engine's `artifacts/s3.py` shape by copy, not import"). Keep the header docstring and add a `WHY:` line that names the source file and OD-5. | the source file |
| C | `apps/scoreboard/src/scoreboard/adapters/s3_archive_reader.py` | `S3ArchiveReader` (GET only, path-style, SigV4). | `apps/aigateway/src/aigateway/core/object_store.py:39-88,106-170` |
| C | `apps/scoreboard/src/scoreboard/adapters/fs_archive_reader.py` | `FilesystemArchiveReader` (local mode, C8 "Local mode"). | — |
| C | `apps/scoreboard/src/scoreboard/scores/publication_store.py` | `PublicationStore`: the Tortoise adapter (requests, withdraw, lease, finish, failure, cleanup, gauges). | lock query exposed for SQL rendering: `scores/store.py:1146-1200` |
| C | `apps/scoreboard/src/scoreboard/publish/__init__.py`, `publish/worker.py` | `PublishWorker` (one job per `run_once`). | — |
| C | `apps/scoreboard/src/scoreboard/routes/publish.py` | `POST /v1/results/{result_id}/publish`. | `routes/scores.py:177-285` |
| C | `apps/scoreboard/src/scoreboard/routes/admin.py` | The `require_admin` dependency (§4.10), `_audit`, `AdminAuditRoute`, and `POST /v1/admin/results/{result_id}/withdraw`. | `apps/aigateway/src/aigateway/core/auth/admin.py:79-127` (`require_admin`, the order of checks), `apps/aigateway/src/aigateway/routes/admin.py:54-97` (`_audit`, `AdminAuditRoute`) |
| M | `apps/scoreboard/src/scoreboard/scores/schemas.py` | `PublishStateResponse`, `WithdrawRequest` (§4.2). Append at the END of the file. | — |
| M | `apps/scoreboard/src/scoreboard/metrics.py` | Counters and gauges (§4.9). | SB-submit §4.9 |
| M | `apps/scoreboard/src/scoreboard/main.py` | Build the publisher factory and the archive reader from settings (or `None`); `app.state.publication_store`, `app.state.release_publisher_factory`, `app.state.archive_reader`; include the two routers; start and cancel the worker loop in `_lifespan` (§4.8). | `apps/screamingface-engine/src/screamingface_engine/app.py:248-275` (`_install_artifact_sweeper`) and `main.py:97-103` |
| M | `apps/scoreboard/DEPLOYMENT.md` | The environment variables of §4.1, GitHub App set-up (contents write on the one repo only, PB-D7), bucket read-only credentials on `cache-versions/` (PB-D8), the admin allowlist (it works only in `cloudflare_headers`, D5), the alerts (§4.9). Say that the chart keys and the Secrets come from unit WIRING (D6). Do not edit the chart. | — |
| C | `apps/scoreboard/tests/fixtures/github/*.json` | Fixture bodies for PB-20 (§6). | — |
| C | tests (§6) | — | — |
| M | `.github/workflows/scoreboard-tests.yml` | Add `tests/unit/scores/test_publish_lease_postgres.py` BY NAME to the PostgreSQL job (`scoreboard-tests.yml:165-174`). The guard `tests/unit/guards/test_postgres_regressions_run_in_ci.py` fails if you forget. | — |

No migration (§5).

## 4. Signatures and data shapes

### 4.1 Settings

```python
admin_emails: Annotated[frozenset[str], NoDecode] = Field(default=frozenset())
# env SCOREBOARD_ADMIN_EMAILS, comma-separated, lowercased; parse exactly like
# apps/aigateway/src/aigateway/config.py:275-290 (drop empty entries).

github_app_id: str | None = None                       # SCOREBOARD_GITHUB_APP_ID
github_app_installation_id: str | None = None          # SCOREBOARD_GITHUB_APP_INSTALLATION_ID
github_app_private_key: SecretStr | None = None        # SCOREBOARD_GITHUB_APP_PRIVATE_KEY (PEM, RSA)
github_repo: str = "ScreamingFace/screamingface-cache-versions"   # erd §4 [proposed] name
github_api_url: str = "https://api.github.com"
public_base_url: str = "https://scoreboard.screamingface.ai"      # for the release body link

archive_backend: Literal["none", "s3", "filesystem"] = "none"
archive_s3_endpoint_url: str | None = None
archive_s3_bucket: str | None = None
archive_s3_region: str = "garage"
archive_s3_access_key_id: str | None = None
archive_s3_secret_access_key: SecretStr | None = None
archive_fs_root: Path | None = None

publish_worker_enabled: bool = True
publish_poll_interval_s: float = Field(default=30.0, gt=0)
```

- "Publishing is available" = all three `github_app_*` are set AND `archive_backend != "none"` AND `auth_mode == "cloudflare_headers"`. Else the publish route answers 503 `publish_unavailable` (PB-E6, OD-2).
- `create_app`: if some but not all `github_app_*` are set → `ValueError` naming the missing variable. If `archive_backend == "s3"` and any `archive_s3_*` (endpoint, bucket, key id, secret) is missing → `ValueError`. If `"filesystem"` and no `archive_fs_root` → `ValueError`. Messages never contain secret values.

### 4.2 Wire (C10)

```python
class PublishStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["private", "requested", "published", "failed", "withdrawn"]
    # Set only when state == "published"; the SDK-replay plan decodes it as optional (PB-21).
    release_url: str | None = Field(default=None, exclude_if=lambda v: v is None)

class WithdrawRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[str, Field(min_length=1, max_length=512)]
```

```
POST /v1/results/{result_id}/publish            (no body)
202 {"state": "requested"}                      private -> requested, or failed -> requested
200 {"state": "requested" | "published"}        no-op (PB-D5)
401 {"detail": {"code": "identity_not_verified", ...}}   (cloudflare_headers, no X-User-Email; WriteIdentity)
403 {"detail": "<UNTRUSTED_PEER_DETAIL>"}               (cloudflare_headers, untrusted peer; WriteIdentity)
403 {"detail": {"code": "not_result_owner", ...}}
404 {"detail": "result not found"}              unknown id, or a private-board result of another caller
409 {"detail": {"code": "withdrawn", ...}}
409 {"detail": {"code": "not_publishable", "reason": "private_board|not_redistributable|no_cache_version|integrity_failure"}}
503 {"detail": {"code": "publish_unavailable", ...}}

POST /v1/admin/results/{result_id}/withdraw     {"reason": "license: ..."}
200 {"state": "withdrawn"}                      (also the no-op from withdrawn)
401 missing identity · 403 {"code": "admin_required"} · 403 untrusted peer
404 {"detail": "result not found"}
409 {"detail": {"code": "not_publishable", "reason": "no_cache_version"}}
503 {"detail": {"code": "admin_unavailable", ...}}   empty allowlist, or auth_mode disabled
```

**Order of checks in the publish route** (fixed; each is one small function):
1. Identity: the route parameter `caller: WriteIdentity` (SB-meta §4.6a; do not copy `_resolve_submitter`). In `cloudflare_headers` (production, D5): untrusted peer → 403, no header → 401, else the verified email. In the `disabled` fallback it is `None`: then `not identity_is_verified(settings.auth_mode)` → 503 `publish_unavailable` (PB-2a).
2. Load `ReportedResult` + head + benchmark + publication. None → 404.
3. Private board and caller ≠ reporter → 404 (the same body as step 2). Use `is_owner` from `core/replay_access.py` (casefold).
4. Caller ≠ reporter → 403 `not_result_owner`.
5. `publication is None` → 409 `not_publishable` `no_cache_version`. `publication.state == "withdrawn"` → 409 `withdrawn`.
6. `publish_refusal(...)` (§4.3) not None → 409 `not_publishable` with that reason.
7. Publishing not available → 503 `publish_unavailable`. The state does not change (PB-19).
8. `publication_store.request_publish(result_id, requested_by=caller, now)` → returns `(state, changed)`. `changed` → 202, else 200.

**Withdraw route:** `dependencies=[Depends(require_admin)]` on a router with `route_class=AdminAuditRoute`. Then load → 404; no publication → 409 `no_cache_version`; `publication_store.withdraw(result_id, actor, reason, now)` → 200.

### 4.3 Core (pure)

`core/publish/state.py`:

```python
State = Literal["private", "requested", "published", "failed", "withdrawn"]
Event = Literal["owner_publishes", "worker_succeeds", "worker_fails_retryable",
                "attempts_exhausted", "admin_takedown"]

class TransitionRejected(Exception):
    def __init__(self, state: State, event: Event) -> None: ...

@dataclass(frozen=True, slots=True)
class Transition:
    to: State
    changed: bool          # False for the no-op cells
    reset_attempts: bool   # True only for failed --owner_publishes--> requested

def apply(state: State, event: Event) -> Transition:
    """erd §2.6, cell by cell. Encode the table as ONE dict[(State, Event), Transition | None]
    (None = reject). Raise TransitionRejected for None. withdrawn + owner_publishes is a
    reject that the route maps to 409 withdrawn."""
```

The table (copy exactly):

| state \ event | owner_publishes | worker_succeeds | worker_fails_retryable | attempts_exhausted | admin_takedown |
|---|---|---|---|---|---|
| private | requested (changed) | reject | reject | reject | withdrawn (changed) |
| requested | requested (no-op) | published | requested (changed=False) | failed | withdrawn |
| failed | requested (reset_attempts) | reject | reject | reject | withdrawn |
| published | published (no-op) | reject | reject | reject | withdrawn |
| withdrawn | reject | reject | reject | reject | withdrawn (no-op) |

`core/publish/eligibility.py`:

```python
INTEGRITY_ERRORS = frozenset({"archive_mismatch", "archive_missing", "release_conflict"})

def publish_refusal(*, board_visibility: str | None, redistributable: bool,
                    has_version: bool, state: str, last_error: str | None) -> str | None:
    """In order: private board -> "private_board"; not redistributable -> "not_redistributable";
    no version -> "no_cache_version"; state == "failed" and last_error in INTEGRITY_ERRORS ->
    "integrity_failure" (PB-E5: not retryable by the owner, OD-3). Else None."""
```

`core/publish/backoff.py`:

```python
BASE_S = 60.0
CAP_S = 3600.0
MAX_ATTEMPTS = 8

def next_delay_s(attempts: int, *, retry_after_s: float | None, jitter: float) -> float:
    """PB-E4. attempts is the count AFTER this failure (1 for the first).
    raw = min(CAP_S, BASE_S * 2 ** (attempts - 1)); jittered = raw * (1 + 0.2 * jitter),
    where jitter in [0, 1) comes from the caller's rng; return max(jittered, retry_after_s or 0).
    INVARIANT: the jitter never pushes the delay below Retry-After."""
```

`core/publish/release_body.py`:

```python
_MD_SPECIAL = set("\\`*_{}[]()#+-.!|<>~")

def escape_markdown(text: str) -> str:
    """Remove every char with ord < 32 (newlines too) and ord 127.
    Then put a backslash before each char in _MD_SPECIAL. Pure; PB-D9."""

@dataclass(frozen=True, slots=True)
class ReleaseFacts:
    system_name: str | None
    system_revision: int | None
    benchmark_id: str
    benchmark_revision: str | None
    score: float
    reporter: str | None       # already in the published local-part form
    authors: list[str] | None  # already in the published form
    paper_url: str | None
    scoreboard_url: str        # f"{public_base_url}/v1/scores/{score_id}"
    entry_count: int
    call_count: int
    coverage_status: str
    archive_sha256: str
    published_at: datetime

def render_release_body(facts: ReleaseFacts) -> str:
    """PB-H3. One line per field, 'Label: value', every value through escape_markdown.
    paper_url is shown only if it starts with 'https://' or 'http://' (else the line is
    omitted); it is escaped like any value (no link markup). The last line is exactly:
    'Metadata as of <published_at RFC 3339>. The current metadata is on the scoreboard page.'
    INVARIANT: no model output, no url4 text, no request or response body ever enters it."""
```

`release_body.py` receives the published forms already built (`ReleaseFacts.reporter`, `.authors`). It imports nothing from `scoreboard.scores`. The adapter builds them with `_publish_submitter` and `_publish_authors` (`scores/schemas.py:178`, `:276`); import them there, do not copy them.

### 4.4 Ports (`core/publish/ports.py`)

```python
@dataclass(frozen=True, slots=True)
class AssetRef:
    id: int
    name: str

@dataclass(frozen=True, slots=True)
class ReleaseRef:
    id: int
    tag: str
    html_url: str
    upload_url: str            # the template with "{?name,label}" already removed
    assets: tuple[AssetRef, ...]

class PublisherError(Exception):
    def __init__(self, message: str, *, retryable: bool, retry_after_s: float | None = None): ...
    # INVARIANT: message is sanitized: status code and GitHub's "message" field only,
    # truncated to 200 chars; never a header, a token or a URL with a query.

class ReleasePublisher(Protocol):
    async def get_release_by_tag(self, tag: str) -> ReleaseRef | None: ...
    async def create_release(self, tag: str, name: str, body: str) -> ReleaseRef: ...
    async def upload_asset(self, release: ReleaseRef, name: str, data: bytes,
                           content_type: str) -> AssetRef: ...
    async def download_asset(self, asset: AssetRef) -> bytes: ...
    async def delete_release(self, release_id: int) -> None: ...     # 404 counts as done
    async def delete_tag(self, tag: str) -> None: ...                # 404/422 counts as done

ReleasePublisherFactory = Callable[[], Awaitable[ReleasePublisher]]   # mints a token per job

@dataclass(frozen=True, slots=True)
class ArchivePair:
    entries: bytes             # entries.jsonl.gz
    manifest: bytes            # manifest.json

class ArchiveMissing(Exception): ...

class VersionArchiveReader(Protocol):
    async def read(self, version_id: UUID) -> ArchivePair: ...        # raises ArchiveMissing
```

Asset names and types: `entries.jsonl.gz` (`application/gzip`), `manifest.json` (`application/json`). Keys: `cache-versions/<version_id>/entries.jsonl.gz`, `cache-versions/<version_id>/manifest.json` (erd §3.5).

### 4.5 Adapters

`GitHubAppTokenSource(app_id, installation_id, private_key_pem, api_url, clock)`:
- App JWT: `jwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id}, private_key, algorithm="RS256")`.
- `POST {api_url}/app/installations/{installation_id}/access_tokens` → `token`. One token per job (PB-D7); no cache across jobs.

`GitHubReleasePublisher(client: httpx.AsyncClient, token: str, repo: str, api_url: str)`. Headers on every call: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`. Calls (C7 plus one, G1):

| Method | Call | Timeout |
|---|---|---|
| `get_release_by_tag` | `GET /repos/{repo}/releases/tags/{tag}`; 404 → None | 30 s |
| `create_release` | `POST /repos/{repo}/releases` `{"tag_name", "name", "body", "draft": false}` | 30 s |
| `upload_asset` | `POST {upload_url}?name=<name>` with `Content-Type` and the bytes | 120 s |
| `download_asset` | `GET /repos/{repo}/releases/assets/{id}` with `Accept: application/octet-stream` (follow redirects) | 120 s |
| `delete_release` | `DELETE /repos/{repo}/releases/{id}`; 204 or 404 → done | 30 s |
| `delete_tag` | `DELETE /repos/{repo}/git/refs/tags/{tag}`; 204, 404 or 422 → done | 30 s |

Error mapping (one function `_raise_for(response)`): 5xx, 429, and 403 with `x-ratelimit-remaining: 0` or a body `message` that contains `"secondary rate limit"` → `PublisherError(retryable=True, retry_after_s=<Retry-After seconds, or x-ratelimit-reset minus now, or None>)`. Any other 4xx → `retryable=False`. A transport error or timeout → `retryable=True`.

`S3ArchiveReader(config)`: GET `/<bucket>/<key>` path-style, signed with the copied `sigv4.authorization_header` (unsigned-payload hash of the empty body: `sha256("")`), timeout 60 s (C8 "Scoreboard: read timeout 60 s"). 404 or `NoSuchKey` → `ArchiveMissing`. Other errors → `PublisherError(retryable=True)`.

`FilesystemArchiveReader(root)`: reads `root / "cache-versions" / str(vid) / name`. A missing file → `ArchiveMissing`. Refuse a resolved path outside `root`.

### 4.6 `PublicationStore` (`scores/publication_store.py`)

```python
LEASE_S = 600          # PB-D2: lease_until = now + 10 min

@dataclass(frozen=True, slots=True)
class PublishJob:
    result_id: UUID
    state: str             # "requested" or "withdrawn" (cleanup)
    attempts: int
    release_tag: str
    cache_version_id: UUID
    cache_version_sha256: str

class PublicationStore:
    async def request_publish(self, result_id: UUID, *, requested_by: str, now: datetime
                              ) -> tuple[str, bool]:
        """In one transaction, lock the row (select_for_update), apply 'owner_publishes'.
        On a change: state=requested, requested_by, requested_at=now, next_attempt_at=None,
        last_error=None, release_tag=f"cv-{cache_version_id}", and attempts=0 when
        reset_attempts. Returns (new state, changed)."""

    async def withdraw(self, result_id: UUID, *, actor: str, reason: str, now: datetime
                       ) -> str:
        """Lock the row; apply 'admin_takedown'. On a change: withdrawn_at/by/reason, attempts=0;
        next_attempt_at = now IF the previous state was requested, published or failed (a
        release can exist: cleanup pending, PB-D4), else None (PB-D6: no GitHub call). The
        previous state 'withdrawn' is a no-op.
        INVARIANT: do NOT touch lease_until. A worker that holds the lease is mid-publish; it
        re-reads the state in finish_published (PB-D3) and does the cleanup itself. Clearing the
        lease would let a second worker lease the cleanup job while the first still uploads."""

    def lease_query(self, now: datetime, *, connection: Any) -> QuerySet[CacheVersionPublication]:
        """The due-job read, exposed so a test can render its SQL (store.py:1146-1175 pattern).
        Due = (state='requested' AND (next_attempt_at IS NULL OR next_attempt_at <= now))
           OR (state='withdrawn' AND next_attempt_at IS NOT NULL AND next_attempt_at <= now);
        AND (lease_until IS NULL OR lease_until < now). ORDER BY requested_at, result_id.
        .select_for_update(skip_locked=True) applied LAST (a values() projection drops it)."""

    async def lease_next(self, now: datetime) -> PublishJob | None:
        """In one transaction: lease_query(...).first(); set lease_until = now + LEASE_S."""

    async def finish_published(self, job: PublishJob, *, release: ReleaseRef, now: datetime
                               ) -> bool:
        """Lock the row and RE-READ the state (PB-D3). If it is 'requested': set published,
        release_url=release.html_url, published_at=now, lease_until=None, last_error=None;
        return True. If it is 'withdrawn': set next_attempt_at=now (cleanup), lease_until=None;
        return False."""

    async def record_retry(self, job: PublishJob, *, error: str, delay_s: float,
                           now: datetime) -> str:
        """Lock the row and RE-READ the state first. If job.state == 'requested' but the row is
        now 'withdrawn' (an admin won a race): leave the state, set next_attempt_at = now,
        lease_until = None, and return 'withdrawn' (the cleanup runs next).
        Else: attempts += 1. For a publish job: attempts >= MAX_ATTEMPTS -> 'attempts_exhausted'
        (failed), else 'worker_fails_retryable' (stays requested) with next_attempt_at = now +
        delay. For a cleanup job: no cap, next_attempt_at = now + delay. lease_until=None.
        last_error = error (already sanitized, ≤ 512 chars). Returns the new state."""

    async def record_failed(self, job: PublishJob, *, error: str, now: datetime) -> None:
        """Lock the row and RE-READ the state. 'requested' -> failed (event
        'attempts_exhausted'), last_error=error, lease_until=None. Row now 'withdrawn' -> only
        next_attempt_at = now and lease_until = None (cleanup pending)."""

    async def finish_cleanup(self, job: PublishJob) -> None:
        """next_attempt_at=None, attempts=0, lease_until=None, release_url kept as history."""

    async def gauges(self, now: datetime) -> tuple[dict[str, int], int]:
        """(count by state, count of rows with state='withdrawn' AND next_attempt_at IS NOT NULL
        AND withdrawn_at <= now - 1 h). WHY withdrawn_at and not next_attempt_at: the backoff
        moves next_attempt_at forward, so it does not measure how long the cleanup is pending
        (PB-D4 "stays pending for more than 1 h")."""
```

All state changes call `state.apply(...)`. No other code writes `state`.

### 4.7 Worker (`publish/worker.py`)

```python
class PublishWorker:
    def __init__(self, *, store: PublicationStore, publisher_factory: ReleasePublisherFactory,
                 archive_reader: VersionArchiveReader, facts_loader: FactsLoader,
                 metrics: Metrics, clock: Callable[[], datetime],
                 rng: Callable[[], float]) -> None: ...
    async def run_once(self) -> bool:     # True when it handled a job
```

`FactsLoader` = `async (result_id, published_at) -> ReleaseFacts` (the method `PublicationStore.release_facts`, which joins the result, head, system revision, system and benchmark). It builds the published forms of `reporter` and `authors` with `_publish_submitter` and `_publish_authors` (`scores/schemas.py:178`, `:276`). WHY in the adapter: `core/publish/release_body.py` must not import `scoreboard.scores.schemas` (that import runs `scores/__init__.py`, which imports `store.py` and Tortoise). `published_at` is the worker's `now` for this run; the same value is written by `finish_published`.

`run_once`:
1. `job = await store.lease_next(now)`; None → return False.
2. `job.state == "withdrawn"` → `_cleanup(job)`; else `_publish(job)`. Return True.

`_publish(job)`:
1. `pair = await archive_reader.read(job.cache_version_id)`. `ArchiveMissing` → `record_failed("archive_missing")`, `integrity_failures.inc()`, stop.
2. `hashlib.sha256(pair.entries).hexdigest() != job.cache_version_sha256` → `record_failed("archive_mismatch")`, `integrity_failures.inc()`, stop. No publisher call happens before this check (PB-3).
3. `publisher = await publisher_factory()`.
4. `release = await publisher.get_release_by_tag(job.release_tag)` or `create_release(job.release_tag, name=f"Cache version {job.cache_version_id}", body=render_release_body(facts))`.
5. For `(name, data, type)` in `[("entries.jsonl.gz", pair.entries, "application/gzip"), ("manifest.json", pair.manifest, "application/json")]` — in this order, so the manifest marks a complete release:
   - asset with that name exists → `download_asset`; `sha256(downloaded) != sha256(data)` → `record_failed("release_conflict")`, `integrity_failures.inc()`, stop (PB-D1). Equal → skip (no upload).
   - else `upload_asset`.
6. `await store.finish_published(job, release=release, now=now)`. If it returns False (withdrawn meanwhile, PB-D3): `delete_release(release.id)`, `delete_tag(job.release_tag)`; on success `finish_cleanup(job)`; a `PublisherError` leaves the cleanup pending for the next run.
7. `attempts_total.labels(result="ok").inc()`.
8. A `PublisherError` anywhere in 3–6: retryable → `delay = next_delay_s(job.attempts + 1, retry_after_s=err.retry_after_s, jitter=rng())`, `record_retry(...)`, `attempts_total.labels(result="retry").inc()`; not retryable → `record_failed(err.message)`, `attempts_total.labels(result="error").inc()`.

`_cleanup(job)`: `publisher_factory()`; `get_release_by_tag`; if found `delete_release(id)`; `delete_tag(tag)`; `finish_cleanup(job)`. A retryable `PublisherError` → `record_retry` (no cap). After each `run_once`, refresh the gauges.

Every `record_failed(...)` call above passes `now=now`.

INVARIANT: `run_once` never raises. The loop in §4.8 still catches and logs, as `apps/screamingface-engine/src/screamingface_engine/app.py:260-270` does.

### 4.8 Lifespan loop (`main.py`)

In `_lifespan` (`main.py:97-103`), after `init_db`: if `publish_worker_enabled` and publishing is available, start `asyncio.create_task(_publish_forever(worker, interval))`. `_publish_forever`: `while True: handled = await worker.run_once(); if not handled: await asyncio.sleep(interval)`; catch `Exception`, log `publish worker iteration failed` with `logger.exception`, sleep the interval. On shutdown cancel the task and await it (suppress `CancelledError`) BEFORE `close_db()`.

### 4.9 Metrics (add to `Metrics`)

- `publish_attempts: Counter` — `scoreboard_publish_attempts_total{result=ok|retry|error}`
- `publish_integrity_failures: Counter` — `scoreboard_publish_integrity_failures_total`
- `publish_jobs: Gauge` — `scoreboard_publish_jobs{state}`
- `withdraw_cleanup_pending: Gauge` — `scoreboard_withdraw_cleanup_pending` (rows pending for more than 1 h)

The alert rules go in `DEPLOYMENT.md` as text: `scoreboard_publish_integrity_failures_total > 0`; `scoreboard_withdraw_cleanup_pending > 0`.

### 4.10 Admin (`core/auth/admin.py`)

`require_admin(request) -> AdminPrincipal` lives in `routes/admin.py` (it raises `HTTPException`); it calls the pure `email_is_admin` from `core/auth/admin.py`. In this order (mirror `apps/aigateway/src/aigateway/core/auth/admin.py:79-127`, except step 2):
1. empty `admin_emails` → 503 `admin_unavailable`;
2. `auth_mode != "cloudflare_headers"` → 503 `admin_unavailable` (the PRD §4 rule "works only in the verified auth mode". NOTE: the gateway allows `disabled`; the scoreboard must NOT, OD-4);
3. and 4. `actor = await write_identity(request)` (SB-meta §4.6a): untrusted peer → 403 (`UNTRUSTED_PEER_DETAIL`, `routes/scores.py:57-59`); no header → 401 `identity_not_verified`. The mode is `cloudflare_headers` here (step 2), so `actor` is the verified email;
5. not on the list (casefold) → 403 `admin_required`.
Set `request.state.admin_actor` before step 5 so the audit line names the caller.

Keep `require_admin` and `AdminAuditRoute` public in `scoreboard.routes.admin`. Unit WIRING (D6) reuses both for its audited `Benchmark.redistributable` route. Do not build that route here.

`AdminAuditRoute` logs one line per attempt on the logger `scoreboard.routes.admin`, at INFO: `admin_action actor=<actor|<unidentified>> result_id=<id> reason=<reason|<none>> outcome=<status>` (PRD §4 "actor, result id, reason, outcome"). `result_id` comes from `request.path_params["result_id"]`. The reason comes from `request.state.withdraw_reason`, which the handler sets after it parses the body; when `require_admin` refused first, it is `<none>`. Log the reason with `escape_markdown` and cut it to 120 chars (it is caller text).

## 5. Migrations

None. erd §2.6 names a cleanup flag `release_delete_pending` in PB-D4, but the §2.6 column list does not have it. This plan encodes "cleanup pending" as `state = 'withdrawn' AND next_attempt_at IS NOT NULL`, with the columns that SB-schema already makes. So no migration is needed, and the rule "only the schema-foundation unit adds migrations" holds. If the merged SB-schema added `release_delete_pending`, STOP and ask which one to use (G2).

## 6. TDD order (RED first, risk order)

New directory `apps/scoreboard/tests/unit/publish/` with `__init__.py` and `conftest.py`.

`conftest.py`:
- `FakeReleasePublisher` (implements the port in memory): `releases: dict[str, ReleaseRef]`, `assets: dict[int, bytes]`, a call log `calls: list[tuple[str, ...]]`, and programmable failures `fail_next: list[PublisherError]`.
- `FakeArchiveReader(pairs: dict[UUID, ArchivePair])`.
- `canonical_pair()` → `ArchivePair(entries=gzip.compress(b'{"key_hash":"k"}\n', compresslevel=9, mtime=0), manifest=b'{"schema":"screamingface.cache-version.v1"}')`, and `hashlib.sha256(pair.entries).hexdigest()` as the receipt `sha` (D7 X-16: the digest of the gzip bytes, the GW-freeze rule).
- `publish_app` / `publish_client` — **the main path (D5)**: `cloudflare_headers` mode. Copy the existing fixtures `app_with_cloudflare_auth` / `cloudflare_score_client` (`tests/unit/test_scores_routes.py:65-107`) with their WHY comments (`allowed_networks="127.0.0.1/32"`, `FORWARDED_ALLOW_IPS=192.0.2.1`), and `untrusted_peer_score_client` (`:110-120`) as `publish_untrusted_client`. Settings: `clustering_enabled=True`, the SB-submit receipt key, `admin_emails="admin@x.org"`, the GitHub settings set to dummy values, `archive_backend="filesystem"` with `tmp_path`, `publish_worker_enabled=False` (tests drive `run_once` by hand). Override `app.state.release_publisher_factory` with the fake.
- `publish_disabled_client` — **the `disabled` fallback only** (PB-2a, PB-12a): the same settings with the default `auth_mode`.
- Seed through `POST /v1/scores` on `publish_client` with `headers=as_user(ANA)` and a receipt whose `sha` equals the pair digest and whose `sub` is `ANA`. Import `make_receipt`, `URL4_A`, `URL4_B`, `ANA`, `BRUNO`, `as_user` from `tests.unit.submissions._receipts` (SB-submit §6); every seeded url4 is one of these constants. The admin is `"admin@x.org"`. Unless a row says otherwise, a route test uses `publish_client` with `as_user(...)`. Benchmarks: `pub` (public, redistributable), `gated` (public, not redistributable), `priv` (private).
- A fixed clock and `rng = lambda: 0.0`.

Before RED: stub routes that raise `NotImplementedError`, empty modules, the settings. Each RED fails on an assertion.

**Task group A — eligibility and ownership (commit after A).**

| # | Test id | File | Test name | RED reason |
|---|---|---|---|---|
| 1 | PB-1 | `test_publish_route.py` | `test_publish_private_board_or_not_redistributable_409_reason` — owner on `gated` → 409 `not_publishable` `not_redistributable`; owner on `priv` → 409 `private_board`; result with no receipt → 409 `no_cache_version`; the state stays `private` | 500 |
| 2 | PB-2 | `test_publish_route.py` | `test_publish_by_non_reporter_403_private_404` — Bruno on Ana's `pub` result → 403 `not_result_owner`; Bruno on Ana's `priv` result → 404, the same body as an unknown id | 500 |
| 3 | PB-2a (disabled fallback, publish) | `test_publish_route.py` | `test_publish_in_disabled_mode_is_503` — `publish_disabled_client`, on a row seeded with the models: 503 `publish_unavailable`, also with a forged `X-User-Email: ana@x.org`; the state stays `private`. The only `disabled` test of the publish flow. (D5) | 500 |
| 3a | PB-2b | `test_publish_route.py` | `test_publish_needs_verified_identity` — no header → 401 `identity_not_verified`; `publish_untrusted_client` with `as_user(ANA)` → 403 `UNTRUSTED_PEER_DETAIL`; the state stays `private`. (D5) | 500 |

**Task group B — integrity and idempotency (commit after B).**

| # | Test id | File | Test name | RED reason |
|---|---|---|---|---|
| 4 | PB-3 | `test_worker.py` | `test_archive_digest_mismatch_fails_without_upload_and_alerts` — (a) reader returns other bytes → state `failed`, `last_error == "archive_mismatch"`, the fake publisher call log is EMPTY, the integrity counter is 1; (b) reader raises `ArchiveMissing` → `archive_missing`, same checks | stub |
| 5 | PB-4 | `test_worker.py` | `test_retry_after_crash_finds_release_by_tag_no_duplicate` — pre-load the fake with release `cv-<vid>` and both assets with the right bytes; `run_once` → `published`; the log has `get_release_by_tag` and two `download_asset`, and NO `create_release` or `upload_asset` | stub |
| 6 | PB-4a | `test_worker.py` | `test_resume_uploads_only_the_missing_manifest` — the release has only `entries.jsonl.gz` (right bytes) → one upload, of `manifest.json` | stub |
| 7 | PB-5 | `test_worker.py` | `test_release_by_tag_with_other_digest_fails_release_conflict` — the existing `manifest.json` has other bytes → `failed`, `release_conflict`, integrity counter 1, no upload | stub |
| 8 | PB-6 | `test_publish_route.py` | `test_owner_publish_202_requested` — 202 `{"state": "requested"}`; the row has `requested_by`, `requested_at`, `release_tag == "cv-<vid>"` | 500 |
| 9 | PB-7 | `test_worker.py` | `test_worker_publishes_assets_and_sets_published` — after PB-6, `run_once` → `published`, `release_url` = the fake html_url, `published_at` = the clock; the fake holds both assets with the bucket bytes; the release body equals `render_release_body(facts)` | stub |
| 10 | PB-7a | `test_archive_readers.py` | `test_filesystem_reader_reads_pair_and_refuses_escape`, `test_s3_reader_signs_get_and_maps_404_to_missing` (`httpx.MockTransport`: assert the `Authorization` header starts with `AWS4-HMAC-SHA256` and the path is `/<bucket>/cache-versions/<vid>/manifest.json`) | stub |

**Task group C — concurrency (commit after C).**

| # | Test id | File | Test name | RED reason |
|---|---|---|---|---|
| 11 | PB-8 | `tests/unit/scores/test_publish_lease_postgres.py` | `test_only_one_worker_leases_a_row` — PostgreSQL only (skip and cleanup as `tests/unit/scores/test_idempotency_postgres.py:25-95`; schema by `Tortoise.generate_schemas()` as in that file). Two `lease_next` calls in parallel (`asyncio.gather`) on ONE due row → exactly one job; a third call before the lease ends → None; after the lease ends (clock + 601 s) → the job again | skipped without the database; with it, both callers get the row |
| 12 | PB-8a | `test_publication_store.py` | `test_lease_query_really_skips_locked_rows` — render `lease_query(...).sql()` on the asyncpg dialect (copy `tests/unit/scores/test_model_identities.py:543-574`) and assert `FOR UPDATE SKIP LOCKED` | method missing |
| 13 | PB-9 | `test_worker.py` | `test_withdraw_during_publish_deletes_new_release_no_published` — make the fake's `upload_asset` for `manifest.json` call `publication_store.withdraw(...)` first (the admin wins the race); after `run_once`: state `withdrawn`, `published_at` is None, the fake has no release and no tag | stub |

**Task group D — takedown (commit after D).**

| # | Test id | File | Test name | RED reason |
|---|---|---|---|---|
| 14 | PB-10 | `test_withdraw.py` | `test_admin_withdraw_sets_withdrawn_deletes_release_keeps_row` — publish (PB-6, PB-7), then `POST /v1/admin/results/{id}/withdraw` as `admin@x.org` → 200 `withdrawn`; the row has `withdrawn_at/by/reason`; `run_once` deletes the release and the tag; `GET /v1/scores/{head}` is still 200 and the leaderboard still lists the head | 500 |
| 15 | PB-11 | `test_worker.py` | `test_withdraw_github_delete_failure_marks_cleanup_pending_and_retries` — the fake fails `delete_release` with a retryable 502 → the row stays `withdrawn`, `next_attempt_at = now + 60 s`, `attempts == 1`; the next due `run_once` succeeds → `next_attempt_at` is None; the pending gauge is 0 at `withdrawn_at + 59 min` and 1 at `withdrawn_at + 61 min` while the delete keeps failing (move the clock) | stub |
| 16 | PB-12 | `test_withdraw.py` | `test_non_admin_withdraw_403_and_audited` — `as_user(BRUNO)` → 403 `admin_required`; `caplog` has one `admin_action actor=bruno@y.org` line with `outcome=403`; no header → 401 `identity_not_verified` (`actor=<unidentified>`); `publish_untrusted_client` → 403 `UNTRUSTED_PEER_DETAIL`; empty allowlist → 503 `admin_unavailable` | 500 |
| 16a | PB-12a (disabled fallback, withdraw) | `test_withdraw.py` | `test_withdraw_in_disabled_mode_is_503` — `publish_disabled_client` with `admin_emails="admin@x.org"` and a forged `X-User-Email: admin@x.org` → 503 `admin_unavailable`; the state does not change. The only `disabled` test of the withdraw flow. (D5) | 500 |
| 17 | PB-13 | `test_publish_state.py` | `test_publish_after_withdraw_409` — `apply("withdrawn", "owner_publishes")` raises; the route answers 409 `withdrawn` | stub |
| 18 | PB-17 | `test_withdraw.py` | `test_withdraw_never_published_blocks_replay_no_github_call` — withdraw a `private` row → `withdrawn`, `next_attempt_at` is None; `run_once` → False and the fake log is empty; `replay_access(..., publication_state="withdrawn", caller="bruno@x.org")` → `"withdrawn"` | 500 |

**Task group E — retry rules (commit after E).**

| # | Test id | File | Test name | RED reason |
|---|---|---|---|---|
| 19 | PB-14 | `test_publish_backoff.py` | `test_github_5xx_429_backoff_then_failed_after_8` — unit table for `next_delay_s`: attempts 1→60, 2→120, 7→3600 (cap), jitter 0.5 → ×1.1, `retry_after_s=900` on attempt 1 → 900; plus a worker test: eight retryable errors (502, 429 with `Retry-After: 120`, 403 secondary-limit) → `failed` on the 8th, `last_error` sanitized (no token, ≤ 512 chars), and `next_attempt_at` honors `Retry-After` | stub |
| 20 | PB-14a | `test_github_adapter.py` | `test_error_mapping_retryable_and_retry_after` (`MockTransport`: 500, 429 + `Retry-After`, 403 + `x-ratelimit-remaining: 0`, 403 + "secondary rate limit", 422 → not retryable, `httpx.ConnectTimeout` → retryable) | stub |
| 21 | PB-15 | `test_publish_state.py` | `test_republish_from_failed_resets_attempts` — a `failed` row with a retryable error (`last_error="HTTP 502"`, `attempts=8`) → owner publish → 202, `attempts == 0`; a `failed` row with `archive_mismatch` → 409 `not_publishable` `integrity_failure` | stub |
| 22 | PB-16 | `test_publish_state.py` | `test_double_publish_is_noop` — the full erd §2.6 table as a parametrized unit test on `apply`, plus the route: publish twice → 202 then 200 `requested`; after PB-7 → 200 `published` | stub |

**Task group F — content, config, adapter contract (commit after F).**

| # | Test id | File | Test name | RED reason |
|---|---|---|---|---|
| 23 | PB-18 | `test_release_body.py` | `test_release_body_has_generated_fields_only_escaped` — a system name `a*b_[x](y)`, authors with a domain (published as the local part), `paper_url="javascript:alert(1)"` (line omitted), `paper_url="https://arxiv.org/abs/1"` (escaped text), control chars dropped; the body contains the exact "Metadata as of …" line; no `<`, no unescaped `[` | stub |
| 24 | PB-19 | `test_publish_route.py` | `test_publish_unavailable_503_without_app_config` — no GitHub settings → 503 `publish_unavailable`, the state stays `private`; plus `create_app` with only `github_app_id` set → `ValueError` naming the missing variables | 500 |
| 25 | PB-20 | `test_github_adapter.py` | `test_github_adapter_contract` — `httpx.MockTransport` that serves `tests/fixtures/github/release_get_404.json`, `release_create_201.json`, `asset_upload_201.json`, `release_get_by_tag_200.json`, `asset_download_200.bin`, and 204s for the two deletes. Assert the method, the path, the headers (`Authorization`, `Accept`, `X-GitHub-Api-Version`), the create body (`draft: false`), the upload URL with the `{?name,label}` template removed and `?name=manifest.json`, the octet-stream `Accept` on download, and that 404 on delete counts as done. Also `GitHubAppTokenSource`: the `POST /app/installations/<id>/access_tokens` call with an RS256 JWT whose `iss` is the app id (decode it with the test key). | stub |
| 26 | PB-20a | `tests/unit/guards/test_publish_layering.py` | `test_only_adapters_reach_github_and_the_bucket` — AST scan of `src/scoreboard`: `httpx` is imported only under `adapters/` and in the existing modules that import it today (list them from `git grep -l "import httpx" -- src` at the merge base with `e14-reproducible-submission-spec`, e.g. `seed.py`); the string `api.github.com` appears only in `config.py`; `adapters.github_releases`, `adapters.s3_archive_reader`, `adapters.fs_archive_reader` are imported only by `main.py`; neither a module under `core/publish/` nor `core/auth/admin.py` imports `tortoise`, `fastapi`, `pydantic`, `httpx`, `jwt`, `scoreboard.scores` or `scoreboard.adapters` (C11) | file missing |

The fixture files are hand-written from the GitHub REST docs shapes (release: `id`, `tag_name`, `html_url`, `upload_url`, `assets[{id, name}]`). Say so in a header comment in each test (they are not recorded from a live call; the nightly PB-22 checks the live API).

## 7. Edge cases, what not to do, gates

Edge cases:
- An owner publish while a cleanup is pending cannot happen (withdrawn is terminal).
- A worker crash after `create_release` and before any upload → the next run finds the release by tag and uploads both (PB-4a covers a partial one).
- A worker crash while it holds a lease → the row is due again after `LEASE_S`.
- A release that exists on GitHub for a row in state `private` (a manual upload) → at publish time the digest rule decides: equal → `published`, different → `release_conflict`.
- `last_error` is always sanitized and at most 512 chars.

What not to do:
- Do not call GitHub or the bucket outside the two ports. The core never imports an adapter (hexagonal; C11).
- Do not write the bucket. The scoreboard credentials are read-only (PB-D8).
- Do not upload before the digest check (PB-3).
- Do not put model outputs, url4 text or any request/response content into the release body (PB-D9).
- Do not log the GitHub token, the App key, the S3 secret, or author emails.
- Do not delete the `ReportedResult` or the head on takedown. The row stays, with the marker (PB-H4).
- Do not add a migration (§5), a `/metrics` route, or portal code (PB-21 is SDK-replay's; OD-6).
- Do not import from `apps/aigateway` (copy `sigv4.py`; do not import it). Never import `screamingface`.
- AIGateway credentials: this unit touches none. No OS keychain.

Overlap with SB-grants (same wave 4): see §2 "Integration notes". SB-grants merges first; do not change its blocks.

Gates: from the repo root `uv run .claude/scripts/run_gates.py scoreboard --base "$(git merge-base HEAD e14-reproducible-submission-spec)"`. The PostgreSQL module: `SCOREBOARD_TEST_DATABASE_URL=postgres://scoreboard:scoreboard@localhost:5432/scoreboard_test uv run pytest tests/unit/scores/test_publish_lease_postgres.py -v` against `postgres:17-alpine` (as `scoreboard-tests.yml:131-160`).

## 8. Verification (definition of done)

1. The gate command exits 0; the append-only check passes.
2. `uv run pytest tests/unit/publish tests/unit/guards/test_publish_layering.py -v`: every row of §6 green.
3. The PostgreSQL module is green with the database set, and it is listed in the CI job (the guard test is green).
4. `uv run pytest -q`: the whole old suite green, unchanged.
5. In the ledger: one rendered release body from the PB-7 test, pasted as text.
6. No chart file is in the diff (`git diff --name-only "$(git merge-base HEAD e14-reproducible-submission-spec)" -- apps/scoreboard/charts` is empty; D6). The chart is unit WIRING's.
7. Design review (Opus) with this plan as the rubric, plus the `sf-code-review` security review (test-plan §5 "Security"). Then commit on `unit/SB-publish` for the integrator (D1). No PR.

## 9. Open decisions and spec gaps

- **OD-6 (portal, open).** The PRD delta lists a portal "Published" link and a "Withdrawn" marker; PB-21 (SDK-replay) names "portal links". No scoreboard unit owns the portal part, and no API field carries the state on the leaderboard row. This unit adds no portal code. The user must name the unit that adds `publication_state` to the leaderboard row and the portal markers.

## 10. Decided

- **OD-1 (archive digest) — Decided: D7 X-16.** `archive_sha256 == sha256(entries.jsonl.gz bytes)` (gzip `mtime=0`, `compresslevel=9`, the GW-freeze rule). Known limit: the manifest bytes are not covered by a receipt digest, so a changed manifest in the bucket is not detected. Record it in the ledger.
- **OD-2 (disabled mode) — Decided: D5.** Production runs `cloudflare_headers`, so publish works there. The `disabled` dev/local fallback answers 503 `publish_unavailable` (PB-2a).
- **OD-3 (owner retry after an integrity failure) — decided (default).** 409 `not_publishable` with the reason `integrity_failure`.
- **OD-4 (admin in disabled mode) — Decided: D5.** The admin allowlist works only in `cloudflare_headers`; the `disabled` fallback answers 503 `admin_unavailable` (PB-12a).
- **OD-5 (DRY) — Decided: D7 X-23.** SigV4 is copied into `adapters/sigv4.py`. No shared package.
- **OD-7 (withdraw without a version) — decided (default).** 409 `not_publishable` `no_cache_version`.
- **G1 — decided (default).** The asset download call (`GET /repos/{o}/{r}/releases/assets/{id}`) is added to C7.
- **G2 — decided (default).** "Cleanup pending" is `state = 'withdrawn' AND next_attempt_at IS NOT NULL`; no `release_delete_pending` column.
- **G3 — decided (default).** The repo name is the setting `github_repo`.
- **G4.** Ed25519 is not used in this unit; the GitHub App JWT is RS256 with PyJWT inside the GitHub adapter only.
- **Error body — Decided: D7 X-8.** `{"detail": {"code", "message", ...}}` for every new error.
- **Metrics — Decided: D7 X-15.** The counters and gauges stay in process; no `/metrics` route.
