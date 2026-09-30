# Plan — GW-freeze: freeze, signed receipt, bucket archive (OME-1307, E14b)

- **Spec (rubric):** `docs/spec/2026-09-29-e14-reproducible-submission/` — `prd/cache-version-store.md`
  §3.1 (Freeze, CV-H2, CV-H2b, CV-H3, CV-H6), §3.2 (CV-E1, CV-E2, CV-E3, CV-E5), §3.3 (CV-D2, CV-D3,
  CV-D4, CV-D7, CV-D12), §4, §7; `erd.md` §3.3–§3.6, §5; `contracts.md` C2b, C3, C8a, DR-1, DR-3, DR-4.
- **Component:** `apps/aigateway` only.
- **Delivery (D1):** all E14 units land on the one branch `e14-reproducible-submission-spec`.
  There is no per-unit PR, no Linear issue and no per-unit CI merge gate. Build this unit in a
  temporary worktree on branch `unit/GW-freeze`, made from the HEAD of the e14 branch after the
  wave-1 integration (so GW-capture is in it):
  `git worktree add .claude/worktrees/unit-GW-freeze e14-reproducible-submission-spec`, then, in
  that worktree, `git checkout -B unit/GW-freeze e14-reproducible-submission-spec`. Commit on
  `unit/GW-freeze` only. After wave 2, the integrator merges the unit branches into the e14 branch
  in sequence and runs the gates.
- **Plan:** `docs/plan/2026-09-29-e14-reproducible-submission/GW-freeze.md` (this file).
- **Ledger:** `docs/work/2026-09-29-e14-gw-freeze.md` (use the real start date; `ticket: unfiled`).
- **Loop:** `sdlc-python`; companion skill `tortoise-dev` (mandatory).
- **Wave:** 2 (with SB-meta, SB-registry, ENG-freeze, SDK-meta). **Size:** 5–6 d. **Language:** ASD-STE100.

## 0. Integration notes (D2)

- Shared files with other wave-2 units: none. SB-meta and SB-registry change `apps/scoreboard`,
  ENG-freeze changes `apps/screamingface-engine` and `.claude/scripts/check_layering.py`, SDK-meta
  changes `packages/screamingface`. This unit changes `apps/aigateway` only.
- This unit builds on GW-capture (wave 1, merged). It changes GW-capture files additively:
  `core/cache_versions/ports.py`, `__init__.py`, `stats.py`, `config.py`, `main.py`,
  `DEPLOYMENT.md`, and it APPENDS fixtures to `tests/unit/cache_versions/conftest.py`.
- GW-replay (wave 3) later changes `wiring.py`, `ports.py`, `stats.py`, `config.py`, `main.py`,
  `DEPLOYMENT.md` and appends to `conftest.py`.
- WIRING (wave 5) owns the aigateway chart, the Secret templates, the Garage bucket and prefix,
  the bucket write credentials and the receipt key generation helper (D6). This unit only adds
  the settings that those values feed.

## 1. Scope

### 1.1 Test ids this unit owns

| Id | Test name (exact) | Level |
|---|---|---|
| CV-7 | `test_freeze_copies_full_request_and_response_for_each_call` | route (TestClient, SQLite) |
| CV-8 | `test_freeze_is_idempotent_same_vid_same_sha` (+ Postgres race twin `test_concurrent_freezes_make_one_version`) | route + integration (Postgres) |
| CV-9 | `test_freeze_of_other_accounts_trace_is_404` | route (TestClient, two jwt accounts) |
| CV-10 | `test_freeze_counts_pruned_row_as_missing_partial` | route |
| CV-11 | `test_freeze_never_stores_error_outcome_as_blob` | unit (fake store) |
| CV-12 | `test_archive_bytes_are_canonical_and_hash_matches` (Hypothesis property) | unit |
| CV-13 | `test_receipt_is_eddsa_jws_with_required_claims_and_kid` | unit |
| CV-14 | `test_freeze_too_large_413_and_nothing_written` (table: entry cap, archive-bytes cap) | route |
| CV-15 | `test_freeze_unknown_trace_404` | unit (fake store) |
| CV-22 | `test_export_writes_pair_and_sets_archived` | integration (Postgres + MinIO testcontainers) |
| CV-23 | `test_export_retries_when_bucket_down_replay_still_works` | unit (fake archive store, fake clock) |
| CV-25 | `test_receipt_signed_with_rotated_key_verifies_with_both_kids` | unit |
| CV-27 | `test_late_freeze_after_six_months_is_complete` | route |

Support tests (no PRD id): `test_archive_store.py` (the two adapters),
`test_freeze_route_contract.py` (C2b status codes and error bodies, the kill switch 503),
`test_cache_versions_settings.py` (startup validation). They keep coverage; they own no PRD row.

### 1.2 Out of scope

- The capture hook and the five tables (GW-capture, merged).
- Replay: lookup, grant verification, STAGE 0 (GW-replay). CV-23's "replay still works" part is
  asserted here as "the version rows stay readable and complete while the bucket is down". The
  replay-level proof is GW-replay's CV-16.
- The engine proxy route (ENG-freeze), the SDK freeze call (SDK-submit), the scoreboard receipt
  verifier (SB-submit), the scoreboard archive reader (SB-publish, C8b).
- Chart, Garage bucket and Kubernetes Secret provisioning, `values-prod.yaml`, the scoreboard's
  read-only bucket key, the `AIGATEWAY_RECEIPT_SIGNING_KEY` Secret and the Ed25519 key helper. They
  belong to WIRING (wave 5, D6). See `WIRING.md`.
- A version GC (`erd.md` §3.6: v1 has none).

## 2. Depends on

- **Units merged first:** GW-capture (tables, models, `CaptureStats`, `cache_versions_enabled`).
- **Contracts implemented:** C2b (gateway route `POST /v1/cache-versions`), C3 (receipt: the gateway
  signs), C8a (archive write, bucket and filesystem adapters).
- **Contracts consumed:** C2b auth — the existing auth modes; the account comes from the identity
  headers the engine forwards (`core/auth/middleware.py:34-46`). In production the gateway runs
  `cloudflare_headers` (`charts/aigateway/values-prod.yaml:18`, D5): the account is the verified
  `X-User-Email` (lowercased), after the peer check. `disabled` is a dev/local fallback only.
- **Later consumers:** ENG-freeze (proxies C2b byte for byte), SB-submit (verifies C3), SB-publish
  (reads the C8a objects and checks `sha`).

## 3. Files

### 3.1 New files

| Path | Purpose | Imitate |
|---|---|---|
| `apps/aigateway/src/aigateway/core/cache_versions/archive.py` | Pure canonical archive writer + manifest (§4.4) | `core/request_cache/snapshot_export.py:127-160` (`_HashingSink`), `core/request_cache/canonical.py:87-114` |
| `apps/aigateway/src/aigateway/core/cache_versions/freeze.py` | `FreezeService` (§4.5), depends on ports only | `core/request_cache/global_plan.py` (pure core), `routes/chat_cache_stage.py:139-209` (closed outcomes) |
| `apps/aigateway/src/aigateway/core/cache_versions/freeze_store.py` | Adapter `TortoiseFreezeStore` (implements `FreezeStore` and `ExportStore`) | `core/request_cache/store.py:218-350` (savepoint + `IntegrityError` outside the block) |
| `apps/aigateway/src/aigateway/core/cache_versions/receipt.py` | Adapter `Ed25519ReceiptSigner` (PyJWT, EdDSA) | `core/auth/jwt.py:1-33` |
| `apps/aigateway/src/aigateway/core/cache_versions/archive_store.py` | Adapters `S3VersionArchiveStore`, `FilesystemVersionArchiveStore` | `core/object_store.py:106-183`, `core/sigv4.py:107` |
| `apps/aigateway/src/aigateway/core/cache_versions/exporter.py` | `CacheVersionExporter` (owned outbox task) | `core/snapshot_scheduler.py:60-140` |
| `apps/aigateway/src/aigateway/core/cache_versions/wiring.py` | `build_cache_version_services(settings, stats) -> CacheVersionServices` (composition, keeps `main.py` short) | `core/snapshot_publish.py:34-87` |
| `apps/aigateway/src/aigateway/routes/cache_versions.py` | `POST /v1/cache-versions` | `routes/chat.py:406-420` (error `detail` shape) |
| `apps/aigateway/tests/unit/cache_versions/test_receipt.py` | CV-13, CV-25 | `tests/unit/auth/` jwt tests |
| `apps/aigateway/tests/unit/cache_versions/test_archive.py` | CV-12 | — |
| `apps/aigateway/tests/unit/cache_versions/test_freeze_service.py` | CV-11, CV-15 | fake-store style of `tests/unit/test_chat_global_cache_route.py:130-190` |
| `apps/aigateway/tests/unit/cache_versions/test_freeze_route.py` | CV-7, CV-8, CV-9, CV-10, CV-14, CV-27 | `tests/unit/cache_versions/test_capture_route.py` (GW-capture) |
| `apps/aigateway/tests/unit/cache_versions/test_freeze_route_contract.py` | support | same |
| `apps/aigateway/tests/unit/cache_versions/test_version_exporter.py` | CV-23 | `tests/unit/test_cache_snapshot_*.py` (fake clock, fake store) |
| `apps/aigateway/tests/unit/cache_versions/test_archive_store.py` | support | `tests/unit/test_object_store.py:1-60` (MockTransport) |
| `apps/aigateway/tests/unit/cache_versions/test_cache_versions_settings.py` | support | `tests/unit/test_cache_snapshot_settings.py` |
| `apps/aigateway/tests/integration/test_cache_version_freeze_postgres.py` | CV-8 race twin + freeze NFR (step 15b) | `tests/integration/test_global_cache_store_postgres.py:143-150` |
| `apps/aigateway/tests/integration/test_cache_version_export_postgres.py` | CV-22 | same, plus `testcontainers.minio.MinioContainer` |

### 3.2 Changed files

| Path | Change |
|---|---|
| `apps/aigateway/src/aigateway/core/cache_versions/ports.py` | Add the freeze and archive ports and value types (§4.2). |
| `apps/aigateway/src/aigateway/core/cache_versions/__init__.py` | Re-export the new port names only. |
| `apps/aigateway/src/aigateway/core/cache_versions/stats.py` | Add `freezes: Counter[str]` (by `created`/`reused`/`not_found`/`too_large`), `missing_total: int`, `export_pending: int`, `export_failures: int`, `export_digest_mismatches: int`. |
| `apps/aigateway/src/aigateway/config.py` | New settings + `_validate_cache_versions` (§4.1). |
| `apps/aigateway/src/aigateway/main.py` | In `create_app`: `services = build_cache_version_services(settings, app.state.capture_stats)`; `app.state.cache_version_freezer = services.freezer`; `app.state.cache_version_exporter = services.exporter` (may be `None`); `app.include_router(cache_versions.router)` next to `chat.router` (line 472). In `_lifespan` next to the snapshot scheduler (line 241-257): start the exporter when it is not `None`; stop it in `finally`. |
| `apps/aigateway/pyproject.toml` | `[dependency-groups].dev`: change `"testcontainers[postgres]==4.15.0"` to `"testcontainers[postgres,minio]==4.15.0"`; add `"hypothesis>=6.100"` (OD-F7). |
| `apps/aigateway/uv.lock` | `uv lock` (the CI runs `uv lock --check`). |
| `apps/aigateway/DEPLOYMENT.md` | New section "Cache versions: freeze, receipt, archive": the route, the error codes, the settings of §4.1, the key form (standard base64 of the raw 32-byte Ed25519 private key; the public key is standard base64 of the raw 32-byte public key; `kid = sha256(raw public key).hexdigest()[:16]`, D7 X-4), the bucket layout `cache-versions/<vid>/…`, that objects are written once, and that server-side encryption is a bucket setting (OD-F5). For key generation and the chart values, write one line that points to the WIRING key helper and chart (D6). Do not write a key-generation script in this unit. |

## 4. Signatures and data shapes

### 4.1 Settings (`config.py`)

```python
receipt_signing_key: SecretStr | None = Field(default=None, validation_alias="AIGATEWAY_RECEIPT_SIGNING_KEY")
cache_version_max_entries: int = Field(default=20_000, gt=0, validation_alias="AIGW_CACHE_VERSION_MAX_ENTRIES")
cache_version_max_archive_bytes: int = Field(default=1_500_000_000, gt=0, validation_alias="AIGW_CACHE_VERSION_MAX_ARCHIVE_BYTES")
cache_version_archive_backend: Literal["none", "s3", "filesystem"] = Field(default="none", validation_alias="AIGW_CACHE_VERSION_ARCHIVE_BACKEND")
cache_version_archive_dir: str | None = Field(default=None, validation_alias="AIGW_CACHE_VERSION_ARCHIVE_DIR")
cache_version_s3_endpoint_url: str | None = Field(default=None, validation_alias="AIGW_CACHE_VERSION_S3_ENDPOINT_URL")
cache_version_s3_bucket: str = Field(default="screamingface-cache-versions", validation_alias="AIGW_CACHE_VERSION_S3_BUCKET")
cache_version_s3_region: str = Field(default="garage", validation_alias="AIGW_CACHE_VERSION_S3_REGION")
cache_version_s3_access_key: SecretStr | None = Field(default=None, validation_alias="AIGW_CACHE_VERSION_S3_ACCESS_KEY")
cache_version_s3_secret_key: SecretStr | None = Field(default=None, validation_alias="AIGW_CACHE_VERSION_S3_SECRET_KEY")
cache_version_s3_timeout_s: float = Field(default=120.0, gt=0, allow_inf_nan=False, validation_alias="AIGW_CACHE_VERSION_S3_TIMEOUT_S")
cache_version_export_poll_s: float = Field(default=30.0, gt=0, allow_inf_nan=False, validation_alias="AIGW_CACHE_VERSION_EXPORT_POLL_S")
```
`@model_validator(mode="after") _validate_cache_versions` (imitate `config.py` `_validate_cache_snapshot`):
- Do NOT refuse startup when `cache_versions_enabled` is on and the signing key is absent. WHY: the
  GW-capture tests turn the flag on without a key, and the append-only gate forbids editing them.
  Instead, wiring (§4.10) logs a WARNING and leaves the freezer `None`, and the route answers
  `503 capture_disabled` (capture still runs).
- backend `s3` → endpoint, access key and secret key are required (list the missing names).
- backend `filesystem` → `cache_version_archive_dir` is required.
- NEVER echo a key value. Do not validate the key CONTENT here (same rule as `secret_key`,
  `config.py:88-99`); `Ed25519ReceiptSigner.from_base64` does it at wiring time.

### 4.2 Ports (`core/cache_versions/ports.py`, additions)

```python
CoverageStatus = Literal["complete", "partial"]

class TraceNotCaptured(LookupError): ...            # → 404 trace_not_captured
class CacheVersionTooLarge(ValueError):              # → 413 cache_version_too_large
    def __init__(self, limit: Literal["entries", "archive_bytes"]) -> None: ...
class VersionAlreadyExists(Exception): ...           # adapter → service, on the unique race
class ArchiveTooLarge(ValueError): ...               # raised by the archive sink
class ArchiveStoreError(RuntimeError): ...           # message carries no credential

@dataclass(frozen=True, slots=True)
class ReceiptClaims:
    sub: str; vid: UUID; tid: str; sha: str; n: int; c: int; cov: CoverageStatus

class ReceiptSigner(Protocol):
    @property
    def kid(self) -> str: ...
    def sign(self, claims: ReceiptClaims) -> str: ...

@dataclass(frozen=True, slots=True)
class CaptureRow:
    ordinal: int; key_hash: str | None; outcome: str; response_json: str | None

@dataclass(frozen=True, slots=True)
class LiveAnswer:
    response_json: str; metadata_json: str | None

@dataclass(frozen=True, slots=True)
class StoredVersion:
    id: UUID; owner_account_id: str; trace_id: str; status: str
    entry_count: int; call_count: int; missing_count: int
    coverage_status: CoverageStatus; archive_sha256: str; archive_key: str; created_at: datetime

@dataclass(frozen=True, slots=True)
class NewBlob:
    sha256: str; request_json: str; response_json: str; metadata_json: str | None; size_bytes: int

@dataclass(frozen=True, slots=True)
class NewEntry:
    key_hash: str; blob_sha256: str; first_ordinal: int   # a value field; the DB column is blob_id (D8)

class FreezeStore(Protocol):
    async def find_version(self, owner_account_id: str, trace_id: str) -> StoredVersion | None: ...
    async def load_capture(self, account_id: str, trace_id: str) -> list[CaptureRow]: ...   # ORDER BY ordinal
    async def load_prompts(self, key_hashes: Collection[str]) -> dict[str, str]: ...       # key_hash → request_json
    async def load_live_answers(self, key_hashes: Collection[str]) -> dict[str, LiveAnswer]: ...
    async def load_blob_metadata(self, shas: Collection[str]) -> dict[str, str | None]: ...  # existing blobs only: sha256 → metadata_json
    async def insert_version(self, version: StoredVersion, blobs: Sequence[NewBlob], entries: Sequence[NewEntry]) -> None: ...  # raises VersionAlreadyExists

class ExportStore(Protocol):
    async def list_frozen(self, limit: int) -> list[StoredVersion]: ...     # ORDER BY created_at
    async def count_frozen(self) -> int: ...
    async def load_archive_entries(self, version_id: UUID) -> list[ArchiveEntry]: ...  # ORDER BY first_ordinal
    async def mark_archived(self, version_id: UUID) -> None: ...            # UPDATE … WHERE status='frozen'

class VersionArchiveStore(Protocol):
    async def put_once(self, key: str, path: Path, *, sha256_hex: str) -> Literal["written", "exists"]: ...

@dataclass(frozen=True, slots=True)
class FreezeResult:
    created: bool; version_id: UUID; entry_count: int; call_count: int; missing_count: int
    coverage_status: CoverageStatus; archive_sha256: str; receipt: str

class CacheVersionFreezer(Protocol):
    async def freeze(self, *, account_id: str, subject: str, trace_id: str) -> FreezeResult: ...
```
`ArchiveEntry` is defined HERE in `ports.py` (the shape is in §4.4). `archive.py` imports `ArchiveEntry` and
`StoredVersion` from `ports.py`. `ports.py` never imports `archive.py` (that would be an import cycle).

### 4.3 Receipt signer (`core/cache_versions/receipt.py`) — C3

```python
class Ed25519ReceiptSigner:
    def __init__(self, private_key: Ed25519PrivateKey, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None
    @classmethod
    def from_base64(cls, secret: SecretStr, **kw) -> Ed25519ReceiptSigner
    @property
    def kid(self) -> str          # sha256(raw 32-byte public key).hexdigest()[:16]  (Decided: D7, X-4)
    def sign(self, claims: ReceiptClaims) -> str
```
- `from_base64`: `raw = base64.b64decode(value, validate=True)`; `len(raw) == 32` else
  `RuntimeError("AIGATEWAY_RECEIPT_SIGNING_KEY must be base64 of a 32-byte Ed25519 private key")`.
  The message never holds the value. Catch `binascii.Error`/`ValueError` the same way.
- `sign` returns `jwt.encode(payload, self._key, algorithm="EdDSA", headers={"kid": self.kid})`
  with payload EXACTLY
  `{"iss": "aigateway", "aud": "scoreboard", "sub": claims.sub, "vid": str(claims.vid), "tid": claims.tid, "sha": claims.sha, "n": claims.n, "c": claims.c, "cov": claims.cov, "iat": int(now().timestamp())}`.
  No `exp` (C3: the receipt attests a fact about an immutable version).
- PyJWT 2.13.0 and cryptography 50.0.1 are already runtime dependencies (`pyproject.toml`). No new
  runtime dependency.
- `sub` is `current.username`. In production (`cloudflare_headers`, D5) it is the lowercased
  verified email (`core/auth/cloudflare_identity.py:74-82`). The scoreboard compares it with its own
  verified `X-User-Email` (also `cloudflare_headers` in production, D5). In the dev/local fallback
  `disabled` it is `"anonymous"` (`middleware.py:22-31`); keep that behaviour.
- Key form (Decided: D7, X-4): the private key is standard base64 of the raw 32 bytes; the
  scoreboard's public-key map is JSON `{kid: <base64 of the raw 32-byte public key>}` with the kid
  of this signer. No PEM.

### 4.4 Archive (`core/cache_versions/archive.py`) — pure, erd §3.5

```python
ARCHIVE_SCHEMA: Final = "screamingface.cache-version.v1"
ENTRIES_OBJECT: Final = "entries.jsonl.gz"
MANIFEST_OBJECT: Final = "manifest.json"
def archive_prefix(version_id: UUID) -> str      # f"cache-versions/{version_id}/"

# ArchiveEntry lives in ports.py (§4.2):
# @dataclass(frozen=True, slots=True)
# class ArchiveEntry:
#     key_hash: str; first_ordinal: int; request: Any; response: Any; metadata: Any | None

@dataclass(frozen=True, slots=True)
class ArchiveDigest:
    sha256: str; size_bytes: int

def write_entries(entries: Iterable[ArchiveEntry], sink: BinaryIO | None, *, max_bytes: int) -> ArchiveDigest
def manifest_bytes(version: StoredVersion) -> bytes
def blob_sha256(request: Any, response: Any) -> str   # canonical_digest({"request": request, "response": response})
```
- `write_entries`: sort by `(first_ordinal, key_hash)`; for each entry write
  `canonical_material({"key_hash": …, "first_ordinal": …, "request": …, "response": …, "metadata": …}) + "\n"`
  (UTF-8) into `gzip.GzipFile(filename="", mode="wb", fileobj=tee, compresslevel=9, mtime=0)`.
  `tee` hashes and counts every COMPRESSED byte and forwards to `sink` (or drops the bytes when `sink`
  is `None`, which is what the freeze uses). When the count passes `max_bytes`, raise `ArchiveTooLarge`.
  Return the sha256 of the compressed bytes. `archive_sha256` = this value (Decided: D7, X-16:
  sha256 of the gzip bytes, `mtime=0`, `compresslevel=9`; SB-publish uses the same rule).
- `manifest_bytes`: `canonical_material({...}).encode("utf-8")`, no trailing newline, with the eleven
  keys of `erd.md` §3.5: `schema`, `version_id` (str), `trace_id`, `created_at`
  (`created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`), `entry_count`, `call_count`,
  `missing_count`, `coverage_status`, `entries_sha256` (= `archive_sha256`),
  `parameter_contract_revision` (`global_keys.PARAMETER_CONTRACT_REVISION`), `key_revision`
  (`global_keys.KEY_REVISION`).
- Reuse `core/request_cache/canonical.py` (`canonical_material`, `canonical_digest`). Do not write a
  second canonical form (its docstring, lines 7-12, explains why).

### 4.5 `FreezeService` (`core/cache_versions/freeze.py`)

```python
class FreezeService:
    def __init__(self, *, store: FreezeStore, signer: ReceiptSigner, stats: CaptureStats,
                 max_entries: int, max_archive_bytes: int,
                 on_frozen: Callable[[], None] | None = None,
                 new_id: Callable[[], UUID] = uuid4,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None
    async def freeze(self, *, account_id: str, subject: str, trace_id: str) -> FreezeResult
```
Algorithm (one call):
1. `existing = await store.find_version(account_id, trace_id)`. If found: return
   `FreezeResult(created=False, …stored values…, receipt=sign(claims from the stored row))`
   (CV-D3: same `vid`, same `sha`; `iat` may differ).
2. `rows = await store.load_capture(account_id, trace_id)`. Empty → raise `TraceNotCaptured`
   (CV-E1; another account's rows are invisible, so CV-D2 gives the same 404).
3. `keys = {r.key_hash for r in rows if r.key_hash}`; `prompts = await store.load_prompts(keys)`;
   `live = await store.load_live_answers({r.key_hash for r in rows if r.key_hash and r.outcome in ("hit", "stored")})`.
4. For `position, row in enumerate(rows)` (position = `first_ordinal`; OD-F3):
   - missing when: `row.outcome == "error"` (CV-D7); `row.key_hash is None`; the prompt is absent;
     `row.outcome in ("hit", "stored")` and `row.key_hash not in live` (CV-E2); an inline outcome with
     `response_json is None`.
   - else `request = json.loads(prompts[k])`; `response = json.loads(inline or live.response_json)`;
     `metadata = json.loads(live.metadata_json)` only for `hit`/`stored` when present, else `None`.
     A `json.JSONDecodeError` makes the row missing (log the key prefix only).
   - `sha = blob_sha256(request, response)`. If `(k, sha)` was seen, skip (not missing, not a new
     entry). Else keep `ArchiveEntry(k, position, request, response, metadata)`.
4b. Blob metadata reconciliation. `existing = await store.load_blob_metadata({e.sha for e in entries})`.
   For each entry whose sha is in `existing`, replace its `metadata` with
   `json.loads(existing[sha]) if existing[sha] is not None else None`. WHY: blobs are shared across versions
   and `insert_version` keeps the FIRST blob row (`ignore_conflicts`). The exporter rebuilds the archive from
   the stored blob rows (§4.9). Without this step, a shared blob with other metadata gives other archive
   bytes, the exporter sees a digest mismatch, and the version is never archived.
5. `missing_count`, `entry_count = len(entries)`, `call_count = len(rows)`,
   `coverage_status = "complete" if missing_count == 0 else "partial"`.
6. `entry_count > max_entries` → raise `CacheVersionTooLarge("entries")` (before any write).
7. `digest = write_entries(entries, None, max_bytes=max_archive_bytes)`; `ArchiveTooLarge` →
   raise `CacheVersionTooLarge("archive_bytes")`.
8. Build `NewBlob`s (`request_json = canonical_material(request)`, `response_json = canonical_material(response)`,
   `metadata_json = canonical_material(metadata) or None`, `size_bytes` = UTF-8 length of the two JSON
   texts) and `NewEntry`s. `vid = new_id()`, `status="frozen"`,
   `archive_key=archive_prefix(vid)`, `created_at=now()`.
9. `await store.insert_version(...)`. On `VersionAlreadyExists`: re-read with `find_version` and return
   step 1's result (the concurrent winner).
10. `on_frozen()` if set (wakes the exporter); stats; sign; return `created=True`.

Late ledger rows (CV-D4): a version never changes after insert. Nothing reads capture rows again.

### 4.6 Adapter `TortoiseFreezeStore` (`core/cache_versions/freeze_store.py`)

- `load_prompts` / `load_live_answers`: query in chunks of 500 keys (`key_hash__in`), because SQLite
  limits bound variables. `load_live_answers` reads `RequestCacheEntry` (`core/request_cache/models`)
  with `.only("key_hash", "response_json", "metadata_json")` and ignores rows with a non-NULL
  `expires_at` in the past (same rule as `store.py:161-163`).
- `insert_version`: `async with in_transaction():` → `CacheVersionBlob.bulk_create(blobs, ignore_conflicts=True, batch_size=500)`
  → `CacheVersion.create(...)` → `CacheVersionEntry.bulk_create(entries, batch_size=500)`. Catch
  `IntegrityError` OUTSIDE the `async with` and raise `VersionAlreadyExists` (copy the
  AIDEV-NOTE of `store.py:251-256`; the order matters on Postgres).
- `load_archive_entries`: `CacheVersionEntry.filter(version_id=…).select_related("blob").order_by("first_ordinal")`;
  map to `ArchiveEntry(request=json.loads(blob.request_json), response=json.loads(blob.response_json), metadata=json.loads(blob.metadata_json) if … else None)`.
- `load_blob_metadata`: `CacheVersionBlob.filter(sha256__in=chunk).values_list("sha256", "metadata_json")`,
  chunks of 500.
- Entries: create with `CacheVersionEntry(version_id=vid, key_hash=e.key_hash, blob_id=e.blob_sha256,
  first_ordinal=e.first_ordinal)` (the attribute and the column are both `blob_id`, D8; GW-capture §5).
- `mark_archived`: `CacheVersion.filter(id=vid, status="frozen").update(status="archived")`.

### 4.7 Route (`routes/cache_versions.py`) — C2b

```python
router = APIRouter()

class FreezeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")

class FreezeResponse(BaseModel):
    receipt: str
    cache_version_id: UUID
    entry_count: int
    call_count: int
    missing_count: int
    coverage_status: Literal["complete", "partial"]
    archive_sha256: str

@router.post("/v1/cache-versions", response_model=FreezeResponse, status_code=201)
async def freeze_cache_version(body: FreezeRequest, request: Request, response: Response, current: CurrentAccount) -> FreezeResponse
```
- `not settings.cache_versions_enabled` or `request.app.state.cache_version_freezer is None` → `HTTPException(503, detail={"code": "capture_disabled", "message": "cache versions are disabled on this gateway"})`.
- `freezer: CacheVersionFreezer = request.app.state.cache_version_freezer`;
  `await freezer.freeze(account_id=str(current.id), subject=current.username, trace_id=body.trace_id)`.
- `TraceNotCaptured` → `404 {"code": "trace_not_captured", "message": …}`;
  `CacheVersionTooLarge(limit)` → `413 {"code": "cache_version_too_large", "limit": limit, "message": …}`.
- `result.created is False` → `response.status_code = 200`.
- A bad body is `422` through the app's redacting handler (`main.py:273-282`).
- The route imports only `aigateway.core.cache_versions` (ports). It never imports a model or an adapter
  (the GW-capture boundary test enforces it).

### 4.8 Archive adapters (`core/cache_versions/archive_store.py`) — C8a

```python
class S3VersionArchiveStore:
    def __init__(self, config: S3ObjectStoreConfig, *, client_factory: Callable[[], httpx.AsyncClient] | None = None) -> None
    async def put_once(self, key: str, path: Path, *, sha256_hex: str) -> Literal["written", "exists"]

class FilesystemVersionArchiveStore:
    def __init__(self, root: Path) -> None
    async def put_once(self, key: str, path: Path, *, sha256_hex: str) -> Literal["written", "exists"]
```
- S3: signed `HEAD /<bucket>/<key>` first (`sigv4.authorization_header(method="HEAD", …, payload_sha256=EMPTY_PAYLOAD_SHA256)`,
  `sigv4.py:32,107`). 200 → `"exists"`. 404 → `S3ObjectStore(config, client_factory=…).put(key, path, sha256_hex=…)`
  → `"written"`. The PUT carries `X-Amz-Content-Sha256 = sha256_hex`, so the server refuses bytes that do
  not match (that is the "written bytes hash to `archive_sha256`" check of CV-H6). Any other status,
  `httpx.HTTPError` or `S3StorageError` → `ArchiveStoreError` (no credential in the message; never follow
  a redirect, `object_store.py:138-152`). WHY HEAD-then-PUT and not `If-None-Match: *`: C8a allows it
  and Garage support for conditional PUT is not proven (OD-F5).
- Filesystem: `target = root / key`; `target.exists()` → `"exists"`; else write to
  `target.with_suffix(target.suffix + ".tmp-<uuid4>")`, then `os.link(tmp, target)` (a link never
  overwrites; `FileExistsError` → `"exists"`), then remove the temp file. Run file I/O through
  `asyncio.to_thread`.

### 4.9 Exporter (`core/cache_versions/exporter.py`) — outbox by `status = 'frozen'`

```python
class CacheVersionExporter:
    def __init__(self, *, store: ExportStore, archive: VersionArchiveStore, stats: CaptureStats,
                 poll_interval_s: float, batch_size: int = 10,
                 base_backoff_s: float = 1.0, max_backoff_s: float = 300.0,
                 monotonic: Callable[[], float] = time.monotonic,
                 jitter: Callable[[], float] = lambda: random.uniform(0.0, 1.0),
                 spool_root: Path | None = None) -> None
    async def run_once(self) -> int          # number of versions archived in this pass
    def notify(self) -> None                  # sets an asyncio.Event; FreezeService.on_frozen calls it
    def start(self) -> None
    async def stop(self) -> None
```
- `run_once`: `stats.export_pending = await store.count_frozen()`; for each `v` in
  `await store.list_frozen(batch_size)` whose `next_attempt[v.id] <= monotonic()`:
  spool = `tempfile.mkdtemp(prefix="aigw-cv-", dir=spool_root)`; `entries = await store.load_archive_entries(v.id)`;
  write `entries.jsonl.gz` with `write_entries` inside `asyncio.to_thread`; if the digest is not
  `v.archive_sha256` → `stats.export_digest_mismatches += 1`, log ERROR with the version id,
  `next_attempt = now + max_backoff_s`, continue (never upload wrong bytes). Else write `manifest.json`
  (`manifest_bytes(v)`), then `put_once(prefix + ENTRIES_OBJECT, …, sha256_hex=digest.sha256)`, then
  `put_once(prefix + MANIFEST_OBJECT, …, sha256_hex=sha256(manifest))` (entries first, like
  `snapshot_publish.py:69-74`), then `mark_archived(v.id)`; `shutil.rmtree(spool)` in `finally`.
- Failure (`ArchiveStoreError`, `OSError`): `attempts[v.id] += 1`;
  `delay = min(max_backoff_s, base_backoff_s * 2 ** (attempts - 1)) + jitter()`;
  `next_attempt[v.id] = monotonic() + delay`; `stats.export_failures += 1`; log WARNING (version id,
  exception type). The version stays `frozen` (CV-E5). Backoff state is in memory; a restart retries at
  once (accepted).
- Loop: `while True: try run_once; except Exception: logger.exception(...)`; then
  `await asyncio.wait_for(self._wake.wait(), timeout=poll_interval_s)` (catch `TimeoutError`),
  `self._wake.clear()`. Owned task: `start()`/`stop()` exactly as `snapshot_scheduler.py:95-114`.

### 4.10 Wiring (`core/cache_versions/wiring.py`)

```python
@dataclass(frozen=True)
class CacheVersionServices:
    freezer: CacheVersionFreezer | None
    exporter: CacheVersionExporter | None

def build_cache_version_services(settings: Settings, stats: CaptureStats) -> CacheVersionServices
```
- `cache_versions_enabled` false → both `None` (the route answers 503 before it reads the freezer).
- Flag on but `receipt_signing_key` is `None` or blank → log WARNING
  `"cache versions: capture on, freeze off (AIGATEWAY_RECEIPT_SIGNING_KEY is not set)"`; both `None`.
- Signer: `Ed25519ReceiptSigner.from_base64(settings.receipt_signing_key)`; log
  `"cache version receipts ready kid=%s"` (the kid is public).
- Archive: `none` → exporter `None`; `s3` → `S3VersionArchiveStore(S3ObjectStoreConfig(endpoint_url=…, bucket=…, credentials=Credentials(…), timeout_s=settings.cache_version_s3_timeout_s))`;
  `filesystem` → `FilesystemVersionArchiveStore(Path(settings.cache_version_archive_dir))`.
- `FreezeService(..., on_frozen=exporter.notify if exporter else None)`.

## 5. Migrations

None. GW-capture's `0013_cache_versions.py` created all five tables (the gateway schema-foundation
unit). If a column is missing, STOP and ask; do not add `0014` in this unit.

## 6. TDD order (RED first)

Scaffold first (so RED fails on an assertion): ports, `archive.py` with `write_entries` raising
`NotImplementedError`, `FreezeService.freeze` raising `NotImplementedError`, the route returning 501,
the signer's `sign` returning `""`, wiring, settings. Commit with the ledger.

Shared arrangement: extend `tests/unit/cache_versions/conftest.py` only by ADDING new fixtures
(append at the end; the append-only gate allows appended code): `signing_key` (a fresh
`Ed25519PrivateKey`), `_freeze_env(monkeypatch, signing_key)` that sets
`AIGATEWAY_RECEIPT_SIGNING_KEY` (base64 raw private bytes), `AIGW_CACHE_VERSIONS_ENABLED=true`,
`AIGW_REQUEST_CACHE_ENABLED=true`; `freeze_client(_freeze_env, client)` logged in as admin. Seed runs
through the real chat route with a `traceparent` (GW-capture helpers), then call
`POST /v1/cache-versions`.

| Step | Id | File :: test | RED reason | GREEN |
|---|---|---|---|---|
| 1 | CV-13 | `test_receipt.py::test_receipt_is_eddsa_jws_with_required_claims_and_kid` | Decode with the public key via `jwt.decode(..., algorithms=["EdDSA"], audience="scoreboard")`; assert header `alg == "EdDSA"`, `kid == sha256(pub).hexdigest()[:16]`; claims equal exactly the §4.3 dict; no `exp`. Fails: `sign` returns `""`. | §4.3 |
| 2 | CV-25 | `test_receipt.py::test_receipt_signed_with_rotated_key_verifies_with_both_kids` | Two signers (old, new key). A kid map `{kid_old: pub_old, kid_new: pub_new}` picks the key by the header `kid` and verifies both receipts; the kids differ; a receipt does not verify under the other key. Fails until kid + sign work. | §4.3 |
| 3 | CV-12 | `test_archive.py::test_archive_bytes_are_canonical_and_hash_matches` | Hypothesis `@given` lists of `ArchiveEntry` (JSON-safe strategy: `st.recursive` over `None`, bools, ints, `st.floats(allow_nan=False, allow_infinity=False)`, `st.text(alphabet=st.characters(codec="utf-8"))`, dicts with such text keys). The list strategy uses `unique_by=lambda e: e.first_ordinal` (in a freeze each entry has its own position, so a duplicate `first_ordinal` cannot occur, and it would make the shuffle check depend on input order). Assert: two runs give byte-identical output and equal sha; a shuffled input gives the same bytes; `sha256(bytes) == digest.sha256`; `gzip.decompress` gives lines sorted by `first_ordinal` and each line is canonical (re-dump equals the line); the gzip header `MTIME` field (bytes 4-8) is zero. Plus `test_archive_cap_raises_archive_too_large`. Fails: `NotImplementedError`. | §4.4 |
| 4 | CV-15 | `test_freeze_service.py::test_freeze_unknown_trace_404` | `FakeFreezeStore` with no rows → `pytest.raises(TraceNotCaptured)`; nothing inserted. Fails: `NotImplementedError`. | §4.5 steps 1–2 |
| 5 | CV-11 | `test_freeze_service.py::test_freeze_never_stores_error_outcome_as_blob` | Rows: `stored` (live row present) + `error` (with a key and a prompt). Assert `missing_count == 1`, `entry_count == 1`, `coverage_status == "partial"`, and no `NewBlob` holds the error call. | §4.5 step 4 |
| 5b | support | `test_freeze_service.py::test_freeze_digest_uses_the_stored_blob_metadata` | `FakeFreezeStore.load_blob_metadata` returns metadata `M1` for the sha of the one entry, while the live row holds `M2`. Assert the result `archive_sha256` equals `write_entries([entry with metadata M1], None, …).sha256`. Fails before §4.5 step 4b (the digest uses `M2`). `FakeFreezeStore.load_blob_metadata` returns `{}` in every other test. | §4.5 step 4b |
| 6 | CV-7 | `test_freeze_route.py::test_freeze_copies_full_request_and_response_for_each_call` | Trace T via the route: H (hit, H pre-filled untraced), S (stored), B (opt-out bypass). `POST /v1/cache-versions {"trace_id": T}` → 201; body counts `call_count=3, entry_count=3, missing_count=0, coverage_status="complete"`. For each `CacheVersionEntry`: its blob `request_json` parses to the prompt material of that key (sha256 of `canonical_material(request)` equals `key_hash`), and `response_json` equals the answer the caller got (`H`/`S` = live row, `B` = inline). Fails: route 501. | §4.5, §4.6, §4.7, wiring |
| 7 | CV-8 | `test_freeze_route.py::test_freeze_is_idempotent_same_vid_same_sha` | Two POSTs: 201 then 200; equal `cache_version_id` and `archive_sha256`; the two receipts decode to equal `vid` and `sha`; `CacheVersion` count is 1. | §4.5 step 1 |
| 8 | CV-8 twin | `tests/integration/test_cache_version_freeze_postgres.py::test_concurrent_freezes_make_one_version` | Postgres; seed capture, prompt and live rows with the models; `asyncio.gather` two `FreezeService.freeze` for one trace → both results have one `version_id`; one `CacheVersion` row; no exception. Red run against the scaffold (`NotImplementedError`) recorded in the ledger. | §4.6 `VersionAlreadyExists` path |
| 9 | CV-9 | `test_freeze_route.py::test_freeze_of_other_accounts_trace_is_404` | Admin runs trace T. A provisioned user (`provisioned_user_factory`, `tests/conftest.py`) logs in and POSTs T → 404 `detail.code == "trace_not_captured"`; the admin POST still gives 201. | account filter in `load_capture` |
| 10 | CV-10 | `test_freeze_route.py::test_freeze_counts_pruned_row_as_missing_partial` | After the run, delete the live row of S (`RequestCacheEntry.filter(key_hash=…).delete()` through `client.portal.call`). Freeze → 201, `missing_count=1`, `coverage_status="partial"`, `entry_count=2`. | §4.5 step 4 |
| 11 | CV-27 | `test_freeze_route.py::test_late_freeze_after_six_months_is_complete` | After the run, move `created_at` of every capture, prompt and live row back 183 days (`.update(created_at=…)`). Freeze → complete, the same counts as CV-7. It proves that no input expires. (It can pass at once after step 6; show red by running it before step 6 GREEN.) | none new |
| 12 | CV-14 | `test_freeze_route.py::test_freeze_too_large_413_and_nothing_written` (parametrize: `AIGW_CACHE_VERSION_MAX_ENTRIES=2` with 3 entries; `AIGW_CACHE_VERSION_MAX_ARCHIVE_BYTES=64`) | 413 with `detail.code == "cache_version_too_large"` and the right `limit`; zero rows in `cache_version`, `cache_version_entry`, `cache_version_blob`. | §4.5 steps 6–7 |
| 13 | support | `test_freeze_route_contract.py` | 503 `capture_disabled` when the flag is off, and when the flag is on but no signing key is set (capture rows are still written in that case); 422 for an upper-case, short, or extra-field body; 401 without a token. | §4.7 |
| 14 | CV-23 | `test_version_exporter.py::test_export_retries_when_bucket_down_replay_still_works` | Real SQLite store with one frozen version (seed through `FreezeService`), `FlakyArchiveStore` that raises `ArchiveStoreError` 3 times then works, fake `monotonic` and `jitter=lambda: 0.0`. Call `run_once` while advancing the clock. Assert: status stays `frozen` after each failure; the retry delays are 1, 2, 4 s; the version's entries and blobs still load and equal the frozen content (replay reads Postgres, DR-3); after recovery status is `archived` and `export_pending` is 0. Plus `test_backoff_is_capped_at_five_minutes`. Fails: `run_once` not written. | §4.9 |
| 15 | CV-22 | `tests/integration/test_cache_version_export_postgres.py::test_export_writes_pair_and_sets_archived` | `AIGW_TEST_PG=1` gate; `pytestmark = pytest.mark.needs_postgres`; `PostgresContainer("postgres:16-alpine", driver=None)` and `MinioContainer()` (default image); `Credentials(region="us-east-1", …)` for MinIO; make the bucket with `minio.get_client().make_bucket(...)`. Freeze on Postgres, `run_once` with `S3VersionArchiveStore` at the MinIO endpoint. Assert both objects exist at `cache-versions/<vid>/…`; `sha256(entries bytes) == archive_sha256`; the manifest parses to the eleven keys; status `archived`; a second `run_once` writes nothing and a pre-written object is not overwritten (`"exists"`). | §4.8 S3 |
| 15b | NFR | `tests/integration/test_cache_version_freeze_postgres.py::test_freeze_of_5000_entries_is_at_most_10_s` | `test-plan.md` §5 "Freeze time ≤ 10 s for 5,000 entries" has no other owner. Seed 5,000 `stored` capture rows with prompt and live rows (4 KB response each) through the models; time one `FreezeService.freeze`; assert `elapsed <= 10.0` s and `entry_count == 5000`. No RED is possible for a budget test; record the measured time in the ledger. | none, or tune §4.6 chunk size |
| 16 | support | `test_archive_store.py` | S3 with `httpx.MockTransport`: HEAD 200 → no PUT; HEAD 404 → one signed PUT with the sha header; HEAD 403 → `ArchiveStoreError`; 3xx not followed. Filesystem: write, second call `"exists"` and bytes unchanged. | §4.8 |
| 17 | support | `test_cache_versions_settings.py` | Flag on + no key → the app starts and logs the WARNING (use `caplog`); s3 without endpoint → names the missing variables; a bad base64 key → `RuntimeError` at wiring with no value in the text. | §4.1, §4.3 |

## 7. Edge cases, what not to do, gates

### 7.1 Edge cases

- A trace whose every row is missing: a version with `entry_count=0`, `partial`. The archive is a valid
  empty gzip. Allowed (the SDK still gets a receipt).
- Two identical requests with two different answers in one run (CV-D6): two entries for one key; the
  replay rule (lowest `first_ordinal`) is GW-replay's.
- A `hit` row whose live row has a non-NULL, past `expires_at`: missing.
- The same blob in two versions: one `cache_version_blob` row (`ignore_conflicts`); the first metadata
  wins (the blob hash covers request + response only, `erd.md` §3.4).
- Production identity (D5): `cloudflare_headers`. Each verified email is its own account, so a
  freeze sees only that user's capture rows, and `sub` is that email.
- `auth_mode=disabled` (dev/local fallback only): all traces share the anonymous account;
  `sub = "anonymous"`. Keep that behaviour; do not design for it as a production path.
- Two gateway replicas export one version at the same time: both build the same bytes (the digest is
  checked first), so a second PUT after a HEAD race writes identical bytes; `mark_archived` is conditional
  (`WHERE status='frozen'`). Accepted.
- Residual race of §4.5 step 4b: two concurrent freezes of DIFFERENT traces insert one new blob sha with
  different metadata. The loser's digest then does not match its stored blobs; the exporter logs the
  mismatch and the version stays `frozen` (replay still works from Postgres). Accepted for v1; the
  `export_digest_mismatches` counter shows it.
- The receipt `sub` is lowercased in `cloudflare_headers` mode; the scoreboard must compare it the same
  way (spec gap SG-3; with D5 the scoreboard also reads the verified `X-User-Email`).

### 7.2 What not to do

- Do not add a migration. Do not change `request_cache_entries` or the global key.
- Do not store a receipt; sign on demand.
- Do not put the receipt signing key, the S3 secret or `AIGATEWAY_SECRET_KEY` in a log, an error
  message, an exception text, `repr`, or `credential_blobs`. The signing key comes from the env/Secret
  only. No OS keychain.
- Do not call the scoreboard. The gateway never knows about it (DR-2).
- Do not import across apps, and do not import `aigateway.plugins` from `core/cache_versions/`.
- Do not upload bytes whose sha differs from `archive_sha256`. Do not overwrite an object.
- Do not edit an existing test. Append to `conftest.py` only.
- Do not add a shared JWS package (Decided: D7, X-3).
- Do not change a chart, a Secret template or `values-prod.yaml` (WIRING, D6).

### 7.3 Gates

```bash
cd apps/aigateway
uv lock --check
uv run ruff check && uv run ruff format --check && uv run pyright
uv run python scripts/check_no_enterprise.py
uv run pytest --cov=aigateway --cov-fail-under=80 -q -m "not live and not needs_postgres"
AIGW_TEST_PG=1 uv run pytest -m needs_postgres -v
cd ../.. && uv run .claude/scripts/run_gates.py aigateway --base e14-reproducible-submission-spec
```

The `--base` is the e14 branch (D1), so the append-only check sees only this unit's change.

## 8. Verification and "done"

1. Every §1.1 row is green; GW-capture's CV-1..CV-6, CV-24, CV-26, CV-28 stay green.
2. The Docker lane (`AIGW_TEST_PG=1 -m needs_postgres`) runs CV-8 twin and CV-22 green (MinIO starts
   inside it; CI already has Docker for that step, `.github/workflows/aigateway-tests.yml:82-85`).
3. A manual contract check, recorded in the ledger: `curl -X POST :9105/v1/cache-versions` on a local
   gateway after one traced call returns 201 with the seven C2a fields, and a second call returns 200.
4. `run_gates.py aigateway --base e14-reproducible-submission-spec` green; `uv lock --check` green.
5. Conventional commits on `unit/GW-freeze`, no `Co-Authored-By`. No PR and no Linear issue (D1).
   The integrator merges the branch after wave 2.
6. `git diff e14-reproducible-submission-spec...HEAD --stat -- apps/aigateway/charts` prints nothing (D6).

## 9. Open decisions

None is open. The items below are closed:

- **OD-F1 — Decided: D7 (X-3).** No new shared package. Service-local PyJWT EdDSA code behind the
  `ReceiptSigner` port (about 40 lines).
- **OD-F2 — Decided: D7 (X-4).** `kid = sha256(raw public key).hexdigest()[:16]`, derived, no extra env
  var. Keys are standard base64 of the raw 32 bytes. The scoreboard's `SCOREBOARD_RECEIPT_PUBLIC_KEYS`
  map is JSON `{kid: b64}` with the same kid.
- **OD-F3 — decided (default).** `first_ordinal` is the 0-based position of the call in its trace, not
  the global capture `ordinal` (the global number would leak other traffic volume into a public archive).
- **OD-F4 — Decided: D7 (X-16).** `archive_sha256` is the sha256 of the gzip bytes (`mtime=0`, level 9).
  Known risk, accepted: a different zlib build can compress the same input to other bytes; the exporter
  then refuses to upload (digest mismatch, `export_digest_mismatches` counts it).
- **OD-F5 — decided (default).** Server-side encryption (C8a says "on") is a bucket setting (WIRING
  provisions the bucket, D6), not a request header; write-once uses HEAD-then-PUT, not `If-None-Match: *`.
- **OD-F6 — Decided: D6.** The chart, the Garage bucket `screamingface-cache-versions` and prefix, the
  scoreboard's read-only key, the `AIGATEWAY_RECEIPT_SIGNING_KEY` Secret, the bucket write credentials,
  `values-prod.yaml` and the key helper belong to WIRING (wave 5). This unit adds settings only.
- **OD-F7 — decided (default).** New dev dependencies `hypothesis` and the `minio` extra of
  `testcontainers`.
- **OD-F8 — Decided: D7 (X-8).** Error body shape `{"detail": {"code": …, "message": …, ...}}` (the
  gateway's existing shape, `routes/chat.py:409-420`). ENG-freeze maps it and SDK-submit maps the code.
- **Identity — Decided: D5.** Production is `cloudflare_headers`; `sub` is the verified lowercased email.
