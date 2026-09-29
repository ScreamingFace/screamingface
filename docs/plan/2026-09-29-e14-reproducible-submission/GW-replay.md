# Plan — GW-replay: grant verification and version lookup on the chat path (OME-1307, E14b)

- **Spec (rubric):** `docs/spec/2026-09-29-e14-reproducible-submission/` — `prd/cache-version-store.md`
  §3.1 (Lookup, CV-H4, CV-H5), §3.2 (CV-E4), §3.3 (CV-D6, CV-D9, CV-D10), §4, §7;
  `prd/replay-pinned-run.md` §3.3 (RP-D1, RP-D3, RP-D5, RP-D8), §7 (RP-5); `erd.md` §3.4 (replay rule);
  `contracts.md` C6 (gateway verifier), C9, C11, DR-2, DR-3.
- **Component:** `apps/aigateway` only.
- **Delivery (D1):** all E14 units land on the one branch `e14-reproducible-submission-spec`.
  There is no per-unit PR, no Linear issue and no per-unit CI merge gate. Build this unit in a
  temporary worktree on branch `unit/GW-replay`, made from the HEAD of the e14 branch after the
  wave-2 integration (so GW-capture and GW-freeze are in it):
  `git worktree add .claude/worktrees/unit-GW-replay e14-reproducible-submission-spec`, then, in
  that worktree, `git checkout -B unit/GW-replay e14-reproducible-submission-spec`. Commit on
  `unit/GW-replay` only. After wave 3, the integrator merges the unit branches into the e14 branch
  in sequence and runs the gates.
- **Plan:** `docs/plan/2026-09-29-e14-reproducible-submission/GW-replay.md` (this file).
- **Ledger:** `docs/work/<start-date>-e14-gw-replay.md` (`ticket: unfiled`).
- **Loop:** `sdlc-python`; companion skill `tortoise-dev` (mandatory).
- **Wave:** 3 (with SB-submit, ENG-replay, SDK-submit). **Size:** 3 d. **Language:** ASD-STE100.

## 0. Integration notes (D2)

- Shared files with other wave-3 units: none. SB-submit changes `apps/scoreboard`, ENG-replay
  changes `apps/screamingface-engine`, SDK-submit changes `packages/screamingface`. This unit
  changes `apps/aigateway` only.
- This unit builds on GW-capture (wave 1) and GW-freeze (wave 2), both merged. It changes their
  files additively: `core/cache_versions/ports.py`, `__init__.py`, `stats.py`, `wiring.py`,
  `config.py`, `main.py`, `routes/chat.py`, `DEPLOYMENT.md`, and it APPENDS fixtures to
  `tests/unit/cache_versions/conftest.py`.
- Cross-track contract (no shared file): ENG-replay (same wave) reads the `X-AIGW-Cache-Version`
  header, the `Cache-Status ... key="<prefix>"` member and the 403 body of §4.5. Both plans use the
  shapes in this file. The integrator does not need an order between the two.
- WIRING (wave 5) owns the aigateway chart value and the Secret for
  `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS` (D6). This unit adds the setting only.

## 1. Scope

### 1.1 Test ids this unit owns

| Id | Test name (exact) | Level |
|---|---|---|
| CV-16 | `test_valid_grant_hit_serves_version_without_provider_call` | route (TestClient) |
| CV-17 | `test_valid_grant_miss_falls_through_and_marks_miss` | route (TestClient) |
| CV-18 | `test_invalid_grant_rejects_403_with_closed_reason` (table: signature, expired, audience, unknown_version, subject) | unit (+ one route assertion) |
| CV-19 | `test_grant_subject_check_skipped_when_auth_disabled` | unit |
| CV-20 | `test_duplicate_key_replay_returns_lowest_ordinal` | unit (SQLite models) |
| CV-21 | `test_verified_grant_cached_60s` | unit |
| RP-5 | `test_gateway_rejects_grant_reused_by_other_subject` | route (two jwt accounts) |

Support tests (no PRD id): `test_version_hit_is_captured_with_inline_body` (the `version_hit`
capture row), `test_replay_settings.py` (public-key config), `test_replay_headers.py` (the header set
on hit, miss, stream), `test_replay_route.py::test_cloudflare_headers_subject_is_the_verified_email`
(the production identity path, D5).

### 1.2 Out of scope

- Grant minting and pin resolution (SB-grants). The engine's header carry and hit/miss counters
  (ENG-replay). The SDK `evaluate(replay=…)` (SDK-replay).
- A revocation list (DR-2 "change when"). Grant refresh (Decided: D4, no refresh).
- The chart value and the Secret for the grant public keys (WIRING, D6).
- Any change to the global cache key, the capture tables or the freeze.
- New migrations (GW-capture owns the schema).

## 2. Depends on

- **Units merged first:** GW-freeze (and so GW-capture). The route tests make a version through
  `POST /v1/cache-versions`.
- **Contracts implemented:** C9 gateway half (request header `X-AIGW-Cache-Replay`, response header
  `X-AIGW-Cache-Version: hit|miss`, `Cache-Status: aigateway; hit; detail=version; key="<prefix>"`, error
  `403 replay_grant_invalid` + `reason`); C6 verifier (gateway side); C11 row 4 (ports only).
- **Contracts consumed:** C6 grant format from SB-grants: compact JWS, `alg: EdDSA`, header `kid`,
  claims `{"iss":"scoreboard","aud":"aigateway","sub","vid","rid","iat","exp"}`.
- **Later consumers:** ENG-replay reads `X-AIGW-Cache-Version` and maps `403 replay_grant_invalid`
  (RP-13, RP-14). The engine already reads `Cache-Status` first
  (`apps/screamingface-engine/src/screamingface_engine/world/cache_readback.py:13-18`).

## 3. Files

### 3.1 New files

| Path | Purpose | Imitate |
|---|---|---|
| `apps/aigateway/src/aigateway/core/cache_versions/grant.py` | `Ed25519ReplayGrantVerifier` (PyJWT) with a 60 s in-process cache | `core/auth/middleware.py:91-112` (PyJWT error mapping), `core/parameter_discovery_cache.py` (injectable clock) |
| `apps/aigateway/src/aigateway/core/cache_versions/lookup.py` | `TortoiseCacheVersionLookup` | `core/request_cache/store.py:143-216` |
| `apps/aigateway/src/aigateway/routes/chat_replay_stage.py` | STAGE 0: `resolve_replay`, `replay_caller`, `replay_headers` | `routes/chat_cache_stage.py:139-209, 376-409`, `routes/tavily_retrieval_cache.py:128-185` |
| `apps/aigateway/tests/unit/cache_versions/test_grant_verifier.py` | CV-18, CV-19, CV-21 | — |
| `apps/aigateway/tests/unit/cache_versions/test_version_lookup.py` | CV-20 | — |
| `apps/aigateway/tests/unit/cache_versions/test_replay_route.py` | CV-16, CV-17, RP-5, CV-18 route row | `tests/unit/huggingface/test_huggingface_route_global_cache.py:162-200` |
| `apps/aigateway/tests/unit/cache_versions/test_replay_capture.py` | support | GW-capture `test_capture_route.py` |
| `apps/aigateway/tests/unit/cache_versions/test_replay_headers.py` | support | — |
| `apps/aigateway/tests/unit/cache_versions/test_replay_settings.py` | support | `tests/unit/test_cache_snapshot_settings.py` |
| `apps/aigateway/tests/integration/test_replay_hit_latency_postgres.py` | NFR (step 12) | `tests/integration/test_global_cache_store_postgres.py:47,143-150` |

### 3.2 Changed files

| Path | Change |
|---|---|
| `core/cache_versions/ports.py` | Add `GrantRejectReason`, `GrantRejected`, `VerifiedGrant`, `ReplayGrantVerifier`, `VersionHit`, `CacheVersionLookup` (§4.2). |
| `core/cache_versions/__init__.py` | Re-export the new port names. |
| `core/cache_versions/stats.py` | Add `replay_lookups: Counter[str]` (`hit`/`miss`/`invalid_grant`) — PRD metric `aigw_replay_lookups_total{result}`. |
| `core/cache_versions/wiring.py` | `CacheVersionServices` gains `grant_verifier: ReplayGrantVerifier | None` and `lookup: CacheVersionLookup`. Restructure `build_cache_version_services` so that the replay half does NOT depend on the receipt key: `lookup = TortoiseCacheVersionLookup()` always; `grant_verifier = None` when `cache_versions_enabled` is false or `replay_grant_public_keys` is empty, else `Ed25519ReplayGrantVerifier.from_config(settings.replay_grant_public_keys, lookup=lookup, cache_ttl_s=settings.replay_grant_cache_ttl_s)`. The GW-freeze rules for `freezer` and `exporter` (flag off or no signing key → `None`) stay unchanged. |
| `apps/aigateway/src/aigateway/config.py` | Two settings (§4.1). |
| `apps/aigateway/src/aigateway/main.py` | `app.state.cache_version_lookup = services.lookup`; `app.state.replay_grant_verifier = services.grant_verifier`. |
| `apps/aigateway/src/aigateway/routes/chat.py` | STAGE 0 and the header merges (§4.6). |
| `apps/aigateway/DEPLOYMENT.md` | Section "Cache versions: replay": the header, the 403 reasons, the key map format (JSON `{kid: b64}`, D7 X-4), the 60 s grant cache, that a takedown reaches issued grants only at their `exp` (DR-2), and the grant-life limit (D4): a grant lives 12 h (`exp = iat + 43,200 s`); the engine job deadline (57,600 s) plus the queue wait can be longer, so a replay run whose grant expires mid-run fails with `403 replay_grant_invalid`, reason `expired` (the engine RP-14 path). There is no refresh. Point to WIRING (D6) for the chart value. |

## 4. Signatures and data shapes

### 4.1 Settings

```python
replay_grant_public_keys: dict[str, str] = Field(default_factory=dict, validation_alias="AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS")
replay_grant_cache_ttl_s: float = Field(default=60.0, gt=0, allow_inf_nan=False, validation_alias="AIGW_REPLAY_GRANT_CACHE_TTL_S")
```
The env value is a JSON object `{"<kid>": "<base64 of the raw 32-byte Ed25519 public key>"}`
(pydantic-settings JSON-decodes a `dict` field). Decided: D7 (X-4): standard base64 of the raw key,
no PEM; the kid is the scoreboard's `SCOREBOARD_REPLAY_GRANT_SIGNING_KID` value. Content is decoded in wiring by
`Ed25519ReplayGrantVerifier.from_config`; a bad value raises
`RuntimeError(f"AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS[{kid!r}] is not base64 of a 32-byte Ed25519 public key")`.
Public keys are not secret, but keep the same message style.

### 4.2 Ports (`core/cache_versions/ports.py`, additions)

```python
GrantRejectReason = Literal["signature", "expired", "audience", "unknown_version", "subject"]

class GrantRejected(Exception):
    def __init__(self, reason: GrantRejectReason) -> None: ...
    reason: GrantRejectReason

@dataclass(frozen=True, slots=True)
class VerifiedGrant:
    version_id: UUID; result_id: str; subject: str; expires_at: int   # exp, epoch seconds

class ReplayGrantVerifier(Protocol):
    async def verify(self, token: str, *, caller: str | None) -> VerifiedGrant: ...   # raises GrantRejected

@dataclass(frozen=True, slots=True)
class VersionHit:
    response: dict[str, Any]; metadata_json: str | None

class CacheVersionLookup(Protocol):
    async def version_exists(self, version_id: UUID) -> bool: ...
    async def find(self, version_id: UUID, key_hash: str) -> VersionHit | None: ...
```

### 4.3 Verifier (`core/cache_versions/grant.py`) — C6 gateway rules

```python
MAX_GRANT_BYTES: Final = 4096
LEEWAY_S: Final = 60

class Ed25519ReplayGrantVerifier:
    def __init__(self, *, public_keys: Mapping[str, Ed25519PublicKey], lookup: CacheVersionLookup,
                 cache_ttl_s: float = 60.0, max_cached: int = 1024,
                 monotonic: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None
    @classmethod
    def from_config(cls, keys: Mapping[str, str], **kw) -> Ed25519ReplayGrantVerifier
    async def verify(self, token: str, *, caller: str | None) -> VerifiedGrant
```
`verify`, in this order:
1. `len(token.encode()) > MAX_GRANT_BYTES` → `GrantRejected("signature")`.
2. `ck = sha256(token).hexdigest()`. A cache entry younger than `cache_ttl_s` (by `monotonic`) gives
   `grant`; skip to step 7.
3. `header = jwt.get_unverified_header(token)`; `jwt.InvalidTokenError` → `signature`.
   `kid = header.get("kid")`; `kid` not a `str` → `signature`. `key = public_keys.get(kid)`; `None` → `signature`.
4. `claims = jwt.decode(token, key, algorithms=["EdDSA"], audience="aigateway", issuer="scoreboard", leeway=LEEWAY_S, options={"require": ["iss", "aud", "sub", "vid", "rid", "iat", "exp"]})`.
   Map: `jwt.ExpiredSignatureError` → `expired`; `jwt.InvalidAudienceError` → `audience`;
   every other `jwt.InvalidTokenError` (bad signature, bad issuer, missing claim, decode error) →
   `signature`. (PyJWT checks the signature before the claims, so a forged token never reports
   `audience` or `expired`.)
5. `vid = UUID(str(claims["vid"]))` (`ValueError` → `signature`); `sub`, `rid` must be `str`
   (else `signature`).
6. `await lookup.version_exists(vid)` false → `unknown_version`. Store
   `VerifiedGrant(vid, rid, sub, int(claims["exp"]))` in the cache with the `monotonic()` time; when the
   cache holds `max_cached` entries, drop the oldest.
7. On EVERY call (cached or fresh): `wall() > grant.expires_at + LEEWAY_S` → drop the entry,
   `expired`. `caller is not None` and `grant.subject.strip().lower() != caller.strip().lower()` → `subject`
   (RP-D1: a cached grant never skips the subject check). Return `grant`.

Never log the token. Log the reason and the first 12 chars of `ck` only.

### 4.4 Lookup (`core/cache_versions/lookup.py`)

```python
class TortoiseCacheVersionLookup:
    async def version_exists(self, version_id: UUID) -> bool     # CacheVersion.exists(id=version_id)
    async def find(self, version_id: UUID, key_hash: str) -> VersionHit | None
```
`find`: `CacheVersionEntry.filter(version_id=version_id, key_hash=key_hash).order_by("first_ordinal", "blob_id").select_related("blob").first()`
(`blob_id` is the Python attribute of the FK whose DB column is `blob_sha256`; GW-capture §5).
`None` → `None`. `json.loads(entry.blob.response_json)`; not a `dict` → log (key prefix) and `None`.
The unique index `(version_id, key_hash, blob_sha256)` from 0013 serves the query (≤ 30 ms NFR).
Replay rule (`erd.md` §3.4, CV-D6, RP-D5): the lowest `first_ordinal` wins. The blob body is model output:
return it as data; never parse or act on its text (CV-D10).

### 4.5 Route stage (`routes/chat_replay_stage.py`)

```python
REPLAY_REQUEST_HEADER: Final = "X-AIGW-Cache-Replay"
VERSION_HEADER: Final = "X-AIGW-Cache-Version"
CACHE_STATUS_HEADER: Final = "Cache-Status"
VERSION_HIT_CACHE_STATUS_PREFIX: Final = "aigateway; hit; detail=version"

def version_hit_cache_status(key_hash: str) -> str:
    # Cross-plan fix (ENG-replay §11 #8, RP-15): the engine counts repeated-key collapses from the
    # `key=` param of the aigateway Cache-Status member. A key-less Cache-Status hit wins over the
    # legacy X-AIGW-Cache-Key header and gives key=None (engine world/cache_readback.py:137-149).
    # `key` is an RFC 9211 String, so it is always quoted (exemplar: routes/tavily_retrieval_cache.py:128-155).
    return f'{VERSION_HIT_CACHE_STATUS_PREFIX}; key="{key_hash[:KEY_PREFIX_LENGTH]}"'

@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    status: Literal["hit", "miss"]
    key_hash: str | None
    hit: VersionHit | None

def replay_caller(settings: Settings, account: BaseAccount) -> str | None
    # None when settings.auth_mode == "disabled" (CV-19, RP-D8); else account.username.
    # Production (D5): auth_mode == "cloudflare_headers", so account.username is the lowercased
    # verified X-User-Email (core/auth/cloudflare_identity.py:74-82). SB-grants puts the same
    # verified email in the grant `sub`. `disabled` is a dev/local fallback only.

async def resolve_replay(request: Request, *, caller: str | None, body: dict[str, Any],
                         plugin: ProviderPluginBase, capture_key: CaptureKey | None) -> ReplayOutcome | None

def replay_headers(outcome: ReplayOutcome | None) -> dict[str, str]
```
`resolve_replay`:
1. `token = (request.headers.get(REPLAY_REQUEST_HEADER) or "").strip()`; empty → `None` (a normal call).
2. `verifier = request.app.state.replay_grant_verifier`. If `cache_versions_enabled` is false or
   `verifier is None` → raise the 403 below with reason `signature` (OD-R1: the gateway holds no key
   that verifies this grant; a silent live run is refused, RP-E6).
3. `grant = await verifier.verify(token, caller=caller)`; `GrantRejected as exc` →
   `stats.replay_lookups["invalid_grant"] += 1`;
   `raise HTTPException(403, detail={"code": "replay_grant_invalid", "reason": exc.reason, "message": "the cache replay grant was refused"})`.
   Never fall through (CV-E4). This is the coded error body of D7 (X-8); ENG-replay reads
   `detail.code` and `detail.reason` from it.
4. `key = capture_key or build_capture_key(body=body, plugin=plugin)` (the key is computed here only
   when capture did not compute it, for example an untraced call). `key is None` → miss.
5. `hit = await request.app.state.cache_version_lookup.find(grant.version_id, key.key_hash)`. Any
   exception → log WARNING (type name, key prefix) and treat as a miss (the version is never an
   availability dependency; the miss header keeps it visible to the engine).
6. Count `stats.replay_lookups["hit"|"miss"]`; return the outcome.

`replay_headers`: `None` → `{}`; miss → `{VERSION_HEADER: "miss"}`; hit →
`{VERSION_HEADER: "hit", CACHE_STATUS_HEADER: version_hit_cache_status(key_hash), CACHE_HEADER: "hit", REASON_HEADER: "", KEY_HEADER: key_hash[:KEY_PREFIX_LENGTH]}`
(import the four names from `routes/chat_cache_stage.py:51-54, 78`; do not re-spell them).

### 4.6 Chat route (`routes/chat.py`)

Line numbers move after GW-capture and GW-freeze merged into the e14 branch; find the anchors by text.
1. Directly after `capture = begin_capture(...)` (GW-capture) and INSIDE its `try` (so a 403 records an
   `error` capture row), before the `STAGE 1` banner, add the STAGE 0 banner and:
   ```python
   replay = await resolve_replay(
       request, caller=replay_caller(request.app.state.settings, current), body=body,
       plugin=plugin, capture_key=capture.key if capture is not None else None,
   )
   if replay is not None and replay.hit is not None:
       response.headers.update(replay_headers(replay))
       if accounting is not None:
           accounting.cache_status = "hit"
       served = request.app.state.taxonomy_plugin.sanitize_provider_response(replay.hit.response)
       await record_capture(request, capture, "version_hit", response=served)
       return attach_hit_metadata(
           served, accounting, plugin=plugin,
           entry_metadata=CacheEntryMetadata.parse(replay.hit.metadata_json) if replay.hit.metadata_json else None,
       )
   ```
   INVARIANT comment: STAGE 0 runs before STAGE 1 and before any credential is resolved; a version hit
   reads no credential and dispatches nothing (CV-H4).
2. STAGE 1 hit return: add `response.headers.update(replay_headers(replay))` after
   `set_global_cache_headers(response, cache_outcome)`.
3. Streaming return: pass `headers={**global_cache_headers(cache_outcome), **replay_headers(replay)}`.
4. After STAGE 3: add `response.headers.update(replay_headers(replay))` after
   `set_global_cache_headers(response, cache_outcome, write_status=write_status)`.
5. Do not change anything else. `accounting.cache_status = "hit"` is valid: `CacheStatusWord`
   includes `hit` (`plugins/taxonomy/session.py:78`).

GW-capture's `capture_record` already keeps the body for `version_hit` (it is in `INLINE_OUTCOMES`).

## 5. Migrations

None. The replay query uses the `cache_version_entry` unique index from `0013_cache_versions.py`
(GW-capture). If the query plan needs another index, STOP and ask.

## 6. TDD order (RED first; the trust boundary first, as `prd/replay-pinned-run.md` §7 orders)

Scaffold: ports; `Ed25519ReplayGrantVerifier.verify` returns a `VerifiedGrant` for ANY token (so RED
is an assertion, not an import error); `TortoiseCacheVersionLookup.find` returns `None`;
`resolve_replay` returns `None`; `replay_caller` returns `None`; `replay_headers` returns `{}`; wiring;
settings. Commit with the ledger.

Shared arrangement: APPEND to `tests/unit/cache_versions/conftest.py`: fixture `grant_key`
(`Ed25519PrivateKey.generate()`); fixture `_replay_env(monkeypatch, grant_key, _freeze_env)` that sets
`AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS={"test-kid": <b64 raw public>}`; fixture
`replay_client(_replay_env, client)` logged in as admin; helper
`mint_grant(key, *, sub, vid, rid="res-1", ttl_s=43_200, aud="aigateway", iss="scoreboard", kid="test-kid", now=None) -> str`
(`jwt.encode(..., algorithm="EdDSA", headers={"kid": kid})`); helper `frozen_version(client, trace) -> UUID`
(3 traced calls, then `POST /v1/cache-versions`, return `cache_version_id`). Unit verifier tests use a
`FakeLookup(existing: set[UUID])` with a call counter.

| Step | Id | File :: test | RED reason | GREEN |
|---|---|---|---|---|
| 1 | CV-18 | `test_grant_verifier.py::test_invalid_grant_rejects_403_with_closed_reason` (parametrize: `signature` — signed by another key under `test-kid`; unknown kid; `"not-a-jws"`; missing `vid`; `iss="someone"`; `expired` — `exp = now-61`; `audience` — `aud="scoreboard"`; `unknown_version` — random vid; `subject` — `sub="carol@x.org"`, caller `"bruno@x.org"`) | `pytest.raises(GrantRejected)` with the expected `reason`. Fails: the scaffold accepts every token. Plus `test_a_grant_inside_the_skew_window_is_accepted` (`exp = now-59`). | §4.3 |
| 2 | CV-18 route row | `test_replay_route.py::test_invalid_grant_is_403_and_never_falls_through` | With a frozen version, send a request with a grant signed by a wrong key: status 403, `detail.code == "replay_grant_invalid"`, `detail.reason == "signature"`, dispatch counter unchanged. Fails: the scaffold `resolve_replay` returns `None`, so the call dispatches. | §4.5 steps 1–3, §4.6 step 1 |
| 3 | RP-5 | `test_replay_route.py::test_gateway_rejects_grant_reused_by_other_subject` | Admin (username `admin`) freezes V. Grant `sub="admin"`. A provisioned user B (`provisioned_user_factory`, `tests/conftest.py:229`) sends it → 403 `detail.reason == "subject"` and the dispatch counter is unchanged. Positive control: admin sends it → status is not 403. Fails: the scaffold `replay_caller` returns `None`, so the route never checks the subject and B's call is not refused. (The admin hit and the headers are asserted by CV-16.) | §4.5 `replay_caller` (jwt mode: `account.username`) |
| 3b | support (D5) | `test_replay_route.py::test_cloudflare_headers_subject_is_the_verified_email` | Admin freezes V in `jwt` mode (helper `frozen_version`). Then flip the built app to production mode: `replay_client.app.state.settings.auth_mode = "cloudflare_headers"` (exemplar `tests/unit/auth/test_cloudflare_identity.py:97-105`). Send body S with header `X-User-Email: Ana@Example.org` and a grant with `sub="ana@example.org"` → status is not 403 (the username is the lowercased verified email). Send it again with a grant `sub="bruno@example.org"` → 403 `detail.reason == "subject"`, dispatch counter unchanged. Write it together with step 3, BEFORE step 3 GREEN, and record its red run: the scaffold `replay_caller` returns `None`, so the `bruno` call is not refused. | §4.5 `replay_caller` (non-disabled mode: `account.username`) |
| 4 | CV-19 | `test_grant_verifier.py::test_grant_subject_check_skipped_when_auth_disabled` and `test_replay_caller_is_none_when_auth_disabled` | `verify(token, caller=None)` with `sub="someone-else"` returns the grant; `replay_caller(Settings(AIGW_AUTH_MODE="disabled"), anonymous)` is `None`, and in `jwt` mode it is the username. Fails: after step 3 GREEN, `replay_caller` returns the username in every mode, so the disabled-mode assertion (`is None`) fails; the paired subject row of step 1 proves the check exists. | §4.3, §4.5 |
| 5 | CV-16 | `test_replay_route.py::test_valid_grant_hit_serves_version_without_provider_call` | Freeze V over calls H, S, B. Delete every `RequestCacheEntry` row (so the live cache cannot answer). Send S again with a valid grant (sub `admin`), recording `ORMStore.read` (HF test pattern). Assert 200; body `choices` equal the frozen answer; `X-AIGW-Cache-Version: hit`; `Cache-Status: aigateway; hit; detail=version; key="<key_hash[:KEY_PREFIX_LENGTH]>"`; `X-AIGW-Cache: hit`; dispatch counter unchanged; no `aigateway:anthropic:*` credential read. Fails: the scaffold lookup returns `None` → the call dispatches. | §4.4, §4.5 steps 4–6, §4.6 step 1 |
| 6 | CV-17 | `test_replay_route.py::test_valid_grant_miss_falls_through_and_marks_miss` | Same V; send a new body N (not in V) with a valid grant. Assert 200, dispatched once, `X-AIGW-Cache: miss`, `X-AIGW-Cache-Write: stored`, `X-AIGW-Cache-Version: miss`. Fails: no `X-AIGW-Cache-Version` header yet. | §4.6 steps 2–4 |
| 7 | CV-20 | `test_version_lookup.py::test_duplicate_key_replay_returns_lowest_ordinal` | Seed with the models (SQLite through `client`'s database): one `CacheVersion`, two blobs A, B, two entries for one key with `first_ordinal` 3 (A) and 0 (B). `find` returns B's response. Also `test_find_returns_none_for_another_version`. Fails: scaffold `find` returns `None`. | §4.4 |
| 8 | CV-21 | `test_grant_verifier.py::test_verified_grant_cached_60s` | Fake `monotonic`/`wall` and a `FakeLookup` that counts `version_exists` calls. Verify the same token at t=0 and t=59 → 1 lookup; at t=61 → 2 lookups; another token → its own entry; a cached grant with a different caller still raises `subject`; a cached grant past `exp + 60` raises `expired`. Fails: no cache yet (2 lookups at t=59). | §4.3 steps 2, 6, 7 |
| 9 | support | `test_replay_capture.py::test_version_hit_is_captured_with_inline_body` | Traced replay hit → a capture row with outcome `version_hit` and `response_json` equal to the served body; a later freeze of that trace is `complete`. | §4.6 step 1 |
| 10 | support | `test_replay_headers.py` | `replay_headers` for `None`/miss/hit (the hit `Cache-Status` ends with `key="<prefix>"`, quoted, and the engine parser `read_cache_outcome` would read that prefix as `key`); a streaming call with a grant gets `X-AIGW-Cache-Version: miss` (a stream has no key). | §4.5, §4.6 step 3 |
| 12 | NFR | `tests/integration/test_replay_hit_latency_postgres.py::test_replay_hit_p99_is_at_most_30_ms` | `pytestmark = pytest.mark.needs_postgres`, skip unless `AIGW_TEST_PG=1`. On a migrated Postgres container, seed one version with 200 entries through the models; warm the verifier with one call; then time 200 `verify` + `lookup.find` pairs. Assert p99 ≤ 30 ms. No RED is possible for a budget test; record the numbers in the ledger. | none, or tune §4.4 |
| 11 | support | `test_replay_settings.py` | A non-base64 or 31-byte public key fails at `create_app` with a message that names the kid; an empty map gives no verifier and a grant header then gets 403 `signature`. | §4.1, OD-R1 |

## 7. Edge cases, what not to do, gates

### 7.1 Edge cases

- A grant header on a call that has no key (stream, provider without a projection): verify the grant
  (an invalid one is still 403), then miss.
- A grant for version V on a call of another benchmark: most calls miss; the scoreboard already
  refuses a benchmark mismatch (RP-E4). The gateway does not check it.
- Production identity (D5): the gateway runs `cloudflare_headers` (`charts/aigateway/values-prod.yaml:18`).
  A grant of a private version used by its owner: `sub` equals the verified email, lowercased.
  The gateway does not know about owners; the scoreboard decided access when it minted the grant
  (the scoreboard also uses `cloudflare_headers` in production, D5).
- `auth_mode=disabled` (dev/local fallback only): no subject check (RP-D8). Keep that behaviour.
- A withdrawn version: the gateway cannot know (DR-2). An issued grant works until `exp`.
- Grant life (D4): `exp = iat + 43,200 s` (12 h). The engine job deadline (57,600 s) plus the queue
  wait can be longer. A grant that expires during a run gives `403 replay_grant_invalid`, reason
  `expired`, on the next chat call (step 7 of §4.3, also for a cached grant). The engine then fails
  the run with its typed error (ENG-replay RP-14). The gateway does not extend or refresh the grant.
- Lookup DB error: miss with a WARNING; the header makes the miss visible.

### 7.2 What not to do

- Do not fall through to the live path on an invalid grant.
- Do not cache a rejection, and do not skip the subject or expiry check for a cached grant.
- Do not log the grant token, a prompt or a response. Key and token prefixes only.
- Do not forward `X-AIGW-Cache-Replay` to a provider (dispatch uses the body only; keep it so).
- Do not import `aigateway.core.cache_versions.grant`, `.lookup` or `.models` from `routes/` (ports
  only, through `app.state`); the GW-capture boundary test fails otherwise. No plugin imports
  `core.cache_versions`.
- Do not change the global key, `global_cache_headers`, or the reason vocabulary.
- No credential work: `credential_blobs`, `ORMStore` and `AIGATEWAY_SECRET_KEY` stay untouched; no OS
  keychain. Grant verification keys are public keys in config, not secrets.
- Do not edit existing tests; append fixtures to `conftest.py` only.

### 7.3 Gates

```bash
cd apps/aigateway
uv run ruff check && uv run ruff format --check && uv run pyright
uv run python scripts/check_no_enterprise.py
uv run pytest --cov=aigateway --cov-fail-under=80 -q -m "not live and not needs_postgres"
AIGW_TEST_PG=1 uv run pytest -m needs_postgres -v
cd ../.. && uv run .claude/scripts/run_gates.py aigateway --base e14-reproducible-submission-spec
```

The `--base` is the e14 branch (D1), so the append-only check sees only this unit's change.

## 8. Verification and "done"

1. Every §1.1 row is green; all GW-capture and GW-freeze rows stay green (CV-1 and CV-2 CHAR included:
   a version hit and a live hit both read no credential).
2. A local manual check, recorded in the ledger: one traced run, freeze, delete the live rows, replay one
   call with a minted grant → `X-AIGW-Cache-Version: hit`; a tampered grant → 403 `signature`.
3. NFR (≤ 30 ms p99 for a replay hit with a warm grant cache): step 12 is green in the Docker lane, and
   the ledger records the measured p99.
4. `run_gates.py aigateway --base e14-reproducible-submission-spec` green; conventional commits on
   `unit/GW-replay`; no `Co-Authored-By`. No PR and no Linear issue (D1). The integrator merges the
   branch after wave 3.

## 9. Open decisions

None is open. The items below are closed:

- **OD-R1 — decided (default).** A grant header that reaches a gateway that cannot verify it (flag off,
  or no public keys) gets `403 replay_grant_invalid`, reason `signature`, so the run fails typed
  (RP-E6) and never becomes a silent paid run.
- **OD-R2 — Decided: D4.** A3 is "[checked] false, accepted". The grant lives 12 h
  (`exp = iat + 43,200 s`). The engine job deadline is 57,600 s
  (`apps/screamingface-engine/src/screamingface_engine/config.py:148-151`) and the queue wait adds
  more. A grant that expires mid-run gives 403 reason `expired`, and the engine fails the run on the
  RP-14 path. No refresh. DEPLOYMENT.md documents the limit (§3.2).
- **OD-R3 — Decided: D5.** Production is `cloudflare_headers`. The gateway compares
  `sub.strip().lower()` with the account username (the lowercased verified email). SB-grants puts the
  verified email in `sub`. Step 3b tests this path.
- **OD-R4 — decided (default); contract Decided: D7 (X-7).** A version hit also sets
  `X-AIGW-Cache: hit`. ENG-replay counts the version dimension from `X-AIGW-Cache-Version` in its own
  `cache.version.*` counters, beside (not instead of) the normal hit count.
- **Error body — Decided: D7 (X-8).** `{"detail": {"code", "reason", "message"}}` for the 403.
