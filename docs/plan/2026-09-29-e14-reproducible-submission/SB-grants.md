# SB-grants — Plan: issue replay grants from a pin

- **Epic:** OME-1307 (E14).
- **Spec (the rubric):** `docs/spec/2026-09-29-e14-reproducible-submission/prd/replay-pinned-run.md` (§3, §4, §7), `contracts.md` C6, DR-2, `erd.md` §2.2, §2.3, §2.6, §2.7, `prd/system-registry.md` SR-H5 / SR-20.
- **Plan:** this file, `docs/plan/2026-09-29-e14-reproducible-submission/SB-grants.md`. **Ledger:** `docs/work/2026-09-29-e14-sb-grants.md`. Start it before the first RED.
- **Delivery (D1):** build this unit in its own temporary worktree on the branch `unit/SB-grants`, made from the HEAD of `e14-reproducible-submission-spec` (`git checkout -B unit/SB-grants e14-reproducible-submission-spec`). Do not open a PR. Do not file a Linear issue. After wave 4, the integrator merges `unit/SB-grants` into `e14-reproducible-submission-spec` (before `unit/SB-publish`, see §2 "Integration notes") and runs the gates.
- **Component:** `apps/scoreboard` only. Wave 4 (D2), in parallel with SB-publish and SDK-replay.
- **Implementer:** Sonnet, `sdlc-python` loop.

## Global constraints

The same as `SB-submit.md` "Global constraints": stack `scoreboard`; gates through `run_gates.py` with `--base "$(git merge-base HEAD e14-reproducible-submission-spec)"`; ruff `max-returns = 3`, `max-branches = 7`, `max-statements = 26`, `max-complexity = 8`; `asyncio_mode = "strict"`; **append-only tests** (new files only); files ≤ 450 lines; the closed comment-anchor vocabulary; conventional commits on `unit/SB-grants` with no `Refs:` line and no `Co-Authored-By`; no import from another app and never `screamingface`.

**Identity (D5).** Production runs `SCOREBOARD_AUTH_MODE=cloudflare_headers` (`apps/scoreboard/src/scoreboard/core/auth/cloudflare_identity.py`; the peer check against `SCOREBOARD_ALLOWED_NETWORKS` comes before the `X-User-Email` read). The grant `sub` and the owner check use that verified email. The gateway also runs `cloudflare_headers` in production and checks `sub == caller` (C6), so a grant for an unverified caller is useless there. So in `cloudflare_headers` mode this route needs a verified identity (401 / 403, as a write route). The `disabled` mode is a dev/local fallback only: keep today's behavior there (`sub = "anonymous"`, nobody is an owner). The main-path tests run in `cloudflare_headers` mode; the grant flow has exactly one `disabled`-fallback test (RP-2a).

## 1. Scope

**Owned test ids (`prd/replay-pinned-run.md` §7):** RP-1, RP-2, RP-3, RP-4, RP-6, RP-7, RP-8, RP-9, RP-10.

Supporting tests have a letter suffix (RP-4a …), listed in §6.

**Out of scope:**
- RP-5 (gateway rejects a reused grant; unit GW-replay).
- RP-11 … RP-15 (engine; ENG-freeze / ENG-replay).
- RP-16 … RP-20 (SDK and local runtime; SDK-replay). RP-20 wires the local keys; this unit only reads the settings.
- RP-21 (E2E). RP-22 is dropped (Q30).
- The pin grammar itself (SR-20, unit SB-registry). This unit calls the merged parser.
- A grant revocation list (DR-2 "change when").
- Any write to the database. The grant route is read-only.
- Chart values and Secrets for the grant signing key, and the local runtime keys (`screamingface up`). Unit WIRING (wave 5, D6) owns them. This unit adds only the settings in `config.py`.
- The admin route that sets `Benchmark.redistributable` (unit WIRING, D6). Tests set the column on the seeded benchmark rows.
- Grant refresh. Decided: D4 (no refresh).

## 2. Depends on

- **Merged first:** SB-meta (it adds `routes/write_identity.py::write_identity`, SB-meta §4.6a) and SB-submit (it adds `pyjwt[crypto]`, `metrics.py`, `ClusterStore.load_replay_target`, `core/replay_access.py`, `routes/errors.py::coded_error`, `tests/unit/submissions/_receipts.py`) and so SB-registry, SB-schema.
- **Contract implemented:** C6 (scoreboard side: the route and the grant token).
- **Contracts consumed:** `parse_pin(raw: str) -> NamePin | RevisionPin | DatePin` and `RegistryService.resolve_pin(pin: str) -> RevisionRef | list[RevisionRef]` of SB-registry (`SB-registry.md` §4.2, §4.5, §4.7). `resolve_pin` takes NO benchmark id; this unit filters by benchmark. C6's verifier rules are the gateway's (GW-replay, `GW-replay.md` §4.1-§4.2) — this unit must emit exactly the claims, the `kid` header and the key encoding that GW-replay checks.

**Before RED:** open the merged SB-registry and SB-submit code and write the real names in the ledger. This plan assumes:

| This plan says | From |
|---|---|
| `from scoreboard.core.registry import parse_pin, NamePin, RevisionPin, DatePin, RevisionRef, InvalidPin, PinNotFound` | SB-registry §4.2, §4.3, §4.5 |
| `parse_pin(raw)` handles ONLY the name forms. `DatePin.at` is already a tz-aware UTC `datetime`: a date-only qualifier is the end of that day (23:59:59.999999 UTC), an offset time is converted to UTC, a time with no offset raises `InvalidPin` (SB-registry §4.5 steps 5-7). `InvalidPin(pin, message)`, `PinNotFound(pin)`. | SB-registry §4.5 |
| `await app.state.system_registry.resolve_pin(raw)`: `NamePin` → the latest `RevisionRef`; `RevisionPin` → that `RevisionRef` or `PinNotFound`; `DatePin` → `list[RevisionRef]` (all revisions, ascending); unknown name → `PinNotFound` | SB-registry §4.7 |
| `replay_access(...)`, `is_owner(...)` in `scoreboard/core/replay_access.py` | SB-submit §4.6 |
| `ClusterStore.load_replay_target(result_id) -> ReplayTarget \| None` (`result`, `head`, `benchmark`, `publication_state`) | SB-submit §4.5, §4.6 |
| `ReportedResult` attribute and column `head_id` (D8); filter across the FK with `head__benchmark_id`, `head__system_revision_id` | SB-schema §4.5 |
| `coded_error(status, code, message, **extra)` in `scoreboard/routes/errors.py` | SB-submit §4.7 |
| `Metrics` dataclass in `scoreboard/metrics.py` | SB-submit §4.9 |

| `write_identity(request) -> str \| None` in `scoreboard/routes/write_identity.py` (`cloudflare_headers`: 403 untrusted peer, 401 coded `identity_not_verified`, else the email; `disabled`: None) | SB-meta §4.6a |
| `identity_is_verified(auth_mode)` and `UNTRUSTED_PEER_DETAIL` in `scoreboard/routes/scores.py:57-84` | existing code |

Do NOT write the date rules again: RP-7 tests the merged parser output together with this unit's resolver. This unit adds only the two id forms (`result:<uuid>`, `score:<uuid>`), in front of `parse_pin` (SB-registry §4.5 step 2 says so). If a name above differs in the merged code, use the merged name and write it in the ledger.

### Integration notes (D2)

SB-publish is in the same wave and changes five of the same files. The integrator merges **SB-grants first, then SB-publish**. Both changes are additive. Put your lines in their own block with a `FEATURE: OME-1307 (E14) replay grants` comment, so the merge has no overlapping hunk:

| Shared file | This unit adds | SB-publish adds |
|---|---|---|
| `apps/scoreboard/src/scoreboard/config.py` | `replay_grant_signing_key`, `replay_grant_signing_kid` | `admin_emails`, `github_app_*`, `archive_*`, `publish_*` |
| `apps/scoreboard/src/scoreboard/main.py` | `app.state.grant_signer`, `app.state.replay_resolver`, `app.state.clock`, `include_router(replay_grants.router)` | the publisher factory, the archive reader, two routers, the worker task in `_lifespan` |
| `apps/scoreboard/src/scoreboard/metrics.py` | `replay_grants: Counter` | four publish counters and gauges |
| `apps/scoreboard/src/scoreboard/scores/schemas.py` (append at the END) | `ReplayGrantRequest`, `ReplayGrantResponse` | `PublishStateResponse`, `WithdrawRequest` |
| `apps/scoreboard/DEPLOYMENT.md` | a "Replay grants" section | a "Publish and takedown" section |

`app.state.clock`: this unit adds it. SB-publish reads a clock too; if both add the same line, the integrator keeps one.

## 3. Files

| C/M | Path | What | Exemplar |
|---|---|---|---|
| M | `apps/scoreboard/src/scoreboard/config.py` | Settings (§4.1). | `config.py:63-87`; secret handling like `apps/aigateway/src/aigateway/config.py:71-85` |
| C | `apps/scoreboard/src/scoreboard/core/replay/__init__.py` | Package marker. | — |
| C | `apps/scoreboard/src/scoreboard/core/replay/grants.py` | Port `GrantSigner`; `build_grant_claims`; `ResolvedReplay`; the errors `PinWithdrawn`, `PinBenchmarkMismatch`. Stdlib only. | `core/auth/cloudflare_identity.py` style |
| C | `apps/scoreboard/src/scoreboard/core/replay/pins.py` | `ResultPin`, `ScorePin`, `ReplayPin`, `parse_replay_pin` (§4.3). Imports only the stdlib and `scoreboard.core.registry`. | SB-registry `core/registry/pins.py` |
| C | `apps/scoreboard/src/scoreboard/adapters/jws_grant_signer.py` | `Ed25519GrantSigner` (PyJWT, EdDSA, `kid` header). | `apps/screamingface-engine/src/screamingface_engine/auth/jwt.py:25-50` |
| C | `apps/scoreboard/src/scoreboard/scores/replay_resolver.py` | `ReplayPinResolver`: the Tortoise adapter that turns a pin into one `ReplayTarget`, applying the access rule. | query style `scores/store.py:1487-1540` |
| C | `apps/scoreboard/src/scoreboard/routes/replay_grants.py` | `POST /v1/replay-grants`. | `routes/scores.py:287-353` (identity, 404 policy, 503 on `OperationalError`) |
| M | `apps/scoreboard/src/scoreboard/scores/schemas.py` | `ReplayGrantRequest`, `ReplayGrantResponse` (§4.2). Append at the END of the file. | `ClientInfo` `schemas.py:331-340` |
| M | `apps/scoreboard/src/scoreboard/metrics.py` | Add `replay_grants: Counter` (`scoreboard_replay_grants_total{result}`). | SB-submit §4.9 |
| M | `apps/scoreboard/src/scoreboard/main.py` | Build the signer from settings (or `None`); `app.state.grant_signer`, `app.state.replay_resolver`, `app.state.clock`; `include_router(replay_grants.router)`. Validate the key at `create_app`. | `main.py:178-196` |
| M | `apps/scoreboard/DEPLOYMENT.md` | The two environment variables, the key format (base64 of the raw 32-byte Ed25519 seed; the kid comes from `SCOREBOARD_REPLAY_GRANT_SIGNING_KID`, D7 X-4), key rotation (new kid; the gateway holds current plus previous public keys), and the fixed 12 h grant life with its limit (the `GRANT_TTL_S` docstring in §4.3, D4). Say that the chart keys and the Secret come from unit WIRING (D6). Do not edit the chart. | — |
| C | tests (§6) | — | — |

No migration. No change to `store.py`.

## 4. Signatures and data shapes

### 4.1 Settings

```python
replay_grant_signing_key: SecretStr | None = None
"""Standard base64 of the RAW 32-byte Ed25519 private key (the seed). Env
SCOREBOARD_REPLAY_GRANT_SIGNING_KEY, from a Secret.
INVARIANT: the same byte form the gateway uses for its keys (GW-freeze.md OD-F2,
GW-replay.md §4.1: AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS holds base64 of the raw 32-byte
public key) and the local runtime writes (SDK-replay.md §4.12).
AIDEV-NOTE: key material — never log it or put it in an error."""
replay_grant_signing_kid: str | None = None  # SCOREBOARD_REPLAY_GRANT_SIGNING_KID, the JWS kid header
# (the variable name the local runtime sets, SDK-replay.md §4.12 table)
```

There is no TTL setting. The grant life is the constant `GRANT_TTL_S` (§4.3). Decided: D4.

`create_app`: if exactly one of key and kid is set → `ValueError` naming the missing variable. If the key is set: `raw = base64.b64decode(key.get_secret_value(), validate=True)`; a decode error or `len(raw) != 32` → `ValueError("SCOREBOARD_REPLAY_GRANT_SIGNING_KEY must be base64 of a 32-byte Ed25519 private key")`; else `Ed25519PrivateKey.from_private_bytes(raw)`. Never echo the key.

### 4.2 Wire (C6)

```python
class ReplayGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: Annotated[str, Field(min_length=1, max_length=256)]
    benchmark_id: Annotated[str, Field(min_length=1, max_length=64)]

class ReplayGrantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grant: str
    result_id: UUID
    score_id: UUID
    cache_version_id: UUID
    expires_at: datetime        # RFC 3339 UTC, = exp
```

```
POST /v1/replay-grants
200 ReplayGrantResponse                 headers: Cache-Control: private, no-store
401 {"detail": {"code": "identity_not_verified", "message": ...}}   (cloudflare_headers, no X-User-Email; D5)
403 {"detail": "<UNTRUSTED_PEER_DETAIL>"}                           (cloudflare_headers, untrusted peer; D5)
404 {"detail": {"code": "replay_pin_not_found", "message": ...}}
410 {"detail": {"code": "cache_version_withdrawn", "message": ...}}
422 {"detail": {"code": "invalid_replay_pin", "message": ...}}
422 {"detail": {"code": "replay_benchmark_mismatch", "message": ...}}
503 {"detail": {"code": "replay_unavailable", "message": ...}}   (no signing key configured; OD-4)
503 {"detail": "score store unavailable"}                      (OperationalError, as routes/scores.py:280-284)
```

Every 404 has the SAME body and the SAME headers (`PRIVATE_CACHE_HEADERS`, `routes/dependencies.py:49-52`) for every cause (unknown name, unknown id, a private result of another user, a gated result, no version, unknown benchmark). INVARIANT: the same OME-894 rule as `routes/scores.py:54-56` — the answer never confirms that a private result exists.

Every response of this route is identity-dependent, so every response (200 and errors) carries `PRIVATE_CACHE_HEADERS`.

### 4.3 Core (`core/replay/grants.py`)

```python
GRANT_ISSUER = "scoreboard"
GRANT_AUDIENCE = "aigateway"
# AIDEV-NOTE (D5): only the `disabled` dev/local fallback issues this subject. In
# cloudflare_headers (production) the route refuses a caller with no verified identity.
ANONYMOUS_SUBJECT = "anonymous"
GRANT_TTL_S = 43_200
"""INVARIANT (C6, D4): exp = iat + 43,200 s (12 h). No setting and no refresh.
WHY this is a known limit: the engine job deadline is 57,600 s
(apps/screamingface-engine/src/screamingface_engine/config.py:148-151) and a queued job can
also wait before it starts (worker/supervisor.py:833-858). So a grant can expire during a
run. Then the gateway refuses the grant and that run fails with the typed replay error (the
RP-14 path, ENG-replay). The user starts a new run with a new grant."""

class GrantSigner(Protocol):
    def sign(self, claims: Mapping[str, object]) -> str: ...

def build_grant_claims(*, subject: str | None, cache_version_id: UUID, result_id: UUID,
                       now: datetime) -> dict[str, object]:
    """{"iss": "scoreboard", "aud": "aigateway", "sub": subject or ANONYMOUS_SUBJECT,
        "vid": str(cache_version_id), "rid": str(result_id),
        "iat": int(now.timestamp()), "exp": int(now.timestamp()) + GRANT_TTL_S}   (C6, exactly)
    `subject` is the verified email in cloudflare_headers; None only in the disabled fallback."""

# PinNotFound and InvalidPin are the SB-registry errors (scoreboard.core.registry). Reuse them;
# do not define a second PinNotFound.
class PinWithdrawn(Exception): ...         # -> 410 cache_version_withdrawn
class PinBenchmarkMismatch(Exception): ... # -> 422 replay_benchmark_mismatch

@dataclass(frozen=True, slots=True)
class ResolvedReplay:
    result_id: UUID
    score_id: UUID
    cache_version_id: UUID
```

`core/replay/pins.py`:

```python
@dataclass(frozen=True, slots=True)
class ResultPin:
    result_id: UUID

@dataclass(frozen=True, slots=True)
class ScorePin:
    score_id: UUID

ReplayPin = ResultPin | ScorePin | NamePin | RevisionPin | DatePin

def parse_replay_pin(raw: str) -> ReplayPin:
    """raw starts with "result:" -> ResultPin(UUID(rest)); "score:" -> ScorePin(UUID(rest));
    a ValueError from UUID() -> InvalidPin(raw, "not a result or score id").
    Else return parse_pin(raw) (SB-registry)."""
```

`adapters/jws_grant_signer.py`:

```python
class Ed25519GrantSigner:
    def __init__(self, private_key: Ed25519PrivateKey, kid: str) -> None: ...
    @classmethod
    def from_config(cls, key_b64: str, kid: str) -> "Ed25519GrantSigner": ...   # §4.1 rules
    def sign(self, claims: Mapping[str, object]) -> str:
        return jwt.encode(dict(claims), self._key, algorithm="EdDSA", headers={"kid": self._kid})
```

### 4.4 Resolver (`scores/replay_resolver.py`)

```python
class ReplayPinResolver:
    def __init__(self, cluster_store: ClusterStore, registry: RegistryService) -> None: ...
    async def resolve(self, pin: ReplayPin, raw_pin: str, *, benchmark_id: str,
                      caller: str | None, identity_verified: bool) -> ResolvedReplay: ...
```

Rules (write each as one small method; keep inside the ruff limits):

1. `benchmark = await Benchmark.get_or_none(id=benchmark_id)`; None → `PinNotFound(raw_pin)` (OD-5).
2. **`ResultPin` / `ScorePin`** (a direct pin):
   - `ResultPin`: `target = await cluster_store.load_replay_target(pin.result_id)`.
   - `ScorePin`: `rr = await ReportedResult.filter(head_id=pin.score_id, is_original=True).first()`; None → `PinNotFound`; else `load_replay_target(rr.id)`.
   - `target is None` → `PinNotFound`.
   - `access = replay_access(board_visibility=target.benchmark.visibility, redistributable=target.benchmark.redistributable, reporter=target.result.reporter, publication_state=target.publication_state, caller=caller, identity_verified=identity_verified)`.
   - `access == "not_found"` → `PinNotFound`. `target.result.cache_version_id is None` → `PinNotFound`. `access == "withdrawn"` → `PinWithdrawn`. `target.head.benchmark_id != benchmark_id` → `PinBenchmarkMismatch`.
   - This order is fixed: the 404 class first, then 410, then 422. WHY: a private or gated result on another board must answer 404, never 422 (no existence leak).
3. **`NamePin` / `RevisionPin`**: `revision = await registry.resolve_pin(raw_pin)` (a `RevisionRef`; the registry raises `PinNotFound`). Candidates: `ReportedResult.filter(is_original=True, cache_version_id__isnull=False, head__system_revision_id=revision.id, head__benchmark_id=benchmark_id)`. Order `submitted_at DESC, id DESC`. Take the first candidate whose access is not `not_found` (OD-3). If none → `PinNotFound`. Its access `withdrawn` → `PinWithdrawn`.
4. **`DatePin`**: `revisions = await registry.resolve_pin(raw_pin)` (a `list[RevisionRef]`, all revisions of the name, SR-H5). `t = pin.at` (already UTC, the date rules are the parser's). Candidates: ALL `ReportedResult` rows (original or not, RP-H2 "the newest accessible one"): `ReportedResult.filter(cache_version_id__isnull=False, submitted_at__lte=t, head__system_revision_id__in=[r.id for r in revisions], head__benchmark_id=benchmark_id)`. Order `submitted_at DESC, id DESC` (RP-D7 tie rule: the greater id wins). Take the first whose access is not `not_found`. None → `PinNotFound`. `withdrawn` → `PinWithdrawn`.
5. Page the candidate scan: read 100 rows at a time (`.order_by("-submitted_at", "-id").offset(k*100).limit(100).only("id", "head_id", "reporter", "cache_version_id", "submitted_at")`); stop at the first accessible row. Never load all rows of a big cluster. For the access check of a candidate, use the `benchmark` row of step 1 (every candidate is on it), the row's `reporter`, and its `publication_state` from ONE `CacheVersionPublication.filter(result_id__in=<page ids>)` read per page.
6. Return `ResolvedReplay(result_id=row.id, score_id=row.head_id, cache_version_id=row.cache_version_id)`. The pin resolves ONCE, here (RP-D4).

### 4.5 Route (`routes/replay_grants.py`)

```python
router = APIRouter(prefix="/v1", tags=["replay"])

@router.post("/replay-grants", response_model=ReplayGrantResponse, responses=...)
async def issue_replay_grant(body: ReplayGrantRequest, request: Request, response: Response
                             ) -> ReplayGrantResponse:
```

Steps:
1. `response.headers.update(PRIVATE_CACHE_HEADERS)`.
2. Identity (D5): `identity = await _caller(request)`, where `_caller` calls `write_identity(request)` (SB-meta §4.6a) and, on its `HTTPException`, raises a new `HTTPException(exc.status_code, exc.detail, headers=PRIVATE_CACHE_HEADERS)` (so the 401 and 403 also carry the private headers). `cloudflare_headers`: untrusted peer → 403 `UNTRUSTED_PEER_DETAIL`; no `X-User-Email` → 401 `identity_not_verified` (count `result="unauthenticated"`). `disabled`: `identity = None`. WHY a plain call and not the `WriteIdentity` dependency: a dependency raises before step 1, so its refusal would miss `PRIVATE_CACHE_HEADERS`.
3. `signer = request.app.state.grant_signer`; None → 503 `replay_unavailable` (count `result="unavailable"`).
4. `pin = parse_replay_pin(body.pin)`; `InvalidPin` → 422 `invalid_replay_pin` (count `result="invalid"`).
5. `identity_verified = identity_is_verified(settings.auth_mode)` (`routes/scores.py:76-84`). In `cloudflare_headers` step 2 guarantees `identity is not None`.
6. `now = clock()`; `resolved = await resolver.resolve(pin, body.pin, benchmark_id=body.benchmark_id, caller=identity, identity_verified=identity_verified)`. Map: `PinNotFound` (the registry error, raised by the registry or the resolver) → 404 (`not_found`), `PinWithdrawn` → 410 (`withdrawn`), `PinBenchmarkMismatch` → 422 (`mismatch`). `OperationalError` → 503 store unavailable.
7. `claims = build_grant_claims(subject=identity, cache_version_id=..., result_id=..., now=now)`; `grant = signer.sign(claims)`.
8. Count `result="issued"`. Return the response with `expires_at = datetime.fromtimestamp(claims["exp"], UTC)`.

INVARIANT: `signer.sign` is called ONLY after the resolver returned. Nothing is minted for a pin that does not resolve (RP-9, RP-E1).

`app.state.clock` is `Callable[[], datetime]`, default `lambda: datetime.now(UTC)`. Tests replace it.

Metric labels: `result ∈ {issued, not_found, withdrawn, mismatch, invalid, unavailable, unauthenticated}` (the PRD names the first four; the last three are added, G1). The counter stays in process (D7 X-15).

## 5. Migrations

None. This unit reads `ReportedResult`, `Score`, `Benchmark.redistributable`, `CacheVersionPublication` and the registry tables that SB-schema made. Performance: the candidate scans use `reported_result (head_id, submitted_at)` (SB-schema 0018; `id` is the tie-break in memory) and, for the head join, the partial unique index `uidx_scores_public_head` on `scores (benchmark_id, benchmark_revision, system_revision_id) WHERE system_revision_id IS NOT NULL` (SB-schema 0018, I-S1; the filters always carry `head__benchmark_id`). SB-schema gives `scores.system_revision_id` no index of its own on purpose (SB-schema §4.2). Do not add a migration here.

## 6. TDD order (RED first, risk order)

New directory `apps/scoreboard/tests/unit/replay/` with `__init__.py` and `conftest.py`.

`conftest.py`:
- `grant_key` → `(kid="sb-test-1", private_b64, public_key)`, where `private_b64 = base64.b64encode(k.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()` for `k = Ed25519PrivateKey.generate()`.
- `grant_cf_app` / `grant_cf_client` — **the main path (D5)**: `Settings.model_validate({... "auth_mode": "cloudflare_headers", "allowed_networks": "127.0.0.1/32", "clustering_enabled": True, ...})` and `monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")`. Copy the existing `cloudflare_headers` fixtures `app_with_cloudflare_auth` / `cloudflare_score_client` (`tests/unit/test_scores_routes.py:65-107`) with their WHY comments, and `untrusted_peer_score_client` (`:110-120`) as `grant_untrusted_client`.
- `grant_app` / `grant_client` — **the `disabled` fallback only** (RP-2a).
- Both apps: the grant key, a fixed clock `2026-09-29T12:00:00Z`, and the SB-submit receipt key. Import `make_receipt`, `URL4_A`, `URL4_B`, `ANA`, `BRUNO`, `as_user` from `tests.unit.submissions._receipts` (SB-submit §6). The owner is `ANA` (`"ana@x.org"`) and the non-owner is `BRUNO` (`"bruno@y.org"`) in every row below. Every seeded url4 is one of these constants (or another text that `url4.build` + `render` accept); an unparseable url4 gives 422 `invalid_url4`.
- Seed helpers that submit through `POST /v1/scores` (never insert rows by hand, so the data is what the real flow makes): `seed_result(client, *, benchmark, reporter, url4, score, submitted_at=None, receipt=True)`. On `grant_cf_client` it sends `headers=as_user(reporter)` and a receipt with `sub=reporter`, so `ReportedResult.reporter == reporter` is the verified email. To set an exact `submitted_at` for the date tests, update `ReportedResult.submitted_at` after the submit (test data only).
- Benchmarks: `pub` (public, `redistributable=True`), `gated` (public, `redistributable=False`), `priv` (private), `other` (public, redistributable). Set `redistributable` on the rows in the fixture (the admin route for it is unit WIRING, D6).
- Unless a row says otherwise, a route test uses `grant_cf_client` and sends `as_user(...)`.

Before RED: create the route with a body that raises `NotImplementedError`, the empty modules, and the settings. Each RED must fail on an assertion.

| # | Test id | File | Test name | RED reason |
|---|---|---|---|---|
| 1 | RP-1 | `test_grant_access.py` | `test_non_owner_private_pin_404_no_leak` — Ana's result on `priv`. Bruno pins `result:<id>` → 404 `replay_pin_not_found`; the body and headers equal those for `result:<random uuid>`; Ana → 200. | 500 (stub). |
| 2 | RP-2 | `test_grant_access.py` | `test_non_owner_non_redistributable_public_pin_404_owner_ok` — result on `gated`: Bruno 404, Ana 200. | 500. |
| 2a | RP-2a (disabled fallback) | `test_grant_access.py` | `test_disabled_fallback_sub_anonymous_public_ok_gated_and_private_404` — `grant_client`: seed the results directly with the models (a `disabled` submit cannot set a verified reporter); a pin on a `pub` result → 200 and the decoded `sub == "anonymous"`; a pin on a `gated` or `priv` result → 404 for every caller, also with a forged `X-User-Email: ana@x.org` (ignored in `disabled`). The only `disabled` test of the grant flow. | 500. |
| 3 | RP-3 | `test_grant_access.py` | `test_withdrawn_pin_410_for_non_owner_owner_ok` — set the `CacheVersionPublication.state = "withdrawn"` of Ana's `pub` result (test data); Bruno 410 `cache_version_withdrawn`; Ana 200. Also: withdrawn AND on `priv` → Bruno gets 404, not 410. | 500. |
| 4 | RP-4 | `test_grant_token.py` | `test_grant_claims_sub_aud_vid_rid_exp_12h_kid` — Bruno pins Ana's `pub` result. Decode the grant with the public key (`jwt.decode(..., algorithms=["EdDSA"], audience="aigateway", issuer="scoreboard")`): `sub == BRUNO` (the verified `X-User-Email`, D5); `vid` = the result's `cache_version_id`; `rid` = the result id; `exp - iat == 43200`; `iat` = the fixed clock; header `kid == "sb-test-1"`, `alg == "EdDSA"`; `expires_at` = `exp`. | 500. |
| 5 | RP-4a | `test_grant_token.py` | `test_grant_life_is_fixed_at_12_hours` — `GRANT_TTL_S == 43200`; `build_grant_claims(..., now=t)` gives `exp - iat == 43200` for two different `t`; `"replay_grant_ttl_s" not in Settings.model_fields` (D4: no setting, no refresh). | the stub returns `{}`. |
| 6 | RP-4b | `test_grant_token.py` | `test_create_app_refuses_bad_or_half_configured_grant_key` — key without kid; kid without key; a key that is not base64; base64 of 16 bytes → `ValueError`, and the message holds no key text. | no startup check. |
| 7 | RP-4c | `test_grant_token.py` | `test_no_signing_key_answers_503_replay_unavailable` | 500. |
| 7a | RP-4d | `test_grant_access.py` | `test_verified_identity_required_in_cloudflare_mode` — `grant_cf_client` with no header → 401 `identity_not_verified`; `grant_untrusted_client` with `as_user(ANA)` → 403 with the plain `UNTRUSTED_PEER_DETAIL`; both carry `Cache-Control: private, no-store`; a spy `GrantSigner` records ZERO `sign` calls; `scoreboard_replay_grants_total{result="unauthenticated"}` == 2. (D5) | 500. |
| 8 | RP-6 | `test_pin_resolution.py` | `test_pin_by_date_newest_at_or_before_T_across_revisions` — `kevins-best` r1 result on 2026-08-10, r2 result on 2026-09-05 (Kevin declares r2 with `revision_of`); `kevins-best@2026-09-01` → the 2026-08-10 result; `kevins-best@2026-09-06` → the r2 result. | 500. |
| 9 | RP-7 | `test_pin_resolution.py` | `test_pin_by_date_boundaries` — parametrized: date-only `2026-09-05` includes a result at `2026-09-05T23:59:59Z`; `2026-09-05T10:00:00+02:00` equals `08:00Z` and includes a result at exactly `08:00:00Z` (≤ T); a future date → the newest; two results with the same `submitted_at` → the greater `id`. The date and offset cases go through the real `parse_pin` (no second date rule here). | stubs. |
| 10 | RP-8 | `test_pin_resolution.py` | `test_pin_forms_resolve_result_score_name_revision` — `result:<non-original id>` → that result; `score:<head>` → the original; `kevins-best` → the newest versioned original of the LATEST revision on `pub`; `kevins-best@r1` → the r1 original. | stubs. |
| 11 | RP-8a | `test_pin_resolution.py` | `test_name_pin_picks_newest_versioned_original_and_does_not_skip_withdrawn` — `kevins-best` r1 has two heads on `pub` (benchmark revisions `R1` older, `R2` newer). Case A: the `R2` original has no cache version → the pin gives the `R1` original. Case B: both have versions and the `R2` publication is `withdrawn` → Bruno gets 410 (not the `R1` result; OD-3); Kevin gets the `R2` result. | stubs. |
| 12 | RP-9 | `test_grant_access.py` | `test_unknown_pin_404_before_run_no_spend` — unknown name, unknown result id, a name with no versioned result, an unknown `benchmark_id`: all 404 with one body; a spy `GrantSigner` records ZERO `sign` calls; `scoreboard_replay_grants_total{result="not_found"}` == 4. | 500. |
| 13 | RP-9a | `test_grant_access.py` | `test_malformed_pin_422_invalid_replay_pin` — `"x@r0"`, `"x@2026-13-01"`, `"x@2026-09-01T10:00:00"` (no offset), `"result:not-a-uuid"`, `"score:"` → 422 `invalid_replay_pin`; no sign call; plus unit rows for `parse_replay_pin` (`result:<uuid>` → `ResultPin`, `score:<uuid>` → `ScorePin`, `kevins-best@r1` → `RevisionPin`). | 500. |
| 14 | RP-10 | `test_pin_resolution.py` | `test_benchmark_mismatch_422` — Ana's result on `other`; Bruno pins `result:<id>` with `benchmark_id="pub"` → 422 `replay_benchmark_mismatch`; the same pin on a `priv` result of Ana, for Bruno → 404 (not 422). | stubs. |

## 7. Edge cases, what not to do, gates

Edge cases:
- `cloudflare_headers` (production): a caller with no verified identity gets 401 (RP-4d); the resolver never runs.
- The `disabled` fallback: `write_identity` returns None, so nobody is an owner. Private and gated results give 404 to all; public results work with `sub = "anonymous"` (RP-2a). A gateway in `cloudflare_headers` rejects such a grant on the `sub` check (C6); that is expected for a dev/local stack only.
- A grant that expires during a long run (the `GRANT_TTL_S` docstring in §4.3, D4): the run fails with the typed replay error. This unit does not refresh it.
- A result without a cache version (submitted without a receipt) never resolves (404).
- A pin with a trailing space is the parser's concern (SR-20); do not strip it here.
- The grant response must not be cached by a proxy (`PRIVATE_CACHE_HEADERS` on every answer).

What not to do:
- Do not write to the database. Do not create a grant row. There is no revocation list in v1 (DR-2).
- Do not import `jwt` outside `adapters/`. The core owns the `GrantSigner` port.
- Do not log the grant, the key, or the caller email (log the result id and the outcome).
- Do not call the gateway. The scoreboard never calls the gateway (DR-2).
- Do not copy the access rule. Use `core/replay_access.py` from SB-submit.
- Do not import from another app, and never `screamingface`.

Overlap with SB-publish (same wave 4): see §2 "Integration notes". This unit merges first.

Gates: from the repo root `uv run .claude/scripts/run_gates.py scoreboard --base "$(git merge-base HEAD e14-reproducible-submission-spec)"`.

## 8. Verification (definition of done)

1. The gate command exits 0; the append-only check passes.
2. `uv run pytest tests/unit/replay -v` in `apps/scoreboard`: all rows of §6 green.
3. `uv run pytest -q`: the whole old suite green, unchanged.
4. A manual check in the ledger: decode one grant from the test with `python -c` and paste the header and the claims (not the key).
5. No chart file is in the diff (`git diff --name-only "$(git merge-base HEAD e14-reproducible-submission-spec)" -- apps/scoreboard/charts` is empty; D6).
6. Design review (Opus) with this plan as the rubric. Then commit on `unit/SB-grants` for the integrator (D1). No PR.

## 9. Open decisions and spec gaps

No open decision is left in this unit.

## 10. Decided

- **OD-1 (A3) — Decided: D4.** `exp = iat + 43,200 s` (12 h), a constant, no setting, no refresh. A3 is "[checked] false, accepted". The limit is documented in `GRANT_TTL_S` (§4.3) and in `DEPLOYMENT.md`: the job deadline (57,600 s, `apps/screamingface-engine/src/screamingface_engine/config.py:148-151`) plus the queue wait can exceed the grant life, and a grant that expires during a run fails that run with the typed error (the RP-14 path).
- **OD-2 (subject) — Decided: D5.** Production runs `cloudflare_headers`: `sub` is the verified `X-User-Email`, and a caller with no verified identity gets 401 / 403 (RP-4d). The `disabled` dev/local fallback keeps `sub = "anonymous"` (RP-2a).
- **OD-3 (name pins) — decided (default).** The newest versioned original by `(submitted_at, id)`; skip `not_found` results; do not skip a withdrawn one (answer 410).
- **OD-4 (503 when not configured) — decided (default).** `503 replay_unavailable`.
- **OD-5 (unknown benchmark) — decided (default).** The 404 `replay_pin_not_found`.
- **OD-6 (who sets `redistributable`) — Decided: D6.** Unit WIRING adds the audited admin route. This unit only reads the column.
- **G1 — decided (default).** The metric labels `invalid`, `unavailable` and `unauthenticated` are added to the PRD list.
- **G2 — Decided: D7 X-3.** PyJWT EdDSA behind the service-local `GrantSigner` port. No shared package.
- **G3 (key form) — Decided: D7 X-4.** Base64 of the raw 32-byte key; the kid comes from `SCOREBOARD_REPLAY_GRANT_SIGNING_KID`.
- **Error body — Decided: D7 X-8.** `{"detail": {"code", "message", ...}}` for every new error.
