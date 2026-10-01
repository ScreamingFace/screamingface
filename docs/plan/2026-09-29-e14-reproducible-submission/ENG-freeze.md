---
title: Engine freeze proxy route (POST /v1/cache-versions)
unit: ENG-freeze
epic: OME-1307 (E14)
component: apps/screamingface-engine
wave: 2
status: draft (for review)
date: 2026-09-29
spec: docs/spec/2026-09-29-e14-reproducible-submission/contracts.md (C2a, C2b, DR-4)
plan: docs/plan/2026-09-29-e14-reproducible-submission/ENG-freeze.md
branch: unit/ENG-freeze (from the e14-reproducible-submission-spec HEAD; D1)
---

# ENG-freeze — the engine freeze proxy route

> **For the implementer (Sonnet).** Follow the `sdlc-python` loop: ledger, RED, GREEN, gates,
> commit. Do not make a design decision. If this plan does not answer a question, stop and ask.

**Goal.** Add one engine route, `POST /v1/cache-versions`. The route takes a `trace_id` from
the SDK. It forwards the request to the AI Gateway route `POST /v1/cache-versions` with the
caller identity. It gives the gateway's receipt back to the SDK without a change.

**Architecture.** Hexagonal. The core defines a port `CacheVersions`. An adapter
`AigatewayCacheVersions` implements the port with `httpx`. A REST router calls the port only.
This is the same shape as the provider-connection subsystem:

| Existing exemplar | New module |
|---|---|
| `src/screamingface_engine/connections/port.py:23-40, 63-148` (Caller, typed errors, Protocol) | `src/screamingface_engine/cache_versions/port.py` |
| `src/screamingface_engine/connections/aigateway.py:65-238` (adapter, `_request`) | `src/screamingface_engine/cache_versions/aigateway.py` |
| `src/screamingface_engine/connections/__init__.py:27-53` (`build_connections`) | `src/screamingface_engine/cache_versions/__init__.py` |
| `src/screamingface_engine/connections/upstream_errors.py:18-35` (status map) | inside `cache_versions/aigateway.py` (`_raise_for_status`) |
| `src/screamingface_engine/rest/connections.py:31-68, 158-191` (route class, `_caller`, `_service`, `_mark_private`) | `src/screamingface_engine/rest/cache_versions.py` |

**Tech stack.** Python 3.13, FastAPI, pydantic v2, httpx, pytest, pytest-asyncio (strict mode).

**Delivery (D1).** All E14 units land on the one branch `e14-reproducible-submission-spec`.
There is no per-unit PR, no Linear issue and no per-unit CI merge gate. Build this unit in a
temporary worktree on branch `unit/ENG-freeze`, made from the HEAD of the e14 branch after the
wave-1 integration: `git worktree add .claude/worktrees/unit-ENG-freeze e14-reproducible-submission-spec`,
then, in that worktree, `git checkout -B unit/ENG-freeze e14-reproducible-submission-spec`.
Commit on `unit/ENG-freeze` only. After wave 2, the integrator merges the unit branches into
the e14 branch in sequence and runs the gates.

## 0. Integration notes (D2)

- **Wave 2** with SB-meta, SB-registry, GW-freeze and SDK-meta.
- **Shared files with other wave-2 units: none.** `.claude/scripts/check_layering.py` is changed
  only by this unit in E14 (URL4-fp and SB-registry enforce C11 with unit tests, D7 X-18).
  GW-freeze changes `apps/aigateway` only; SDK-meta changes `packages/screamingface` only.
- **Files that a later unit also changes:** `apps/screamingface-engine/CHANGELOG.md` (ENG-replay,
  wave 3, adds its own line under `## Unreleased`). ENG-replay starts from the e14 HEAD after this
  unit merged, so it appends below this line.
- **Wave-1 file that is already merged:** `apps/screamingface-engine/uv.lock` (URL4-fp, D7 X-25).
  This unit does not change `uv.lock`.

## 1. Scope

### 1.1 Test ids this unit owns

| Id | Test | Level | Source |
|---|---|---|---|
| SC-21 | `engine_cache_versions_route_proxies_with_caller_identity` | integration | `prd/submit-and-cluster.md` §7, contracts C2a, C2b |

SC-21 is one contract. This plan splits it into named test functions (SC-21a to SC-21l in §6).
All of them are SC-21. Do not add other PRD test ids.

### 1.2 Out of scope

- The gateway freeze service, the receipt signing, and the gateway route (GW-freeze, CV-7 to
  CV-15). This unit uses a fake gateway (`httpx.MockTransport`).
- The SDK freeze call, its 60 s timeout, its retry, and the "submit without a version" rule
  (SDK-submit, SC-18, SC-19, SC-20).
- The replay grant, the `X-SF-Cache-Replay` header, and the version counters (ENG-replay).
- Any retry in the engine. C2b says: "No engine retry; the SDK owns the retry."
- Decoding or verifying the receipt JWS. The engine treats the receipt as an opaque string.
- Prometheus metrics for this route. The spec names none.
- The Helm chart. The route uses the existing `aigateway_base_url` setting
  (`src/screamingface_engine/config.py:160`, chart key `URL4_CLOUD_AIGATEWAY_BASE_URL` at
  `deploy/helm/templates/configmap.yaml:73`). No new setting. The E14 chart, Secret and bucket
  work (gateway and scoreboard) belongs to WIRING (wave 5, D6).

## 2. Depends on

- **Merged units:** none. The unit map lists `depends_on: []`. Build against a fake gateway.
- **Contracts implemented:** C2a (SDK → engine, the engine side) and C2b (engine → gateway,
  the engine client side).
- **Contracts consumed:** C2b response shape and error codes from GW-freeze. Do not wait for
  GW-freeze. The shapes below are the contract.
- **Contract C11 row 3 (Decided: D7, X-6):** "no `jwt` import outside
  `screamingface_engine/auth/`". The engine never decodes a JWS. This unit adds no `jwt` import.

## 3. Global constraints

- **Append-only test gate.** `.claude/scripts/run_gates.py` (`append_only_check`, lines
  380-440) forbids a change to any line of an existing test function, fixture, helper, class
  header or module-level assignment. Put every new test in a **new file**. Do not edit
  `tests/unit/_fakes.py` or any existing test file.
- **Layering gate.** `.claude/scripts/check_layering.py` classifies modules. A new top-level
  package that is not in `CONTROL_PLANE` is a "shared leaf" (lines 63-89). The new
  `cache_versions` package is control plane, so add it to `CONTROL_PLANE` (see §4, file 10;
  Decided: D7, X-18).
- **No secret, no body echo.** Never log the receipt. Never copy an upstream error `message`
  into the engine response. Only the stable `code` crosses (same rule as
  `connections/port.py:73-78`).
- **Identity (D5).** The engine forwards only the verified identity headers
  (`job_env.identity_from_headers`, `src/screamingface_engine/job_env.py:76-90`). It never
  forwards `Authorization`, `Cookie` or `URL4-Capability`. In production the whole system relies
  on the Cloudflare identity headers: the Cloudflare Access/Envoy edge sets the verified
  `X-User-Email`, the engine forwards it, and the gateway runs `AIGW_AUTH_MODE=cloudflare_headers`
  (`apps/aigateway/charts/aigateway/values-prod.yaml:18`). The gateway, not the engine, verifies
  the identity (peer check, then the header read). No engine change is needed for this.
- **Credentials.** The engine holds no AI Gateway credential. Do not add one. AIGateway
  credentials live only in the gateway `credential_blobs` table. No OS keychain.
- **Imports.** The engine never imports `apps/aigateway` or `apps/scoreboard` code.

## 4. Files

| # | Path | Change | Exemplar to imitate |
|---|---|---|---|
| 1 | `apps/screamingface-engine/src/screamingface_engine/cache_versions/__init__.py` | create | `connections/__init__.py:1-71` |
| 2 | `apps/screamingface-engine/src/screamingface_engine/cache_versions/port.py` | create | `connections/port.py:23-196` |
| 3 | `apps/screamingface-engine/src/screamingface_engine/cache_versions/aigateway.py` | create | `connections/aigateway.py:65-238`, `connections/upstream_errors.py:18-35` |
| 4 | `apps/screamingface-engine/src/screamingface_engine/rest/cache_versions.py` | create | `rest/connections.py:1-278` |
| 5 | `apps/screamingface-engine/src/screamingface_engine/rest/__init__.py` | change: export `cache_version_router` | `rest/__init__.py:11` |
| 6 | `apps/screamingface-engine/src/screamingface_engine/app.py` | change: `_ROUTERS`, `create_app` kwarg, `create_app_from_env` wiring | `app.py:76-85, 109, 124, 620-644` |
| 7 | `apps/screamingface-engine/src/screamingface_engine/local.py` | change: local wiring and shutdown | `local.py:465-491` |
| 8 | `apps/screamingface-engine/src/screamingface_engine/connections/port.py` | change: add `Caller.upstream_headers()` | `connections/aigateway.py:386-412` (move the logic) |
| 9 | `apps/screamingface-engine/src/screamingface_engine/connections/aigateway.py` | change: `_headers(caller)` returns `caller.upstream_headers()` | — |
| 10 | `.claude/scripts/check_layering.py` | change: add `"cache_versions"` to `CONTROL_PLANE` | `check_layering.py:66-89` (`"reaper"` entry and its WHY comment) |
| 11 | `apps/screamingface-engine/tests/unit/test_cache_versions_aigateway.py` | create | `tests/unit/test_connections_aigateway.py:1-60` |
| 12 | `apps/screamingface-engine/tests/unit/test_rest_cache_versions.py` | create | `tests/unit/test_rest_connections.py:1-95` |
| 13 | `apps/screamingface-engine/tests/integration/test_cache_versions_proxy.py` | create | `tests/unit/test_rest_connections.py:85-95` plus `tests/unit/test_connections_aigateway.py:28-41` |
| 14 | `apps/screamingface-engine/CHANGELOG.md` | change: one line under `## Unreleased` | `CHANGELOG.md:3-5` |
| 15 | `docs/work/<date>-e14-eng-freeze.md` | create (work ledger, repo rule; `ticket: unfiled`) | `docs/work/TEMPLATE.md` |

Why file 8 and 9: the new adapter needs the same header rule as the connections adapter
(identity first, then the gateway-owned `X-Profile` and `traceparent` last). DRY: move the
body of `connections/aigateway.py:_headers` into a method on `Caller`, and let both adapters
call it. The behavior of `_headers` must not change. The existing tests in
`tests/unit/test_connections_aigateway.py` and `tests/unit/test_selector_connections.py` are
the safety net. They must stay green without an edit.

## 5. Signatures and data shapes

### 5.1 `cache_versions/port.py` (the core port; imports nothing from `screamingface_engine` except `connections.port.Caller`)

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from screamingface_engine.connections.port import Caller

CoverageStatus = Literal["complete", "partial"]


@dataclass(frozen=True, slots=True)
class FrozenCacheVersion:
    """The gateway's freeze answer, validated, opaque receipt included."""

    receipt: str               # compact JWS; opaque; never decoded, never logged
    cache_version_id: str      # canonical UUID text, as the gateway sent it
    entry_count: int           # >= 0
    call_count: int            # >= 0
    missing_count: int         # >= 0
    coverage_status: CoverageStatus
    archive_sha256: str        # 64 lowercase hex
    created: bool              # True when the gateway answered 201, False for 200 (idempotent)


class CacheVersionError(Exception):
    """A safe freeze failure with its public HTTP mapping. Same shape as ConnectionError."""

    status = 502
    title = "Bad Gateway"
    detail = "AI Gateway returned an unusable cache version response"
    code: str | None = None

    def __init__(self, detail: str | None = None) -> None:
        self.internal_detail = detail
        super().__init__(self.detail)


class TraceNotCaptured(CacheVersionError):       # 404
    status, title = 404, "Not Found"
    detail = "no captured calls exist for this trace"
    code = "trace_not_captured"

class CacheVersionTooLarge(CacheVersionError):   # 413
    status, title = 413, "Content Too Large"
    detail = "the trace is too large to freeze as one cache version"
    code = "cache_version_too_large"

class CaptureDisabled(CacheVersionError):        # 503
    status, title = 503, "Service Unavailable"
    detail = "cache version capture is disabled on AI Gateway"
    code = "capture_disabled"

class CacheVersionUnauthorized(CacheVersionError):  # 401
    status, title = 401, "Unauthorized"
    detail = "AI Gateway did not accept the caller identity"

class CacheVersionForbidden(CacheVersionError):     # 403
    status, title = 403, "Forbidden"
    detail = "AI Gateway refused the freeze for this caller"

class CacheVersionRateLimited(CacheVersionError):   # 429
    status, title = 429, "Too Many Requests"
    detail = "cache version requests are temporarily rate limited"

class CacheVersionBadResponse(CacheVersionError):   # 502 (the base values)
    pass

class CacheVersionsUnavailable(CacheVersionError):  # 503
    status, title = 503, "Service Unavailable"
    detail = "AI Gateway is unavailable"

class CacheVersionTimeout(CacheVersionError):       # 504
    status, title = 504, "Gateway Timeout"
    detail = "AI Gateway did not answer the freeze in time"


@runtime_checkable
class CacheVersions(Protocol):
    """The engine-facing freeze port."""

    async def freeze(self, caller: Caller, trace_id: str) -> FrozenCacheVersion: ...

    async def aclose(self) -> None: ...
```

Write each class attribute on its own line (the tuple form above is only to keep this plan
short). Export all names in `__all__`.

### 5.2 `cache_versions/aigateway.py` (the adapter)

```python
_FREEZE_PATH = "/v1/cache-versions"

class AigatewayCacheVersions:
    def __init__(self, client: httpx.AsyncClient) -> None: ...
    async def freeze(self, caller: Caller, trace_id: str) -> FrozenCacheVersion: ...
    async def aclose(self) -> None: ...   # await self._client.aclose()
```

Behavior of `freeze`:

1. Send `POST /v1/cache-versions` with `json={"trace_id": trace_id}` and
   `headers=caller.upstream_headers()`.
2. `httpx.TimeoutException` → raise `CacheVersionTimeout`. Any other `httpx.HTTPError` →
   raise `CacheVersionsUnavailable`. Log only the exception class name (imitate
   `connections/aigateway.py:228-236`). **No retry.**
3. Map a non-2xx status with `_raise_for_status(response)`:

   | Gateway status | Gateway `detail.code` | Raise |
   |---|---|---|
   | 404 | any | `TraceNotCaptured` |
   | 413 | any | `CacheVersionTooLarge` |
   | 503 | `capture_disabled` | `CaptureDisabled` |
   | 503 | other or none | `CacheVersionsUnavailable` |
   | 401 | any | `CacheVersionUnauthorized` |
   | 403 | any | `CacheVersionForbidden` |
   | 429 | any | `CacheVersionRateLimited` |
   | 504 | any | `CacheVersionTimeout` |
   | any other non-2xx (400, 409, 422, 500, 502, 3xx) | any | `CacheVersionBadResponse` |

   Read the gateway code from the FastAPI error body shape `{"detail": {"code": "..."}}`
   (the gateway pattern at `apps/aigateway/src/aigateway/routes/chat.py:411-414`; the coded
   error body of D7, X-8, which GW-freeze §4.7 emits). A body that
   is not JSON, or has no such code, means "no code". Never raise from the body parse.
4. A 2xx other than 200 and 201 → `CacheVersionBadResponse`.
5. Validate the 200 or 201 body. It must be a JSON object with **exactly** these keys:
   `receipt`, `cache_version_id`, `entry_count`, `call_count`, `missing_count`,
   `coverage_status`, `archive_sha256`. Rules:
   - `receipt`: `str`, non-blank after `strip()`. Keep the value as sent (do not strip it).
   - `cache_version_id`: `str` that `uuid.UUID(...)` accepts.
   - `entry_count`, `call_count`, `missing_count`: `int`, not `bool`, `>= 0`.
   - `coverage_status`: `"complete"` or `"partial"`.
   - `archive_sha256`: matches `^[0-9a-f]{64}$`.
   Any failure → `CacheVersionBadResponse`.
6. Return `FrozenCacheVersion(..., created=response.status_code == 201)`.

Do not add cross-field rules (for example `call_count == entry_count + missing_count`). The
contract does not state them.

### 5.3 `cache_versions/__init__.py`

```python
_UPSTREAM_TIMEOUT_S = 55.0   # C2b: 55 s, less than the SDK's 60 s, so the engine answers first

class _CacheVersionSettings(Protocol):
    aigateway_base_url: str | None

def _default_client(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=_UPSTREAM_TIMEOUT_S)

def build_cache_versions(
    settings: _CacheVersionSettings,
    *,
    client_factory: Callable[[str], httpx.AsyncClient] = _default_client,
) -> CacheVersions | None:
    """None when no gateway is configured; the route then answers 503."""
```

Re-export the port names and `build_cache_versions` in `__all__`.

### 5.4 `connections/port.py` — `Caller.upstream_headers`

Add this method to the existing `Caller` dataclass. Move the body of
`connections/aigateway.py:_headers` (lines 386-412) here without a behavior change, and keep
its INVARIANT docstring:

```python
def upstream_headers(self) -> dict[str, str]:
    headers = dict(self.identity)
    if self.profile is not None:
        headers["X-Profile"] = self.profile
    if self.traceparent is not None:
        headers["traceparent"] = self.traceparent
    return headers
```

Then `connections/aigateway.py:_headers(caller)` becomes `return caller.upstream_headers()`.

### 5.5 `rest/cache_versions.py` (the REST adapter)

Route: `POST /v1/cache-versions`, tag `"Cache versions"`, `status_code=201` as the default.

```python
class FreezeRequest(BaseModel):
    """Freeze the calls of one captured run trace as an immutable cache version."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    trace_id: str   # validated by the rules below


class CacheVersionReceiptResponse(BaseModel):
    """AI Gateway's signed freeze receipt and the version's counts, relayed unchanged."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    receipt: str
    cache_version_id: str
    entry_count: int
    call_count: int
    missing_count: int
    coverage_status: Literal["complete", "partial"]
    archive_sha256: str
```

- `trace_id` rule: `^[0-9a-f]{32}$`, and not 32 zeros (W3C trace-id rules). Use a pydantic
  `field_validator`. The SDK sends the lowercase hex id it minted
  (`packages/screamingface/src/screamingface/_engine/transport.py:180-183`).
- Route class `_ProblemRoute(APIRoute)`: imitate `rest/connections.py:31-57`.
  1. Call `refuse_selector(request.headers)` first (OME-1381: every REST surface refuses a
     stated `X-Profile` with `400 x_profile_unsupported`).
  2. Map `RequestValidationError` to
     `ProblemException(status=422, title="Unprocessable Content",
     detail="the freeze request is invalid", code="invalid_freeze_request")`.
     Do not echo the input.
- Router: `APIRouter(tags=["Cache versions"], route_class=_ProblemRoute,
  dependencies=[Depends(_declare_x_profile)])`, where `_declare_x_profile` imitates
  `rest/connections.py:60-61`.
- `_caller(request)`: the same as `rest/connections.py:158-170`:
  `Caller(job_env.identity_from_headers(request.headers),
  traceparent=valid_traceparent(request.headers.get("traceparent")))`. No profile.
- `_service(request)`: `request.app.state.cache_versions`, or raise
  `ProblemException(status=503, title="Service Unavailable",
  detail="cache versions are not configured on this Engine", code="cache_versions_unconfigured")`.
- Handler:

```python
@router.post("/v1/cache-versions", status_code=201, response_model=CacheVersionReceiptResponse,
             summary="Freeze a run's cache version", responses=_error_responses())
async def freeze_cache_version(request: Request, body: FreezeRequest,
                               response: Response) -> CacheVersionReceiptResponse:
    try:
        frozen = await _service(request).freeze(_caller(request), body.trace_id)
    except CacheVersionError as exc:
        logger.info("cache version freeze failed: %s", type(exc).__name__)
        raise ProblemException(status=exc.status, title=exc.title,
                               detail=exc.detail, code=exc.code) from exc
    response.status_code = 201 if frozen.created else 200
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "X-User-Email"
    return CacheVersionReceiptResponse(...)   # copy every field except `created`
```

- `_error_responses()`: imitate `rest/connections.py:113-136`. Document 400, 401, 403, 404,
  413, 422, 429, 502, 503, 504 as RFC 9457 problems. The 400 text must name
  `x_profile_unsupported` (the OME-1381 OpenAPI invariant, `tests/unit/test_selector_openapi.py:1-10`:
  every operation that refuses `X-Profile` declares the header and a 400 problem that names the
  code). The 404, 413 and 503 texts name `trace_not_captured`, `cache_version_too_large`,
  `capture_disabled` and `cache_versions_unconfigured`. Also document `200` ("idempotent
  re-freeze").
- Log lines: never log `trace_id`, the receipt, or the identity. Log only the error class
  name.

### 5.6 `app.py` and `local.py` wiring

- `app.py`: import `cache_version_router` from `screamingface_engine.rest`, and add it to
  `_ROUTERS` right after `connection_router` (line 82). Add the keyword argument
  `cache_versions: CacheVersions | None = None` to `create_app` (after `connections`, line 109),
  and set `app.state.cache_versions = cache_versions` (after line 124).
- `create_app_from_env` (`app.py:620-644`): build
  `cache_versions = build_cache_versions(settings)`, pass it to `create_app`, and register
  `app.router.on_shutdown.append(cache_versions.aclose)` when it is not `None`.
- `local.py:465-491`: build `cache_versions = build_cache_versions(settings)` beside
  `connections`, pass it to `create_app`, and add it to the shutdown loop
  `for adapter in (catalog, connections, cache_versions):`. The local settings already carry
  the loopback gateway address (`local.py:173-182`).
- `rest/__init__.py`: add
  `from screamingface_engine.rest.cache_versions import router as cache_version_router` and add
  `"cache_version_router"` to `__all__`.

### 5.7 Headers, codes and statuses (the complete C2a contract, engine side)

| Engine answer | When | Problem `code` |
|---|---|---|
| `201` + body | gateway 201 | — |
| `200` + body | gateway 200 (idempotent re-freeze, CV-D3) | — |
| `400` | request states `X-Profile` | `x_profile_unsupported` |
| `401` | gateway 401 | none |
| `403` | gateway 403 | none |
| `404` | gateway 404 | `trace_not_captured` |
| `413` | gateway 413 | `cache_version_too_large` |
| `422` | body fails `FreezeRequest` | `invalid_freeze_request` |
| `429` | gateway 429 | none |
| `502` | gateway answer unusable (other status, bad body) | none |
| `503` | no gateway configured | `cache_versions_unconfigured` |
| `503` | gateway `503 capture_disabled` | `capture_disabled` |
| `503` | gateway unreachable, or other 503 | none |
| `504` | engine timeout (55 s), or gateway 504 | none |

## 6. Migrations

None. The engine has no database. No schema change in this unit.

## 7. TDD order (RED first, risk order)

All tests are new files. Use `pytestmark = pytest.mark.asyncio` in async files. Before the
first RED, create empty stubs so that each failure is an **assertion**, not an import error:
the package `cache_versions` with the port names, an `AigatewayCacheVersions.freeze` that
raises `NotImplementedError`, and a route that returns `501`. Do not register the stub route
as done: SC-21a must fail on its assertions.

There are no CHAR rows in the PRD for this unit. The existing connection tests are the
safety net for file 8 and 9: run them first and see them green.

| Order | Id | File | Test function | RED reason (what fails before the change) |
|---|---|---|---|---|
| 0 | safety | `tests/unit/test_connections_aigateway.py`, `tests/unit/test_selector_connections.py`, `tests/unit/test_rest_connections.py` (existing) | all | none; they must stay green after the `Caller.upstream_headers` move |
| 1 | SC-21a | `tests/integration/test_cache_versions_proxy.py` | `test_engine_cache_versions_route_proxies_with_caller_identity` | The stub answers 501. Assert: engine status 201; the fake gateway saw exactly one `POST /v1/cache-versions` with body `{"trace_id": T}`, header `X-User-Email: ana@example.org`, and a valid `traceparent` when the client sent one; no `Authorization`, `Cookie` or `URL4-Capability` header reached the gateway; the engine body equals the gateway body key by key. |
| 2 | SC-21b | same file | `test_idempotent_refreeze_relays_200_and_the_same_receipt` | Fake gateway answers 200. Assert engine status 200 and the same `receipt` and `cache_version_id`. |
| 3 | SC-21c | same file | `test_trace_not_captured_is_a_404_problem_with_its_code` | Gateway `404 {"detail":{"code":"trace_not_captured","message":"secret-text"}}`. Assert 404, `application/problem+json`, `code == "trace_not_captured"`, and `"secret-text"` is not in the body. |
| 4 | SC-21d | same file | `test_too_large_is_a_413_problem_with_its_code` | Gateway 413. Assert 413 and `code == "cache_version_too_large"`. |
| 5 | SC-21e | same file | `test_capture_disabled_is_a_503_problem_with_its_code` | Gateway `503 capture_disabled`. Assert 503 and the code. |
| 6 | SC-21f | `tests/unit/test_cache_versions_aigateway.py` | `test_a_timeout_is_a_504_and_is_not_retried` | MockTransport raises `httpx.ReadTimeout`. Assert `CacheVersionTimeout` and exactly **one** request was sent. |
| 7 | SC-21g | same file | `test_a_transport_error_is_unavailable_and_is_not_retried` | MockTransport raises `httpx.ConnectError`. Assert `CacheVersionsUnavailable` and one request. |
| 8 | SC-21h | same file | `test_a_malformed_success_body_is_a_bad_response` (parametrize: missing key, extra key, bad UUID, negative count, bool count, bad coverage, bad sha, blank receipt, non-JSON) | Assert `CacheVersionBadResponse` for each case. |
| 9 | SC-21i | same file | `test_the_status_map` (parametrize over the table in §5.2) | Assert the named error class for each status and code. |
| 10 | SC-21j | `tests/unit/test_rest_cache_versions.py` | `test_an_invalid_trace_id_is_a_422_problem_before_any_gateway_call` (parametrize: uppercase hex, 31 chars, 33 chars, all zeros, extra body key, missing key) | Fake port records calls. Assert 422, `code == "invalid_freeze_request"`, and zero port calls. |
| 11 | SC-21k | same file | `test_a_stated_x_profile_is_refused_before_the_port` | Send `X-Profile: p`. Assert 400, `code == "x_profile_unsupported"`, and zero port calls. |
| 12 | SC-21l | same file | `test_an_unconfigured_engine_answers_503` and `test_the_route_is_published_in_openapi_with_its_problems` | `create_app(..., cache_versions=None)`, and send a **valid** body (the 422 check runs before the handler). Assert 503 `cache_versions_unconfigured`. Assert `/v1/cache-versions` `post` is in `app.openapi()["paths"]` with 201, 200, 400, 404, 413, 503 responses; the 400 response is `application/problem+json` and its description contains `x_profile_unsupported`; the operation declares an `X-Profile` header parameter (imitate `tests/unit/test_selector_openapi.py:43-62`). |
| 13 | SC-21m | same file | `test_the_answer_is_private_and_never_cached` | Assert `Cache-Control: private, no-store` and `Vary: X-User-Email` on 201. |

Test wiring:

- SC-21a to SC-21e use the **real** route and the **real** adapter:
  `create_app(Settings(jwt_secret="t"), stream=InMemoryEventStream(),
  cache_versions=AigatewayCacheVersions(httpx.AsyncClient(base_url="http://aigateway.test",
  transport=httpx.MockTransport(handler))))`, driven by
  `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`
  (imitate `tests/unit/test_rest_connections.py:85-95` and
  `tests/unit/test_connections_aigateway.py:28-41`).
- SC-21j to SC-21m use a `FakeCacheVersions` class in the test file (imitate
  `tests/unit/test_rest_connections.py:27-82`). It records `(caller, trace_id)` and returns or
  raises what the test sets.
- Oracle values come from contracts.md C2a (the example body):
  `{"receipt": "<JWS>", "cache_version_id": "<uuid>", "entry_count": 412, "call_count": 420,
  "missing_count": 8, "coverage_status": "partial", "archive_sha256": "<64-hex>"}`.
  Use a literal receipt such as `"eyJhbGciOiJFZERTQSJ9.e30.c2ln"`. It is opaque; never decode it.

## 8. Edge cases

- **Production identity (D5).** The Cloudflare Access/Envoy edge sets `X-User-Email`; the
  engine forwards it; the gateway (`cloudflare_headers`) verifies it and scopes the freeze to that
  account. SC-21a pins that the header reaches the gateway unchanged.
- **Blank identity.** A request with no `X-User-Email` (the dev/local fallback, gateway auth
  `disabled`) is still forwarded. The gateway decides. The engine does not refuse it. In
  `cloudflare_headers` mode the gateway refuses it (401, passed through with no code).
- **Forged gateway-owned headers.** An inbound `X-Profile` is refused (400). An inbound
  `traceparent` that is not W3C-valid is dropped, not forwarded (`valid_traceparent`).
- **Identity mapping.** Only `X-User-Email` is read (`job_env.IDENTITY_HEADER_ENV`). Any other
  inbound header does not reach the gateway.
- **Receipt size.** Do not cap it and do not parse it. It is the gateway's contract with the
  scoreboard (C3).
- **Duplicate calls.** The freeze is idempotent at the gateway (CV-D3). The engine keeps no
  state, so two engine replicas behave the same.
- **Timeout order.** Engine 55 s < SDK 60 s. Do not change `_UPSTREAM_TIMEOUT_S`.
- **Mount table.** `/v1/cache-versions` is an engine route, so `engine_route_paths(app)`
  (`world/serving.py:67`) includes it, and a declared mount cannot shadow it. No change there.
- **Local mode route order.** `local._install_local_node` asserts that the node route is last.
  `create_app` registers `_ROUTERS` first, so the new route is before it. Do not register the
  route anywhere else.

## 9. What not to do

- Do not retry in the engine (C2b).
- Do not decode, verify, or log the receipt. Do not import `jwt` or `cryptography`.
- Do not import anything from `apps/aigateway`, `apps/scoreboard`, or `packages/screamingface`.
- Do not import `screamingface_engine.runner`, `worker` or `world` from the new package (the
  layering gate forbids control plane → run mode).
- Do not forward `X-Profile` (OME-1381) or any credential.
- Do not edit an existing test or `tests/unit/_fakes.py` (append-only gate).
- Do not add a database, a migration, a Prometheus metric, or a Helm value.
- Do not echo an upstream error `message` or body into the engine answer or the log.

## 10. Gates and verification

Run from `apps/screamingface-engine/` in the unit's worktree:

```bash
uv run ruff check
uv run ruff format --check
uv run pyright
python3 ../../.claude/scripts/check_layering.py
uv run pytest tests/integration/test_cache_versions_proxy.py tests/unit/test_cache_versions_aigateway.py tests/unit/test_rest_cache_versions.py -q
uv run pytest tests/unit/test_connections_aigateway.py tests/unit/test_selector_connections.py tests/unit/test_rest_connections.py tests/unit/test_selector_openapi.py -q
uv run pytest --cov=screamingface_engine --cov=url4.streaming --cov-fail-under=80 -q
```

Then, from the repo root of the unit worktree:
`python3 .claude/scripts/run_gates.py screamingface-engine --base e14-reproducible-submission-spec`
(D1: the base is the e14 branch, so the check sees only this unit's change; the default
`--base HEAD` sees no change after a commit, so the append-only check would pass in silence).

**Done means all of these are true:**

1. SC-21a to SC-21m are green, and each one was seen RED for its stated reason first.
2. The existing connection and selector tests are green without an edit.
3. `check_layering.py` prints `LAYERING OK`.
4. `run_gates.py screamingface-engine` passes, including the append-only check and the 80 %
   coverage floor.
5. `grep -rn "import jwt\|from jwt" src/screamingface_engine/cache_versions src/screamingface_engine/rest/cache_versions.py`
   finds nothing.
6. `git diff e14-reproducible-submission-spec...HEAD --stat` shows only the files in §4.
7. Conventional commits on `unit/ENG-freeze`, no `Co-Authored-By`. No PR and no Linear issue
   (D1). The integrator merges the branch after wave 2.

## 11. Open decisions

None is open. The items below are closed:

1. **Problem `code` names — Decided: D7 (X-8).** `invalid_freeze_request` (422) and
   `cache_versions_unconfigured` (503), in the engine problem shape with a top-level `code`.
2. **401 and 403 pass-through — Decided: D7 (X-8).** The engine passes the gateway's 401 and 403
   through with no `code`.
3. **Layering script edit — Decided: D7 (X-18).** Add `"cache_versions"` to `CONTROL_PLANE` in
   `.claude/scripts/check_layering.py`. No other E14 unit edits that script (URL4-fp and
   SB-registry enforce C11 with unit tests), so there is no merge order to keep.
4. **Identity — Decided: D5.** Production relies on the Cloudflare identity headers; the gateway
   already runs `cloudflare_headers`. The engine forwards `X-User-Email` only.
