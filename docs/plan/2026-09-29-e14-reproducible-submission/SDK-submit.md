# Plan — SDK-submit: freeze the cache version, then submit with the receipt (E14, OME-1307)

Status: draft for approval. Spec: `docs/spec/2026-09-29-e14-reproducible-submission/`
(`prd/submit-and-cluster.md` SC-H1, SC-E1, SC-E2, SC-E5, SC-D6, §7 SC-18 to SC-20;
`contracts.md` C2a, C4). Language: ASD-STE100. Stack: `screamingface`
(`packages/screamingface`). Skill: `sdlc-python`. Wave: 3. Size: 2 d.

Delivery (D1): this unit lands on the one branch `e14-reproducible-submission-spec`. There is
no unit PR, no Linear sub-issue and no unit CI merge gate. Build it in a temporary worktree on
the branch `unit/SDK-submit`, made from the e14 branch HEAD after wave 2 is integrated
(`git checkout -B unit/SDK-submit e14-reproducible-submission-spec`). After wave 3, the
integrator merges `unit/SDK-submit` into the e14 branch and runs the gates. Plan: this file
(`docs/plan/2026-09-29-e14-reproducible-submission/SDK-submit.md`). Ledger:
`docs/work/2026-09-29-e14-sdk-submit.md` (start it before RED).

## 1. Scope

### 1.1 Test ids this unit owns

| Id | PRD name | What this unit proves |
|---|---|---|
| SC-18 | `sdk_submit_freezes_then_submits_with_receipt` | `submit` calls the engine `POST /v1/cache-versions {"trace_id": T}` first, then `POST /v1/scores` with `cache_version_receipt` (plus `revision_of` and `paper_url` when given), decodes the C4 response (`reported_result`, `reported_results_count`, `notices`), and follows the C2a and C4 policies (timeouts, retries). |
| SC-19 | `sdk_freeze_failure_submits_without_version_and_warns` | table: timeout, 404, 413, 5xx, no trace, bad freeze body → the submit still happens, with no receipt, and the returned score carries `cache_version_warning == "cache_version_unavailable: <reason>"`, and a log line. |
| SC-20 | `sdk_keeps_receipt_for_resubmit_after_name_error` | after a `409 system_name_taken`, a second `submit` of the same result sends the same receipt and calls the engine no second time. |

### 1.2 Out of scope

- SC-1 to SC-17, SC-22 (scoreboard, portal), SC-21 (engine route, ENG-freeze), SC-23 (E2E).
- Receipt verification. The SDK never decodes or verifies the receipt JWS. It is an opaque
  string from the engine to the scoreboard.
- The `replay` block of C4 (SDK-replay).
- An SDK method for `GET /v1/scores/{id}/results` (no PRD names one).
- A freeze after the submit ("Attaching a cache version after the submit" is out of scope,
  `prd/submit-and-cluster.md` §5).

## 2. Depends on

- Code dependency: **SDK-meta** (wave 2). This unit appends fields after the SDK-meta fields on
  `LeaderboardScore`, and reuses its `timeout`, `transport_retries` and per-operation
  `_status_code` helpers. SDK-meta is on the e14 branch HEAD when this unit starts (D2).
- Wave (D2): 3, with SB-submit, GW-replay and ENG-replay.
- Board and engine compatibility (not a build block; the tests use fakes, D7 X-20):
  **ENG-freeze** (the engine route C2a, wave 2) and **SB-submit** (wave 3: the board must
  accept `cache_version_receipt`, `trace_id` and `revision_of`, because `ScoreSubmission` is
  `extra="forbid"`, `apps/scoreboard/src/scoreboard/scores/schemas.py:369`). A missing engine
  route gives `404`, and the SDK then submits with no version (SC-E1). With D1, all units land
  on one branch and ship together, so no release order is left to own.
- Contracts: implements the client side of **C2a** (freeze) and **C4** (submit + receipt).
  Consumes **C3** only as an opaque string. Coded errors: the scoreboard uses
  `{"detail": {"code", "message", ...}}`; the engine uses its problem shape with a top-level
  `code` (D7 X-8). §4.2 reads both.

### 2.1 Integration notes

- Same-wave shared files: none. SB-submit, GW-replay and ENG-replay change no file under
  `packages/screamingface/`.
- The SB-submit payload keys (`cache_version_receipt`, `trace_id`, `revision_of`, `paper_url`)
  and this unit must agree. Before GREEN of row 1, read the SB-submit plan §4.1
  `ScoreSubmission` fields and write the key names in the ledger. If they differ from §4.4,
  **STOP** and ask.
- Later-wave files that build on this unit: SDK-replay (wave 4) changes the same
  `_scoreboard/leaderboards.py` (`_submission`), `_core/ports.py`, `client.py`, `leaderboard.py`,
  `__init__.py`, `CHANGELOG.md`, `README.md` and `public_surface_snapshot.json`. It starts from
  the e14 HEAD after this unit is merged. Keep each new block additive (new functions, new
  fields last), so the SDK-replay change applies with no rework.

## 3. Files

| Path | Change | Exemplar to imitate |
|---|---|---|
| `packages/screamingface/src/screamingface/_core/ports.py` | change: the freeze port (two Protocols) and its two value types | `SyncRunTransport` / `AsyncRunTransport`, `_core/ports.py:99-124`; `_ResultArtifact`, `:20-31` |
| `packages/screamingface/src/screamingface/_engine/cache_versions.py` | create: the engine adapter of the freeze port (sync + async) | `_engine/connections.py:1-80` (adapter on an injected request callable, typed failures) |
| `packages/screamingface/src/screamingface/client.py` | change: `_http_request` gets `timeout`; build the adapter and inject it into `Leaderboards` (both twins) | `client.py:95-102`, `:342-352` |
| `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py` | change: freeze-then-submit, receipt cache, submit retries, `revision_of`, C4 decode | `submit`, `:90-112`; `_decode_ranking_notice`, `:402-419` |
| `packages/screamingface/src/screamingface/leaderboard.py` | change: three new public value types and four new `LeaderboardScore` fields | `LeaderboardRankingNotice`, `leaderboard.py:88-115` |
| `packages/screamingface/src/screamingface/leaderboards.py` | change: facade `submit(..., revision_of=None)` | `leaderboards.py:25-32` |
| `packages/screamingface/src/screamingface/__init__.py` | change: export the three new types | `LeaderboardRankingNotice` export, `__init__.py:35`, `:96` |
| `packages/screamingface/tests/test_submit_cache_version.py` | create | two `httpx.MockTransport` handlers on one client: `http_transport=` (engine) as in `tests/test_answer_seed_report.py:140-146`, `scoreboard_transport=` as in `tests/test_leaderboards.py:180-192`; candidate builder `tests/test_leaderboards.py:118-178` (add `trace_id=`) |
| `packages/screamingface/tests/public_surface_snapshot.json` | regenerate | `tests/test_public_surface.py:31` |
| `packages/screamingface/CHANGELOG.md`, `README.md` | change | existing entries |

## 4. Signatures and data shapes

### 4.1 The freeze port (`_core/ports.py`)

```python
@dataclass(frozen=True, slots=True)
class _FrozenCacheVersion:
    """A version the gateway froze for one trace (contracts.md C2a)."""
    receipt: str                     # opaque JWS; never decoded by the SDK
    cache_version_id: UUID
    entry_count: int                 # >= 0
    call_count: int                  # >= 0
    missing_count: int               # >= 0
    coverage_status: Literal["complete", "partial"]
    archive_sha256: str              # 64 lowercase hex

@dataclass(frozen=True, slots=True)
class _FreezeUnavailable:
    """Why no version rides this submit (prd/submit-and-cluster.md SC-E1)."""
    reason: str                      # a token that matches ^[a-z0-9_]{1,64}$

type _FreezeOutcome = _FrozenCacheVersion | _FreezeUnavailable

class SyncCacheVersionFreezer(Protocol):
    def freeze(self, trace_id: str) -> _FreezeOutcome: ...

class AsyncCacheVersionFreezer(Protocol):
    async def freeze(self, trace_id: str) -> _FreezeOutcome: ...
```

Hexagonal: the core (`_core/ports.py`) owns the port. `_engine/cache_versions.py` is the
adapter. `_scoreboard/leaderboards.py` uses only the port type. It never imports
`_engine/cache_versions.py`. `client.py` is the composition root that joins them.

### 4.2 The adapter (`_engine/cache_versions.py`)

```python
_PATH = "/v1/cache-versions"
_TIMEOUT_S = 60.0                               # C2a
_RETRY_STATUS = frozenset({502, 503, 504})      # C2a
_ATTEMPTS = 2                                   # C2a: one retry
_REASON = re.compile(r"^[a-z0-9_]{1,64}$")

def _jitter() -> float:
    return random.uniform(1.0, 3.0)             # C2a: 1-3 s

class EngineCacheVersions:
    def __init__(self, request: Callable[..., httpx.Response], *,
                 sleep: Callable[[float], None] = time.sleep,
                 jitter: Callable[[], float] = _jitter) -> None: ...
    def freeze(self, trace_id: str) -> _FreezeOutcome: ...

class AsyncEngineCacheVersions:
    def __init__(self, request: Callable[..., Awaitable[httpx.Response]], *,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 jitter: Callable[[], float] = _jitter) -> None: ...
    async def freeze(self, trace_id: str) -> _FreezeOutcome: ...
```

`freeze` never raises for a network or HTTP failure. Rules, per attempt:

| Result of the attempt | Outcome | Retry? |
|---|---|---|
| `httpx.TimeoutException` | reason `timeout` | yes |
| other `httpx.TransportError` | reason `unreachable` | yes |
| status in `_RETRY_STATUS` | reason `http_<status>` | yes |
| status 200 or 201 | `_decode_freeze(body)` | no |
| other status | `_error_reason(response)` | no |

Between attempts: `sleep(jitter())`. After the last attempt, return the last reason.
Call shape: `request("POST", _PATH, json={"trace_id": trace_id}, timeout=_TIMEOUT_S)`.

`_error_reason(response)`: read JSON; take the first non-blank string of `body["code"]` (the
engine problem shape) or `body["detail"]["code"]` (the gateway body that the engine passes
through), per D7 X-8. Use it only when it matches `_REASON`. Else `http_<status>`.
WHY the regex: the reason goes into a log line and a user-visible warning, so it must never
carry untrusted text.

`_decode_freeze(body)`: the body must be a JSON object with all seven C2a keys and the types in
§4.1 (`bool` is not an `int`; the id parses as `UUID`; the digest matches `^[0-9a-f]{64}$`;
`receipt` is non-blank text). Any failure → `_FreezeUnavailable("invalid_response")`.

### 4.3 Client wiring (`client.py`, both twins)

- `_http_request(self, method, path, *, json=None, timeout: float | None = None)`: pass
  `**({"timeout": timeout} if timeout is not None else {})`. Keep `extensions={_REPLAY_SAFE: True}`
  (the freeze is idempotent, CV-D3, so a re-send after an Access login is safe).
- In `__init__`:
  ```python
  from screamingface._engine.cache_versions import EngineCacheVersions
  self.leaderboards = Leaderboards(self._scoreboard_request, self._scoreboard_url,
                                   freezer=EngineCacheVersions(self._http_request))
  ```
  Use `AsyncEngineCacheVersions` in `AsyncClient`.

### 4.4 `Leaderboards` (sync; the async twin is the same with `await`)

```python
def __init__(self, request, scoreboard_url, freezer: SyncCacheVersionFreezer | None = None, *,
             sleep: Callable[[float], None] = time.sleep) -> None

def submit(self, candidate_result: CandidateResult, *,
           authors: Sequence[str] | None = None,
           paper_url: str | None = None,
           revision_of: str | None = None) -> LeaderboardScore
```

`submit` steps, in this order:

1. `payload = _submission(candidate_result, authors=authors, paper_url=paper_url,
   revision_of=revision_of)`. All input checks run here, before any HTTP call. `revision_of`:
   `None` → no key; non-blank `str` → the stripped text; blank → `ValueError("revision_of must
   be non-blank text or None")`; other type → `TypeError`. The SDK does not check the name
   grammar (the registry does, SR-E2).
2. `notebook_notice = prepare_submission_notice(candidate_result)` (unchanged position).
3. `outcome = self._cache_version(candidate_result)`:
   - `trace_id is None` → `_FreezeUnavailable("no_trace")` (SC-D6). No engine call.
   - `self._freezer is None` → `_FreezeUnavailable("freeze_unconfigured")`. No engine call.
   - key `(run_id, trace_id)` is in `self._receipts` → the cached `_FrozenCacheVersion`
     (SC-20). No engine call.
   - else `self._freezer.freeze(trace_id)`. When the result is a `_FrozenCacheVersion`, store it
     in `self._receipts`.
   `self._receipts` is an `OrderedDict` bounded to 32 entries (drop the oldest). WHY bounded:
   a long notebook session submits many runs; the cache must not grow without end. WHY on the
   `Leaderboards` object and not on `CandidateResult`: `CandidateResult` is a frozen value whose
   fields are its export (`report.py:317-358`); a receipt is transport state. The freeze is
   idempotent (CV-D3), so a new client that lost the cache gets the same receipt back.
4. `_FrozenCacheVersion` → `payload["cache_version_receipt"] = outcome.receipt` and
   `payload["trace_id"] = trace_id` (cross-plan fix: SB-submit adds the optional `ScoreSubmission.trace_id`,
   pattern `^[0-9a-f]{32}$`, and refuses a receipt whose `tid` differs with `403 cache_version_not_yours`,
   SB-submit §4.1 and G1). Send `trace_id` ONLY together with a receipt: `ScoreSubmission` is
   `extra="forbid"`, so an old board must not get a new key on a plain submit.
   `_FreezeUnavailable` → `warning = f"cache_version_unavailable: {outcome.reason}"` and
   `_logger.warning("%s (run_id=%s)", warning, candidate_result.run_id)`. Add
   `import logging` and `_logger = logging.getLogger(__name__)` at the top of
   `_scoreboard/leaderboards.py` (the same form as `_engine/transport.py:94`). Log no trace id, no
   receipt, no author.
5. Send `POST /v1/scores` with `headers={"Idempotency-Key": run_id}`, `replay_safe=True`,
   `timeout=30.0`, and the C4 retry: up to **2 re-sends** after
   `LeaderboardError` whose `code == "scoreboard_unreachable"` or whose `status >= 500`. Wait
   `sleep(0.5 * 2 ** (n - 1) * (1 + 0.25 * random.random()))` before re-send `n` (0.5 s, 1 s).
   Never re-send after a 4xx (SC-E2: a `422 invalid_cache_version_receipt` raises at once, and
   the SDK does not retry it). Put this loop in one private helper per twin
   (`_submit_with_retries` / `_submit_with_retries_async`) around `_sync_json` / `_async_json`.
   Do **not** pass the SDK-meta `transport_retries` for this call: it has no backoff, and C4
   asks for backoff. The random factor comes from `random.random()` (module `random`), so the
   tests assert a range, not an exact value.
6. `score = _decode_score(...)`, then `dataclasses.replace(score, cache_version_warning=warning)`
   when there is a warning.
7. `display_submission_notice(notebook_notice)`; return `score`.

A `LeaderboardError` from step 5 propagates as today. The receipt stays in `self._receipts`, so
a resubmit with a fixed name (SC-E5) needs no new freeze.

The C4 error codes pass through with the SDK-meta rule (`detail.code` first). For the submit
operation, keep today's status map (`_scoreboard/leaderboards.py:307-316`) as the fallback.

`permanent` for a coded error: today a submit `409` is **not** permanent and gets the hint
"Retry the submission." (`_scoreboard/leaderboards.py:276-291`), because the board sends `409`
for a transient race (`apps/scoreboard/src/scoreboard/routes/scores.py:250-262`). A `409` whose
code comes from `detail.code` (`system_name_taken`, `cache_version_already_bound`) is a fixed
fact, so for it use `permanent = True` and no hint. A `409` with no `detail.code` keeps today's
rule and hint. Change only `_response_json` for this; the status map stays.

### 4.5 New public value types (`leaderboard.py`)

```python
@dataclass(frozen=True, slots=True)
class LeaderboardCacheVersion:
    id: UUID
    sha256: str                                   # 64 lowercase hex
    entry_count: int                              # >= 0
    call_count: int                               # >= 0
    coverage_status: Literal["complete", "partial"]

@dataclass(frozen=True, slots=True)
class LeaderboardReportedResult:
    id: UUID
    is_original: bool
    reporter: str | None
    cache_version: LeaderboardCacheVersion | None
    publication_state: str | None                 # "private" | "requested" | "published" | "failed" | "withdrawn" | None

@dataclass(frozen=True, slots=True)
class LeaderboardNotice:
    code: str                                     # e.g. "clustered_under", "system_already_named"
    details: Mapping[str, object]                 # every other key of the notice, frozen
```

`publication_state`: accept the five states of `erd.md` §2.6 and `None`; any other value →
`invalid_leaderboard`. `LeaderboardNotice.code`: any non-blank text (notices are information;
an unknown code must not break a submit that the board already stored). `details`: use
`freeze_mapping` (the helper `LeaderboardScore` already uses for `metadata`).

Append to `LeaderboardScore`, after the SDK-meta fields:

```python
reported_result: LeaderboardReportedResult | None = None
reported_results_count: int | None = None           # >= 1 when present
notices: tuple[LeaderboardNotice, ...] = ()
# Local, never from the wire. compare=False: two reads of one stored score stay equal.
cache_version_warning: str | None = field(default=None, compare=False)
```

`_decode_score`: decode `reported_result` (absent or `null` → `None`), `reported_results_count`
(`_optional_integer`), `notices` (absent → `()`; else an array of objects with a `code`).
Absent keys give the defaults, so `get_score` on a board before E14 still works.

### 4.6 Ed25519 JWS

The SDK does not sign or verify. The receipt is signed by the gateway (GW-freeze, PyJWT behind
a gateway port) and verified by the scoreboard (SB-submit, PyJWT behind a scoreboard port).
The SDK adds no `jwt` or `cryptography` import.

## 5. Migrations

None.

## 6. TDD order (RED first, risk order)

Step 0: add the port types, the adapter with a `freeze` that returns
`_FreezeUnavailable("not_implemented")`, the `freezer=` parameter, and the new
`LeaderboardScore` fields with defaults. Then each RED fails on an assertion.

All tests are in `packages/screamingface/tests/test_submit_cache_version.py`. Sync and async
for each transport test. Inject `sleep=` fakes that record the waits (no real sleep).

How to inject them: `Client.__init__` builds `EngineCacheVersions(self._http_request)` with the
real `time.sleep` and `_jitter` (the defaults are bound when the function is defined, so a
`monkeypatch` of the module does not reach them). So each test builds the client with a local
helper, and then replaces the adapter object:

```python
def _client(engine, scoreboard, waits: list[float]) -> sf.Client:
    client = sf.Client(engine_url="https://engine.example", scoreboard_url=SCOREBOARD_URL,
                       http_transport=httpx.MockTransport(engine),
                       scoreboard_transport=httpx.MockTransport(scoreboard))
    client.leaderboards = Leaderboards(
        client._scoreboard_request, client._scoreboard_url,
        freezer=EngineCacheVersions(client._http_request, sleep=waits.append, jitter=lambda: 2.0),
        sleep=waits.append)
    return client
```

The async helper is the same with `sf.AsyncClient`, `AsyncLeaderboards`,
`AsyncEngineCacheVersions`, and `async def _sleep(s): waits.append(s)`. Rows 1, 6 and 11 use
the plain `sf.Client` (no retry happens there), so they also prove the real wiring.
Use `trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"` and a UUID `cache_version_id`.

| Order | Test name | RED reason |
|---|---|---|
| 1 | `test_sc18_submit_freezes_then_submits_with_receipt` (+ `_async`) | one shared `calls` list across both handlers; assert `calls == ["engine POST /v1/cache-versions", "scoreboard POST /v1/scores"]`, engine body `{"trace_id": T}`, scoreboard body `cache_version_receipt == "<receipt>"` and `trace_id == T`, `Idempotency-Key == run_id`. Fails: the stub never calls the engine and sends no receipt. |
| 2 | `test_sc18_submit_decodes_reported_result_and_notices` | response with the C4 block (`reported_result` with `is_original: false`, the cache version summary, `publication_state: "private"`, `reported_results_count: 2`, notice `clustered_under` with `score_id`); the decoded fields are the defaults. |
| 3 | `test_sc19_freeze_failure_submits_without_version_and_warns` (params below) | the score must have `cache_version_warning == "cache_version_unavailable: <reason>"`, the POST must have no `cache_version_receipt` and no `trace_id`, and `caplog` must hold the line. Fails: stub reason is `not_implemented`. |
| 4 | `test_sc20_resubmit_after_name_error_reuses_the_receipt` | first POST → `409 {"detail": {"code": "system_name_taken", "suggested_name": "x-2"}}` raises `LeaderboardError(code="system_name_taken")`; second `submit` → 201. Assert the engine saw **1** call, both POSTs carry the same receipt, and the first error has `permanent is True` (the coded-409 rule of §4.4). Fails: no cache, 2 engine calls. |
| 5 | `test_sc18_freeze_retries_once_on_502_503_504_and_connection_error` (params) | engine answers the failure once then 201; assert 2 engine calls, one recorded wait in `[1.0, 3.0]` (inject `jitter=lambda: 2.0`, assert `2.0`), and a receipt in the POST. |
| 6 | `test_sc18_freeze_uses_a_60_second_timeout` | `request.extensions["timeout"]["read"] == 60.0`. |
| 7 | `test_sc18_submit_retries_twice_on_5xx_or_connection_error_then_raises` | scoreboard answers `503` three times; assert 3 POSTs, waits `[0.5..0.625, 1.0..1.25]`, and `LeaderboardError(status=503)`. Then one case: 503 once, then 201 → success with 2 POSTs. |
| 8 | `test_sc18_submit_never_retries_a_4xx` (params: 409, 422) | assert 1 POST. (Passes after row 7 GREEN if row 7 is right; it guards SC-E2.) |
| 9 | `test_sc18_submit_sends_revision_of_only_when_given` | the POST has no `revision_of`. Second half (absent key when not given) passes and guards the old shape. |
| 10 | `test_sc18_invalid_revision_of_raises_before_any_call` (params: `""`, `"  "`, `5`) | no error, and the engine is called. |
| 11 | `test_sc18_facade_submit_passes_revision_of` | `sf.leaderboards.submit(..., revision_of=...)` is a `TypeError`. |

SC-19 params (engine behavior → reason): `httpx.ReadTimeout` both tries → `timeout`;
`httpx.ConnectError` both tries → `unreachable`; `404 {"code": "trace_not_captured"}` →
`trace_not_captured`; `413 {"detail": {"code": "cache_version_too_large"}}` →
`cache_version_too_large`; `503` both tries → `http_503`; `500` → `http_500` (no retry);
`201` with a body missing `receipt` → `invalid_response`; `404` with body
`{"code": "Bad Code!"}` → `http_404` (the regex rule); `trace_id=None` → `no_trace` with **no**
engine call.

CHAR guard (no edit): `tests/test_leaderboards.py:387-425` compares the whole
`LeaderboardScore` of a submit. Its candidate has no `trace_id`, so the freeze is skipped with
`no_trace`, and `cache_version_warning` is `compare=False`. The test must stay green unchanged.
Also run `tests/test_partial_submission_notice.py` and `tests/test_cache_saved_cost_submission.py`
unchanged.

## 7. Edge cases, what not to do, gates

Edge cases:
- The freeze runs **after** the input checks and **after** the partial-submission advisory, so
  `-W error` still aborts before any engine call, as today
  (`_scoreboard/submission_notice.py:18-40`).
- Do not use `warnings.warn` for `cache_version_unavailable`. WHY: the warning comes before the
  POST, and under `-W error` it would raise and stop a submit that SC-E1 says must go on. The
  PRD asks for "the local warning … and logs it": the field plus the log line give both.
- Worst-case time: 60 s + 3 s + 60 s for the freeze, then the submit. The two timeouts are per
  request.
- A receipt for another caller or another trace gives `403 cache_version_not_yours` (SC-E3).
  The SDK raises it and keeps the receipt cached. That is correct: the same run and trace give
  the same receipt again.
- `run_id` alone is not the cache key: a report decoded twice can carry the same `run_id` with
  a different `trace_id` only by a bug, and then the key `(run_id, trace_id)` keeps them apart.

What not to do:
- Do not decode, verify or log the receipt.
- Do not send `cache_version_id` or any client-made version field. The receipt is the only
  way a version enters the scoreboard (`prd/submit-and-cluster.md` §4 Security).
- Do not import `jwt`, `cryptography`, or anything from `apps/`.
- `_scoreboard/leaderboards.py` must not import `_engine/cache_versions.py` (port only).
- Do not change a prior test. If one must change, stop and ask.

Gates:

```bash
uv run .claude/scripts/run_gates.py screamingface --base e14-reproducible-submission-spec
```

WHY this `--base`: the unit branch starts at the e14 branch HEAD (D1).

## 8. Verification

```bash
cd packages/screamingface
uv run pytest tests/test_submit_cache_version.py -q
uv run pytest tests/test_leaderboards.py tests/test_partial_submission_notice.py \
  tests/test_cache_saved_cost_submission.py tests/test_public_surface.py -q
cd ../.. && uv run .claude/scripts/run_gates.py screamingface --base e14-reproducible-submission-spec
```

Done when all `test_sc18_*`, `test_sc19_*`, `test_sc20_*` are green (sync and async), the three
prior files are green with no edit, the snapshot shows only the planned surface change, the
CHANGELOG and README have the entry, and the gates are green. Conventional commits on
`unit/SDK-submit`, no `Co-Authored-By`. Do not open a PR. Tell the integrator that the unit
branch is ready (D1).

## 9. Open decisions

None open. The earlier items are closed:

- **Receipt cache location (deviation from the PRD GREEN note of SC-20).** Decided (default):
  `CandidateResult` is `@dataclass(frozen=True, slots=True, init=False)`
  (`packages/screamingface/src/screamingface/report.py:183-184`), so no private attribute can
  be added to it, and a new public field would change its export. The receipt cache lives on
  the `Leaderboards` object (§4.4 step 3). The observable SC-20 behavior is the same.
- **respx.** Decided: D7 (X-20). The tests use `httpx.MockTransport`
  (`tests/test_leaderboards.py:180-192`). This unit adds no dependency.
- **Freeze error body.** Decided: D7 (X-8). The engine sends a top-level `code`; a gateway body
  that the engine passes through has `detail.code`. `_error_reason` accepts both (§4.2).
- **`503 capture_disabled` is in the retry set.** Decided (default): C2a retries every 503
  once. A kill-switch 503 costs 1–3 s more. The plan follows C2a as written.
- **`reason` vocabulary.** Decided (default): `no_trace`, `freeze_unconfigured`, `timeout`,
  `unreachable`, `invalid_response`, `http_<status>`, or the server code (when it matches
  `^[a-z0-9_]{1,64}$`).
- **Release order.** Decided: D1. SB-submit and this unit land on one branch and ship together.

Not owned by this unit (for reference only):

- **A5 and SR-5.** The SDK already imports `url4`
  (`packages/screamingface/src/screamingface/url4.py:10`) and vendors it into the wheel
  (`packages/screamingface/scripts/runtime_build_hook.py:32-40`). The SDK sends no fingerprint
  (the scoreboard computes it, R2), so the SR-5 parity test lives in `packages/url4/tests` plus
  a scoreboard test that reads the same fixture, not in the SDK (index X-9).
