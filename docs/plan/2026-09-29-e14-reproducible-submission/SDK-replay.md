# Plan — SDK-replay: `evaluate(replay=...)`, local signing keys, `publish_cache_version` (E14, OME-1307)

Status: draft for approval. Spec: `docs/spec/2026-09-29-e14-reproducible-submission/`
(`prd/replay-pinned-run.md` RP-H1, RP-H2, RP-E1, RP-E5, RP-E7, RP-E8, RP-D2, RP-D8, §7 RP-16 to
RP-20; `prd/publish-and-takedown.md` PB-H1, §7 PB-21; `contracts.md` C1, C4 `replay`, C6, C10).
Language: ASD-STE100. Stack: `screamingface` (`packages/screamingface`). Skill: `sdlc-python`.
Wave: 4. Size: 3–4 d (the largest SDK unit; see OD-7).

Delivery (D1): this unit lands on the one branch `e14-reproducible-submission-spec`. There is
no unit PR, no Linear sub-issue and no unit CI merge gate. Build it in a temporary worktree on
the branch `unit/SDK-replay`, made from the e14 branch HEAD after wave 3 is integrated
(`git checkout -B unit/SDK-replay e14-reproducible-submission-spec`). After wave 4, the
integrator merges `unit/SDK-replay` into the e14 branch and runs the gates. Plan: this file
(`docs/plan/2026-09-29-e14-reproducible-submission/SDK-replay.md`). Ledger:
`docs/work/2026-09-29-e14-sdk-replay.md` (start it before RED).

The wire names that the tests use are decided (D7): the grant header rides the start request
(X-5), the counter names are the X-7 frame contract, and the key env names and forms are X-4.
There is no gate before RED.

## 1. Scope

### 1.1 Test ids this unit owns

| Id | PRD name | What this unit proves |
|---|---|---|
| RP-16 | `sdk_evaluate_replay_requests_grant_then_runs` | `evaluate(..., replay=pin)` (sync + async) gets a grant from `POST /v1/replay-grants` **before** any run, carries it opaquely to the engine start request as `X-SF-Cache-Replay`, and puts a `replay` block in the report (from the engine's root replay counters). The C4 `replay` block rides a later `submit`. |
| RP-17 | `sdk_multi_candidate_with_pin_raises` | more than one Candidate plus a pin → `ValueError`, no HTTP call. |
| RP-18 | `sdk_malformed_pin_raises_before_calls` | the pin grammar check raises `ValueError`/`TypeError` before any call. |
| RP-19 | `sdk_scoreboard_down_raises_replay_unavailable` | unreachable, timeout (10 s) or 5xx → `ReplayUnavailable`, no retry, no run, no silent plain run. |
| RP-20 | `local_mode_grant_keys_wired_by_up` | `screamingface up` (`_runtime/server.run`) creates the local Ed25519 keypairs once, keeps them, and sets the signer and verifier environment of the local gateway and scoreboard before they start. |
| PB-21 | `sdk_publish_cache_version_and_portal_links` | `publish_cache_version(result_id)` (sync + async + facade) sends `POST /v1/results/{id}/publish`, decodes `202/200 {"state", "release_url"?}`, and types the C10 errors. |

### 1.2 Out of scope

- RP-1 to RP-15, RP-21 (scoreboard, gateway, engine, E2E). RP-22 is dropped (Q30).
- Decoding or verifying the grant. The SDK carries it as an opaque string (RP-D2).
- A grant refresh during a long run (Decided: D4, no refresh).
- SDK methods for the results list or the metadata history.
- The local bucket archive directory for C8, and the E14 feature flags of `screamingface up`
  (Decided: D6, the WIRING unit owns them).
- Portal UI work for PB (SB-publish).

## 2. Depends on

- Code dependency: **SDK-submit** (wave 3). This unit adds the `replay` block to `_submission`
  and reuses the coded-error and timeout helpers. SDK-submit (and SDK-meta) are on the e14
  branch HEAD when this unit starts (D2).
- Wave (D2): 4, with SB-grants and SB-publish.
- Service compatibility (not a build block; the tests use fakes, D7 X-20): **SB-grants** (C6
  route, wave 4), **ENG-replay** (wave 3: the engine reads the header on the start request and
  emits the counters), **SB-submit** (wave 3: the board accepts `replay`, `extra="forbid"`),
  **SB-publish** (C10, wave 4), **GW-freeze** and **SB-grants** (they read the local key env of
  RP-20). With D1, all units land on one branch and ship together. The local E2E (wave 5)
  needs all of them.
- Contracts: implements the client side of **C1** (the header rides `GET /?q=`, D7 X-5),
  **C6**, **C10** (publish), and the `replay` block of **C4**. Consumes the engine's counter
  frame (D7 X-7: `cache.version.hits`, `cache.version.misses`,
  `cache.version.repeated_key_collapses` on the closing cache-summary LogData frame of the root
  source; `repeated_key_collapses` is an upper bound).

### 2.1 Integration notes

- Same-wave shared files: none. SB-grants and SB-publish change no file under
  `packages/screamingface/`.
- The mirrored pin grammar (D7 X-21): SB-registry (wave 2) has the scoreboard copy (SR-20).
  Before GREEN of rows 9 and 10, read the scoreboard pin parser on the e14 HEAD and write its
  `file:line` in the ledger. The two parsers must accept and refuse the same forms. If they
  differ, **STOP** and ask. Do not import the scoreboard parser (C11).
- The key env names (D7 X-4): GW-freeze (wave 2), GW-replay (wave 3), SB-submit (wave 3) and
  SB-grants (wave 4, same wave as this unit) read them. Before GREEN of row 17, read the
  settings classes of GW-freeze, GW-replay and SB-submit on the e14 HEAD, and the SB-grants
  plan §4.1, and write each variable name with its `file:line` in the ledger. If a name or a
  form differs from §4.12, **STOP** and ask.
- Later-wave unit that builds on this unit: **WIRING** (wave 5, D6) owns the rest of the local
  runtime (`screamingface up`: the E14 feature flags, the archive dir) and the deploy charts.
  WIRING must extend `_runtime/signing_keys.py` and the `server.run()` call of §4.12. It must
  not add a second key file or a second key generator for the local runtime. RP-20 stays owned
  by this unit. Keep `apply_local_signing_environment(environment, data_dir)` as the one entry
  point, so WIRING and E2E can call it.
- E2E (wave 5) calls `screamingface._runtime.signing_keys.apply_local_signing_environment` to
  make the key env of its stack. Keep that name and signature stable.

## 3. Files

| Path | Change | Exemplar to imitate |
|---|---|---|
| `packages/screamingface/src/screamingface/_scoreboard/replay_pin.py` | create: the pin grammar | `_submission_authors`, `_scoreboard/leaderboards.py:523-538` (pure check, typed errors) |
| `packages/screamingface/src/screamingface/_core/ports.py` | change: `_ReplayBinding`, `_ReplayCounts`, `_RunOutcome.replay_counts` | `_ResultArtifact` and `_RunOutcome`, `_core/ports.py:20-68` |
| `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py` | change: `_replay_grant`, `publish_cache_version` (both twins), `replay` block in `_submission` | `get_score` twins, `:114-126`, `:190-202` |
| `packages/screamingface/src/screamingface/_evaluation/replay.py` | create: the pre-run replay steps (sync + async) | `_evaluation/url4.py:1-95` (a small sync/async twin module) |
| `packages/screamingface/src/screamingface/_evaluation/model.py` | change: `Candidate.replay`, `_with_replay`, copy `replay` in `_with_answer_seed` | `Candidate.answer_seed`, `model.py:51-54`; `_with_answer_seed`, `model.py:171-185` |
| `packages/screamingface/src/screamingface/_evaluation/runner.py` | change: `replay=` on `evaluate_sync` / `evaluate_async`; stamp after the seed | `_seeded_candidates`, `runner.py:87`, `:512-520` |
| `packages/screamingface/src/screamingface/_engine/transport.py` | change: grant header on the start request (both twins) | `_answer_seed_header`, `transport.py:1197-1206`; its call sites `:267`, `:663`, `:929`, `:959`, `:1153`, `:1183` |
| `packages/screamingface/src/screamingface/_engine/contract.py` | change: read the root replay counters from log frames | root client-version read, `contract.py:190-199`; outcome build, `:262-274` |
| `packages/screamingface/src/screamingface/_evaluation/results.py` | change: `replay=` into `CandidateResult` | `cache_saved_cost_usd=` line, `results.py:167-169` |
| `packages/screamingface/src/screamingface/report.py` | change: public `ReplayProvenance`; `CandidateResult.replay`; `to_dict` | `cache_saved_cost_usd` field, init arg and `to_dict` entry, `report.py:214`, `:237`, `:355-357` |
| `packages/screamingface/src/screamingface/leaderboard.py` | change: public `CacheVersionPublication` | `LeaderboardRankingNotice`, `leaderboard.py:88-115` |
| `packages/screamingface/src/screamingface/errors.py` | change: public `ReplayUnavailable(LeaderboardError)`, and add `"ReplayUnavailable"` to `errors.__all__` (`errors.py:233-241`) | `LeaderboardError`, `errors.py:152-178` |
| `packages/screamingface/src/screamingface/client.py` | change: `replay=` on `evaluate` (all overloads, both twins) | `answer_seed` threading, `client.py:205-257`, `:538-583` |
| `packages/screamingface/src/screamingface/_default_client.py` | change: `replay=` passthrough | `answer_seed` passthrough, `_default_client.py:96-158` |
| `packages/screamingface/src/screamingface/leaderboards.py` | change: facade `publish_cache_version` | `leaderboards.py:35-38` |
| `packages/screamingface/src/screamingface/__init__.py` | change: export `ReplayUnavailable`, `ReplayProvenance`, `CacheVersionPublication` | `__init__.py:20-26`, `:85-112` |
| `packages/screamingface/src/screamingface/_runtime/signing_keys.py` | create: local keypairs + env | `_write_json_atomic`, `_runtime/cli.py:762-775` (0600 atomic write); `enable_local_providers`, `_runtime/bootstrap.py:41-45` (env defaults) |
| `packages/screamingface/src/screamingface/_runtime/server.py` | change: call the key step in `run()` | `run()`, `_runtime/server.py:166-180` |
| `packages/screamingface/tests/test_replay_pinned_run.py` | create (RP-16 to RP-19) | `tests/test_answer_seed_report.py:46-71` (recording http for the start header), `:140-146` and `:227-263` (fake run transport that records the Candidate), `tests/test_leaderboards.py:180-192` (scoreboard MockTransport) |
| `packages/screamingface/tests/test_replay_contract_counters.py` | create (RP-16 decode part) | `tests/test_client_version_provenance.py` (root log attribute read) |
| `packages/screamingface/tests/test_runtime_signing_keys.py` | create (RP-20) | `tests/test_runtime_cli.py:135-145` (private file mode), `:25` (import `server`) |
| `packages/screamingface/tests/test_publish_cache_version.py` | create (PB-21) | `tests/test_leaderboards.py:180-192` |
| `packages/screamingface/tests/public_surface_snapshot.json` | regenerate | `tests/test_public_surface.py:31` |
| `packages/screamingface/CHANGELOG.md`, `README.md` | change | a "Rerun a submission" and a "Publish a cache version" example |

## 4. Signatures and data shapes

### 4.1 Pin grammar (`_scoreboard/replay_pin.py`)

```python
# INVARIANT: mirrors the system-name rule of erd.md §2.3.1 (lowercase, then this regex).
_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
_REVISION = re.compile(r"^r([1-9][0-9]*)$")

type _PinKind = Literal["result", "score", "name", "revision", "date"]

@dataclass(frozen=True, slots=True)
class _ReplayPin:
    text: str          # the stripped pin, sent unchanged to the scoreboard
    kind: _PinKind

def parse_replay_pin(value: object) -> _ReplayPin: ...
```

Rules (RP-E8, the pin forms of `prd/replay-pinned-run.md` §3.1):
1. Not a `str` → `TypeError("replay must be a pin string")`. Strip it. Empty → `ValueError`.
2. Prefix `result:` or `score:` → the rest must parse with `uuid.UUID(rest)` → kind
   `result`/`score`. Else `ValueError`.
3. Else split once on `@` (a name cannot hold `@`). The name part: `name.lower()` must match
   `_NAME`; else `ValueError`. No `@` → kind `name`.
4. Suffix matches `_REVISION` → kind `revision`.
5. Suffix has length 10 → `date.fromisoformat(suffix)` → kind `date`.
6. Else `datetime.fromisoformat(suffix.replace("Z", "+00:00"))`, and it must have a UTC offset
   (a time with no offset → `ValueError`; Decided: D7 X-21, the scoreboard rejects it too)
   → kind `date`.
7. Any other suffix → `ValueError`.

Every `ValueError` message is `f"invalid replay pin {value!r}: <why>"`.

### 4.2 Values carried with the run (`_core/ports.py`)

```python
@dataclass(frozen=True, slots=True)
class _ReplayBinding:
    """A grant the Scoreboard issued for one pinned run (contracts.md C6)."""
    grant: str = field(repr=False)       # opaque JWS, <= 2,048 UTF-8 bytes; never logged
    result_id: UUID
    score_id: UUID
    cache_version_id: UUID
    expires_at: datetime                 # aware
    pinned_baseline_result_id: UUID | None

@dataclass(frozen=True, slots=True)
class _ReplayCounts:
    hits: int
    misses: int
    repeated_key_collapses: int
```

`_RunOutcome` gets `replay_counts: _ReplayCounts | None = None` (append after `client_version`).
`pinned_baseline_result_id` is `result_id` when the pin kind is `date`, else `None` (OD-8,
decided default).

### 4.3 The grant request (`Leaderboards._replay_grant`, both twins)

```python
def _replay_grant(self, pin: _ReplayPin, benchmark_id: str) -> _ReplayBinding
```

- `POST /v1/replay-grants`, `json={"pin": pin.text, "benchmark_id": benchmark_id}`,
  `timeout=10.0` (C6), `replay_safe=True` (a grant has no side effect), **no** retry.
- How: call `_sync_json` / `_async_json` with `operation="request a replay grant from"`,
  `missing=None`, `timeout=10.0` and `transport_retries=0`. Catch the `LeaderboardError` it
  raises. When `exc.code == "scoreboard_unreachable"` or `(exc.status or 0) >= 500`, raise
  `ReplayUnavailable(...)` `from exc` (the rule below). Else re-raise it unchanged. Put the
  fallback map below in a module constant `_REPLAY_GRANT_CODES`, looked up by the SDK-meta
  per-operation `_status_code`.
- `httpx.TransportError` (timeout included) or status `>= 500` →
  `ReplayUnavailable("Could not get a replay grant from the Scoreboard", scoreboard_url=...,
  status=<status or None>, permanent=False)`. Chain the cause.
- Other non-2xx → `LeaderboardError` with `permanent=True` and the code from `detail.code`,
  else this fallback map: `404 → replay_pin_not_found`, `410 → cache_version_withdrawn`,
  `422 → invalid_replay_pin`, other → `scoreboard_contract_error`.
- `200` → decode: `grant` non-blank text with `len(grant.encode()) <= 2048`, else
  `LeaderboardError(code="invalid_replay_grant", permanent=True)` (C1: "the SDK raises before
  the run"). `result_id`, `score_id`, `cache_version_id` parse as `UUID`; `expires_at` through
  the existing `_timestamp` (aware). Other shape errors → `_invalid(...)`.

`ReplayUnavailable` (`errors.py`):

```python
class ReplayUnavailable(LeaderboardError):
    """The Scoreboard could not issue a replay grant; the run did not start."""
    _default_code: str = "replay_unavailable"
```

### 4.4 Pre-run steps (`_evaluation/replay.py`)

```python
def prepare_replay_sync(
    replay: object,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
    request_grant: Callable[[_ReplayPin, str], _ReplayBinding],
) -> _ReplayBinding:
    pin = parse_replay_pin(replay)                                   # RP-18
    values = _evaluation_inputs(candidates, benchmark, limit)        # same checks as a run
    if len(values) != 1:                                             # RP-17
        raise ValueError("a replay pin applies to one Candidate; pass exactly one Recipe")
    return request_grant(pin, benchmark)                             # RP-19 raises here

async def prepare_replay_async(..., request_grant: Callable[[_ReplayPin, str], Awaitable[_ReplayBinding]]) -> _ReplayBinding
```

Import `_evaluation_inputs` from `screamingface._evaluation.runner` (`runner.py:797-808`).

### 4.5 `evaluate(replay=...)`

- `Client.evaluate` / `AsyncClient.evaluate`: add `replay: str | None = None` as the last
  keyword to the implementation and to both overloads. The `candidates: str` overload uses
  `replay: None = None`.
- Order in the implementation: `_require_open()`; seed check (unchanged); if `candidates` is a
  `str` and `replay is not None` → `TypeError("replay requires Recipe candidates and
  benchmark=")` (OD-9, decided default); the existing `benchmark is None` check; then
  `binding = prepare_replay_sync(replay, candidates, benchmark, limit, self.leaderboards._replay_grant)`
  when `replay is not None`, else `None`; then `evaluate_sync(..., answer_seed=..., replay=binding)`.
- `_default_client.evaluate`: add `replay: str | None = None` to the three signatures and pass
  it in **both** branches (the Client raises for the `str` case). Keep the OME-1227 invariant
  comment true.
- `evaluate_sync` / `evaluate_async` (`runner.py`): `replay: _ReplayBinding | None = None`.
  After `selected_candidates = _seeded_candidates(...)`, add
  `selected_candidates = _bound_candidates(selected_candidates, replay)`.

### 4.6 The Candidate carries the binding (`_evaluation/model.py`)

```python
# FEATURE (OME-1307): the replay grant rides the Candidate the transport already receives,
# for the same reason as `answer_seed`: the run-transport protocol never widens.
replay: _ReplayBinding | None
```

- `_with_answer_seed`: add `"replay"` to the copied field list (`model.py:174-182`).
- New `_with_replay(candidate, binding) -> Candidate`, the same shape as `_with_answer_seed`,
  copying every field and `answer_seed`, then setting `replay`.
- Every other place that builds a `Candidate` must set `replay = None`. Find them with
  `rg -n 'object.__new__\(Candidate\)|"answer_seed"' src/screamingface`. Do not miss one:
  pyright does not see a missing `object.__setattr__`.

### 4.7 The start request carries the grant (`_engine/transport.py`)

```python
_REPLAY_GRANT_HEADER = "X-SF-Cache-Replay"

def _replay_grant_header(replay_grant: str | None) -> dict[str, str]:
    """INVARIANT: absent means byte-identical to a run with no replay (like X-Answer-Seed)."""
    return {} if replay_grant is None else {_REPLAY_GRANT_HEADER: replay_grant}
```

`_start_sync`, `_send_start_sync`, `_start_async`, `_send_start_async` get
`replay_grant: str | None = None` (keyword, default keeps the old call shape). The header goes
next to `**_answer_seed_header(answer_seed)`. The two `run` call sites pass
`replay_grant=None if candidate.replay is None else candidate.replay.grant`.
`_mint_sync` / `_mint_async` (`POST /token`) do **not** change (Decided: D7 X-5).

### 4.8 The engine's replay counters (`_engine/contract.py`)

In `_log`, for a frame whose `envelope["source"] == self._root_source`, read three
attributes (names per Decided: D7 X-7):

```python
_REPLAY_HITS = "cache.version.hits"
_REPLAY_MISSES = "cache.version.misses"
_REPLAY_COLLAPSES = "cache.version.repeated_key_collapses"
```

When all three are present, each an `int` (not `bool`) and `>= 0`, set
`self._replay_counts = _ReplayCounts(...)` (the last valid root frame wins). Else keep the
old value. Never raise: a telemetry defect must not end a paid run (the same rule as the
progress notice, `transport.py:832-847`). `_terminated` passes `replay_counts=self._replay_counts`
into `_RunOutcome`.

### 4.9 The report (`report.py`, public)

```python
@dataclass(frozen=True, slots=True)
class ReplayProvenance:
    """Which cache version a pinned run replayed, and how much of it matched."""
    result_id: UUID
    cache_version_id: UUID
    hits: int | None                     # None: the Engine reported no counters
    misses: int | None
    repeated_key_collapses: int | None
    pinned_baseline_result_id: UUID | None

    @property
    def coverage(self) -> Literal["complete", "partial", "unknown"]:
        # unknown when a count is None; complete when misses == 0; else partial (ans:Q13)

    def to_dict(self) -> dict[str, object]:
        # {"result_id": str, "cache_version_id": str, "hits", "misses",
        #  "repeated_key_collapses", "coverage", "pinned_baseline_result_id": str | None}
```

`CandidateResult.__init__` gets `replay: ReplayProvenance | None = None` (keyword, last). It
checks the type, stores it, and `to_dict` always emits `"replay"` (`None` or the block) — the
stable-key rule of `report.py:344-357`. `results.py` builds it from `candidate.replay` and
`outcome.replay_counts` (all counts `None` when `replay_counts is None`). Add
`ReplayProvenance` to `report.__all__` and to the top-level exports.

### 4.10 The C4 `replay` block (`_submission`)

When `candidate_result.replay is not None`:

```python
payload["replay"] = {
    "result_id": str(r.result_id), "cache_version_id": str(r.cache_version_id),
    "hits": r.hits, "misses": r.misses, "repeated_key_collapses": r.repeated_key_collapses,
    "pinned_baseline_result_id": None if r.pinned_baseline_result_id is None else str(...),
}
```

When any count is `None` → `ValueError("this replay run has no replay counters from the SF
Engine, so it cannot be submitted as a replay")` before any HTTP call (OD-10, decided
default). WHY: SC-D7 says
a replay must never show as an independent result, and C4 needs integer counts.

### 4.11 `publish_cache_version` (both twins + facade)

```python
def publish_cache_version(self, result_id: UUID | str) -> CacheVersionPublication

@dataclass(frozen=True, slots=True)
class CacheVersionPublication:            # leaderboard.py, public
    result_id: UUID
    state: Literal["requested", "published"]
    release_url: str | None = None
```

- `POST /v1/results/{result_id}/publish`, no body, `replay_safe=True` (idempotent, PB-D5),
  `operation="publish the cache version on"`,
  `missing=("unknown_result", f"Result {id!r} was not found")`.
- `202` or `200` → decode `state` (only the two values; other → `invalid_leaderboard`) and
  optional `release_url` (`_optional_text`).
- Errors: `detail.code` first; fallback `403 → not_result_owner`, `409 → not_publishable`,
  `503 → publish_unavailable`. For `409 not_publishable`, `details` keeps the `reason`
  (`private_board|not_redistributable|no_cache_version`). `permanent` keeps today's rule.
- `result_id` is checked like `_score_id` (UUID or UUID text) before any call.

### 4.12 Local signing keys (`_runtime/signing_keys.py`)

```python
KEY_FILENAME = "signing-keys.json"       # under RuntimeConfig.data_dir, mode 0600

@dataclass(frozen=True, slots=True)
class LocalKeyPair:
    kid: str                             # receipt: sha256(public raw).hexdigest()[:16] (the GW-freeze derived kid, OD-F2);
                                         # replay_grant: "local-" + sha256(public raw).hexdigest()[:16]
    private_key: str = field(repr=False) # base64 (standard, padded) of the 32-byte Ed25519 seed
    public_key: str                      # base64 of the 32-byte public key

@dataclass(frozen=True, slots=True)
class LocalSigningKeys:
    receipt: LocalKeyPair                # gateway signs, scoreboard verifies (C3)
    replay_grant: LocalKeyPair           # scoreboard signs, gateway verifies (C6)

def ensure_local_signing_keys(data_dir: Path) -> LocalSigningKeys
def apply_local_signing_environment(environment: MutableMapping[str, str], data_dir: Path) -> None
```

- Generate with `nacl.signing.SigningKey.generate()` (PyNaCl is a base dependency,
  `pyproject.toml` `pynacl>=1.5`, already used in `_access/contract.py:16`). Seed:
  `bytes(signing_key)`. Public: `bytes(signing_key.verify_key)`.
- The file: `{"version": 1, "receipt": {...}, "replay_grant": {...}}`, written atomically with
  mode 0600 (copy the `_runtime/cli.py:762-775` steps; do not import `cli` from here). A second
  call reads it and returns the same keys. A file that does not parse, or has the wrong shape →
  `RuntimeError(f"local signing keys at {path} are unreadable; move the file away to make new keys")`.
  The message never holds key text.
- Env groups (names and forms per Decided: D7 X-4: raw base64 keys, JSON `{kid: b64}` maps,
  receipt kid derived, grant kid from `SCOREBOARD_REPLAY_GRANT_SIGNING_KID`):

| Group | Variable | Value |
|---|---|---|
| receipt | `AIGATEWAY_RECEIPT_SIGNING_KEY` | `receipt.private_key` |
| receipt | `SCOREBOARD_RECEIPT_PUBLIC_KEYS` | `json.dumps({receipt.kid: receipt.public_key})` |
| replay_grant | `SCOREBOARD_REPLAY_GRANT_SIGNING_KEY` | `replay_grant.private_key` |
| replay_grant | `SCOREBOARD_REPLAY_GRANT_SIGNING_KID` | `replay_grant.kid` |
| replay_grant | `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS` | `json.dumps({replay_grant.kid: replay_grant.public_key})` |

  Per group: none set → set all of them (two for receipt, three for replay_grant); all set → change nothing (the operator wins); some set
  → `RuntimeError("set all of <names> or none of them")`. WHY per group and not per variable:
  a signer from one pair and a verifier from another fail every submit or replay, with no clue.
- Cross-plan fix: the gateway has NO `AIGATEWAY_RECEIPT_SIGNING_KID` variable. GW-freeze derives the receipt `kid` as `sha256(raw 32-byte public key).hexdigest()[:16]` (GW-freeze §4.4, OD-F2). So `receipt.kid` MUST be that exact value (no prefix), or the scoreboard map misses the kid and every receipt fails with 422. Test row 17 also asserts `receipt.kid == hashlib.sha256(base64.b64decode(receipt.public_key)).hexdigest()[:16]`.
- `server.run()`: call `apply_local_signing_environment(os.environ, config.data_dir)` right
  after `config.data_dir.mkdir(...)` (`_runtime/server.py:176`), before `_migrate` and
  `_build_apps`. The scoreboard child inherits `os.environ` (`subprocess.Popen` with no `env`,
  `_runtime/server.py:213-215`), so both services see the keys. Print nothing about the keys.

### 4.13 Ed25519 JWS in this unit

The SDK does not sign or verify a JWS. It only makes the local keypairs (PyNaCl) and hands
them to the services by environment. Signing and verifying stay in the services: the gateway
(GW-freeze signs receipts, GW-replay verifies grants) and the scoreboard (SB-submit verifies
receipts, SB-grants signs grants), each with PyJWT behind a service-local port. No shared JWS
package is planned (Decided: D7 X-3).

## 5. Migrations

None.

## 6. TDD order (RED first, risk order)

Step 0 (stubs, so each RED is an assertion): `parse_replay_pin` returns
`_ReplayPin(text=value, kind="name")` with no checks; `evaluate` accepts `replay=` and ignores
it; `_replay_grant` and `publish_cache_version` exist and raise `NotImplementedError`;
`ReplayProvenance`, `CandidateResult.replay` (always `None`), `Candidate.replay` (always `None`),
`_ReplayCounts`, `_RunOutcome.replay_counts`, `CacheVersionPublication`, `ReplayUnavailable`,
and `signing_keys.py` with functions that do nothing.

| Order | Test file :: name | RED reason |
|---|---|---|
| 1 | `test_replay_pinned_run.py::test_rp16_evaluate_replay_requests_grant_then_runs` (+ `_async`) | the scoreboard handler must see one `POST /v1/replay-grants` with `{"pin": "result:<X>", "benchmark_id": "draco"}` **before** the fake transport's `run`, and the recorded Candidate must have `replay.grant == GRANT`. Fails: `replay` is ignored, zero grant calls, `candidate.replay is None`. |
| 2 | `test_replay_pinned_run.py::test_rp16_start_request_carries_the_grant_only_when_bound` (+ async twin) | `_start_sync(http, token, url4, replay_grant=GRANT)` → `seen[0].headers["X-SF-Cache-Replay"] == GRANT`; with no grant the header is absent. Fails: no header. |
| 3 | `test_replay_contract_counters.py::test_rp16_root_replay_counters_reach_the_outcome` | a root log frame with the three attributes → `outcome.replay_counts == _ReplayCounts(412, 8, 0)`; a child-source frame is ignored; a `bool` or negative value leaves `None` and does not raise. Fails: always `None`. |
| 4 | `test_replay_pinned_run.py::test_rp16_report_carries_the_replay_block` | fake transport returns `replay_counts=_ReplayCounts(420, 0, 0)` → `result.replay.hits == 420`, `coverage == "complete"`, and `to_dict()["replay"]["result_id"] == str(X)`; with `(412, 8, 0)` → `"partial"`; no binding → `to_dict()["replay"] is None`. Fails: `replay` is `None`. |
| 5 | `test_replay_pinned_run.py::test_rp16_oversize_grant_is_refused_before_any_run` | a 2,049-byte grant → `LeaderboardError(code="invalid_replay_grant")`, and the transport `run` is never called. |
| 6 | `test_replay_pinned_run.py::test_rp16_grant_errors_are_typed_and_nothing_runs` (params: 404 `replay_pin_not_found`, 410 `cache_version_withdrawn`, 422 `invalid_replay_pin`, 422 with `detail.code == "replay_benchmark_mismatch"`) | `exc.code` and `permanent is True`; zero transport runs (the SDK half of RP-9). |
| 7 | `test_replay_pinned_run.py::test_rp16_grant_request_uses_a_10_second_timeout` | `request.extensions["timeout"]["read"] == 10.0`. |
| 8 | `test_replay_pinned_run.py::test_rp19_scoreboard_down_raises_replay_unavailable` (params: `httpx.ConnectError`, `httpx.ReadTimeout`, 500, 503; + async) | `pytest.raises(sf.ReplayUnavailable)`, `isinstance(exc, sf.LeaderboardError)`, `exc.retryable is True`, exactly **1** scoreboard request (no retry), zero runs. Fails: stub raises `NotImplementedError`. |
| 9 | `test_replay_pinned_run.py::test_rp18_malformed_pin_raises_before_any_call` (params: `""`, `"  "`, `5`, `"result:not-a-uuid"`, `"score:"`, `"Kevin Best"`, `"-bad"`, `"a" * 65`, `"kevins-best@r0"`, `"kevins-best@r-1"`, `"kevins-best@rx"`, `"kevins-best@2026-13-01"`, `"kevins-best@2026-09-01T10:00:00"`, `"kevins@best@r1"`) | expect `ValueError`/`TypeError` and zero HTTP calls on both transports. Fails: the stub accepts all. |
| 10 | `test_replay_pinned_run.py::test_rp18_valid_pin_forms_parse` (params: `result:<uuid>`, `score:<uuid>`, `kevins-best`, `Opus-5.5`, `kevins-best@r2`, `kevins-best@2026-09-01`, `kevins-best@2026-09-01T10:00:00+02:00`, `kevins-best@2026-09-01T10:00:00Z`) | assert `kind`; the stub gives `"name"` for all. |
| 11 | `test_replay_pinned_run.py::test_rp17_multi_candidate_with_pin_raises_before_any_call` (+ async) | two Recipes + `replay="kevins-best"` → `ValueError`, zero HTTP calls, zero runs. Fails: no check. |
| 12 | `test_replay_pinned_run.py::test_rp16_raw_url4_with_replay_raises_type_error` | `client.evaluate("<url4>", replay="result:<X>")` → `TypeError`. |
| 13 | `test_replay_pinned_run.py::test_rp16_facade_passes_replay` | `sf.evaluate(recipe, benchmark="draco", replay=...)` reaches the default client with `replay`. Fails: `TypeError` unexpected keyword. |
| 14 | `test_replay_pinned_run.py::test_rp16_submit_sends_the_replay_block` | submit a replay result → the POST body `replay` equals the §4.10 dict; a result with `hits=None` → `ValueError` and zero HTTP calls (no engine freeze, no scoreboard). |
| 15 | `test_runtime_signing_keys.py::test_rp20_first_start_creates_two_pairs_in_a_private_file` | file exists, `stat.S_IMODE(mode) == 0o600`, two distinct kids. Fails: the stub writes nothing. |
| 16 | `test_runtime_signing_keys.py::test_rp20_second_start_reuses_the_same_keys` | the two calls return equal `LocalSigningKeys`. |
| 17 | `test_runtime_signing_keys.py::test_rp20_environment_pairs_sign_and_verify` | sign `b"x"` with the seed from `AIGATEWAY_RECEIPT_SIGNING_KEY`; verify with `SCOREBOARD_RECEIPT_PUBLIC_KEYS[kid]` (PyNaCl `VerifyKey`); same for the grant group. Fails: no env set. |
| 18 | `test_runtime_signing_keys.py::test_rp20_operator_group_wins_and_a_partial_group_fails` | all three names of the grant group preset → unchanged; one of the three preset → `RuntimeError`; the same two cases for the two names of the receipt group. |
| 19 | `test_runtime_signing_keys.py::test_rp20_unreadable_key_file_fails_without_key_text` | write `"{"` to the file → `RuntimeError` whose text has the path and no base64 key. |
| 20 | `test_runtime_signing_keys.py::test_rp20_up_sets_the_keys_before_the_apps_are_built` | `monkeypatch.delenv` the five names of §4.12; patch `server.require_runtime_extra` (a fake with `describe()`), `server._migrate` (async no-op), and `server._build_apps` (copy `dict(os.environ)`, then raise a private `_Stop`); run `asyncio.run(server.run(RuntimeConfig(data_dir=tmp_path, runner_config=<a tmp url4.toml>)))` under `pytest.raises(_Stop)`. Assert the copy has all five names and `capsys` output has no private key. Fails: `run` does not call the key step. |
| 21 | `test_publish_cache_version.py::test_pb21_publish_sends_post_and_decodes_requested` (+ `_async`) | `POST /v1/results/<X>/publish` → `202 {"state": "requested"}` → `CacheVersionPublication(X, "requested", None)`. Fails: `NotImplementedError`. |
| 22 | `test_publish_cache_version.py::test_pb21_published_noop_returns_the_release_url` | `200 {"state": "published", "release_url": "https://github.com/ScreamingFace/screamingface-cache-versions/releases/tag/cv-<V>"}`. |
| 23 | `test_publish_cache_version.py::test_pb21_publish_errors_are_typed` (params: 403 `not_result_owner`, 404 `unknown_result`, 409 `not_publishable` with `reason`, 409 `withdrawn`, 503 `publish_unavailable`, 200 with `state: "private"` → `invalid_leaderboard`) | `exc.code`, and `exc.details["reason"]` for `not_publishable`. |
| 24 | `test_publish_cache_version.py::test_pb21_invalid_result_id_raises_before_any_call` and `::test_pb21_facade_passes_through` | no check; no facade. |
| 25 | `test_replay_pinned_run.py::test_rp16_grant_that_expires_mid_run_fails_the_run_once` | a copy of `_CandidateRecordingTransport` (`tests/test_answer_seed_report.py:227-236`; copy it, do not import it) whose `run` raises `sf.ExecutionError("replay grant expired", code="replay_grant_invalid", permanent=True)` (the RP-14 path of the engine for a grant whose `exp` passed mid-run). Assert `pytest.raises(sf.ExecutionError)`, the engine code reaches the caller (read how `runner.py` maps a one-Candidate run failure, write that `file:line` in the ledger, and assert that exact form: `exc.code`, or `exc.details["failed"]`), exactly **1** grant request, and exactly **1** transport `run`. Guard row (see the note below). |

GREEN after each row with the smallest change. REFACTOR on green only.

No test for "`POST /token` carries no grant": `_mint_sync` / `_mint_async`
(`_engine/transport.py:858-887`) take no grant argument, so a test of it proves nothing, and a
full `run` against the recording http cannot pass the mint (the fake answers `202` with no
token). D7 X-5 is held by §4.7 and by review.

Prior tests that must stay green with no edit: `tests/test_answer_seed_report.py` (the seed
path now also copies `replay`), `tests/test_report.py`, `tests/test_leaderboards.py`,
`tests/test_submit_cache_version.py`, `tests/test_runtime_cli.py`,
`tests/test_default_client_evaluate_passthrough.py`. **Stop and ask** if a prior test pins the
exact key set of `CandidateResult.to_dict()` or the exact header set of the start request:
the new `"replay"` key and header would then need an owner-approved test change (precedent:
`docs/plan/2026-09-28-sdk-run-isolation.md` unit 4, `--skip-append-only` only with approval).

Row 25 (Decided: D4) is a guard row. It can pass at once after row 1 GREEN. It pins that the SDK
never refreshes a grant and never runs the Candidate a second time.

## 7. Edge cases, what not to do, gates

Edge cases:
- The grant is fetched before the benchmark load, the model preflight and the mint. So a pin
  that does not resolve spends nothing (RP-E1, RP-9).
- `benchmark_id` sent to C6 is the `benchmark=` argument after `_evaluation_inputs` checks it.
- The start request is re-sent on a 503 (admission) or while the attach registers
  (`transport.py:906-965`). Each re-send carries the same grant. That is correct: the grant is
  valid for its whole life.
- A reconnect (resume) sends no start, so it sends no grant. The engine already holds it.
- A mid-run `403 replay_grant_invalid` arrives as an engine run failure (RP-14, ENG-replay).
  The SDK shows it as the engine's typed `ExecutionError`. It never re-runs without the grant.
- A grant can expire during a long run (Decided: D4). The grant `exp` is `iat + 43,200` s
  (12 h). The engine job deadline is 57,600 s, and a queued run can also wait before it starts,
  so a long pinned run can pass `exp`. The gateway then refuses the next replay call, and the
  engine fails the run with the typed error (the RP-14 path). The SDK raises that error as an
  `ExecutionError` (row 25). It does not refresh the grant, it does not start a second run, and
  it does not fall back to a plain run. Assumption A3 is "[checked] false, accepted". Put this
  limit in the README "Rerun a submission" example: "A pinned run must finish within 12 hours
  of the grant."
- Identity (Decided: D5): in production the scoreboard and the gateway run
  `cloudflare_headers`. The grant `sub` is the verified `X-User-Email` of the caller, and the
  gateway compares it with the verified email of the run's caller. The SDK sends no identity of
  its own; the Cloudflare Access edge sets it. The `disabled` mode is a dev/local fallback only:
  there the grant `sub` is `"anonymous"` and the gateway skips the subject check (CV-19). The
  SDK does nothing special in either mode.

What not to do:
- Do not decode, verify or log the grant. `_ReplayBinding.grant` is `repr=False`.
- Do not fall back to a plain run when the grant request fails (RP-E5).
- Do not put the grant on `POST /token` (D7 X-5), in a WebSocket frame, or in the url4.
- Do not import `jwt`, `cryptography`, or anything from `apps/`. The runtime module may use
  PyNaCl only.
- Do not use the OS keychain for the local keys. Do not store or log `AIGATEWAY_SECRET_KEY`
  (this unit does not touch it). The local signing keys are not provider credentials, so
  `credential_blobs` does not apply to them.
- Do not change a prior test. Stop and ask instead.

Gates:

```bash
uv run .claude/scripts/run_gates.py screamingface --base e14-reproducible-submission-spec
```

WHY this `--base`: the unit branch starts at the e14 branch HEAD (D1).

Note: `src/screamingface/_runtime/*` is out of the SDK coverage (`pyproject.toml`
`[tool.coverage.run] omit`). The RP-20 tests still run in the SDK job, because they need only
PyNaCl.

## 8. Verification

```bash
cd packages/screamingface
uv run pytest tests/test_replay_pinned_run.py tests/test_replay_contract_counters.py \
  tests/test_runtime_signing_keys.py tests/test_publish_cache_version.py -q
uv run pytest tests/test_answer_seed_report.py tests/test_report.py tests/test_leaderboards.py \
  tests/test_submit_cache_version.py tests/test_runtime_cli.py tests/test_public_surface.py -q
cd ../.. && uv run .claude/scripts/run_gates.py screamingface --base e14-reproducible-submission-spec
```

Done when every `test_rp16_*` to `test_rp20_*` and `test_pb21_*` (rows 1 to 25) is green (sync and async where
listed), the prior files are green with no edit, the snapshot shows only the planned surface
(`evaluate(..., replay)`, `sf.evaluate(..., replay)`, `ReplayUnavailable`, `ReplayProvenance`,
`CandidateResult.replay`, `CacheVersionPublication`, `publish_cache_version` twins and
facade), the CHANGELOG and README have the entries (the README states the 12 h grant limit of
D4), the ledger has the `file:line` rows of §2.1, and the gates are green. Conventional commits
on `unit/SDK-replay`, no `Co-Authored-By`. Do not open a PR. Tell the integrator that the unit
branch is ready (D1).

## 9. Open decisions

None open. The earlier items are closed as follows.

Decided by the user:

- **Where the grant header goes.** Decided: D7 (X-5). `X-SF-Cache-Replay` rides the start
  request `GET /?q=` (`apps/screamingface-engine/src/screamingface_engine/rest/routes.py:597-676`),
  next to `X-Answer-Seed` (`packages/screamingface/src/screamingface/_engine/transport.py:949-960`).
  `POST /token` does not carry it (§4.7). ENG-replay reads it there.
- **The engine counter wire names.** Decided: D7 (X-7). `cache.version.hits`,
  `cache.version.misses`, `cache.version.repeated_key_collapses` on the closing cache-summary
  LogData frame of the root source (§4.8). ENG-replay emits them even when a count is 0.
  `repeated_key_collapses` is an upper bound.
- **Local key env names and forms.** Decided: D7 (X-4). Standard base64 of the raw 32-byte
  seed or public key; public-key maps are JSON `{kid: b64}`; the receipt kid is
  `sha256(raw public key).hexdigest()[:16]`; the grant kid comes from
  `SCOREBOARD_REPLAY_GRANT_SIGNING_KID` (§4.12).
- **A pin time with no UTC offset, and one grammar in two places.** Decided: D7 (X-21). The
  grammar is mirrored (the SDK copy here, the scoreboard copy in SB-registry, SR-20). Both sides
  reject a time with no UTC offset (§4.1 rule 6, row 9).
- **Grant life shorter than a run (A3).** Decided: D4. Keep `exp = iat + 43,200` s. No refresh.
  A grant that expires mid-run fails that run with the typed error (§7, row 25). A3 is
  "[checked] false, accepted".
- **Local archive directory and E14 flags in `screamingface up`.** Decided: D6. The WIRING unit
  owns them (§2.1).
- **A shared JWS package.** Decided: D7 (X-3). No new shared package. PyJWT EdDSA stays behind
  service-local ports. The SDK needs none of it.
- **Production identity.** Decided: D5 (§7).
- **respx.** Decided: D7 (X-20). The tests use `httpx.MockTransport`.

Unit-local, decided (default):

- **OD-7 — unit size.** Keep one unit (replay, local keys, publish). The unit map has one unit.
- **OD-8 — `pinned_baseline_result_id`.** The resolved `result_id` for a `date` pin only;
  `null` for the other forms (§4.2).
- **OD-9 — `replay=` with a raw url4 string.** `TypeError` (a raw url4 has no `benchmark=`, so
  C6 has no `benchmark_id`) (§4.5, row 12).
- **OD-10 — a replay run with no counters.** The report shows `coverage == "unknown"`, and
  `submit` refuses it (§4.10, row 14). Zeros would state a false fact.
- **OD-12 — "portal links" in PB-21.** The returned value carries `release_url`. The portal
  button and the "Published"/"Withdrawn" markers are SB-publish work.

Not owned by this unit (for reference only):

- **A5 and SR-5.** The SDK already imports and vendors `url4`; SB-registry adds the scoreboard
  dependency; the SR-5 parity test lives in `packages/url4/tests` plus a scoreboard test, not
  in the SDK (index X-9).
