# E14 E2E Implementation Plan (unit `E2E`, wave 5)

> **For agentic workers:** use the `sdlc-python` loop (ledger, then RED, then GREEN, then gates,
> then commit). Do the steps in order. Each step uses checkbox (`- [ ]`) syntax. When a step
> says **STOP**, do not continue. Report to the orchestrator.

**Goal:** Prove the four E14 flow spines end to end, on a real local stack (real gateway, real
engine, real scoreboard), with zero provider spend: MD-21, SC-23 and RP-21 in the E2E replay
lane, and PB-22 nightly against a sandbox GitHub repo.

**Delivery (D1):** this unit lands on the one branch `e14-reproducible-submission-spec`. There
is no unit PR, no Linear sub-issue and no unit CI merge gate. Build it in a temporary worktree
on the branch `unit/E2E`, made from the e14 branch HEAD after wave 4 is integrated
(`git checkout -B unit/E2E e14-reproducible-submission-spec`). After wave 5, the integrator
merges `unit/WIRING` first and `unit/E2E` second into the e14 branch, and runs the gates and
this E2E lane. Plan: this file (`docs/plan/2026-09-29-e14-reproducible-submission/E2E.md`).
Ledger: `docs/work/2026-09-29-e14-e2e.md` (start it before Step 1).

**Architecture:** Extend the existing OME-961 e2e replay lane in
`packages/screamingface/tests/e2e/`. That lane already boots the real gateway (Postgres
testcontainer, request cache seeded from a committed snapshot, zero provider keys) and the real
engine in local mode, and drives the SDK the way a notebook does. Its own docstring calls it
"`screamingface up` for one test" (`packages/screamingface/tests/e2e/harness/stack.py:3-9`).
This unit adds a third process (the scoreboard), the E14 key, flag and archive wiring (taken
from the local-runtime code of SDK-replay and WIRING), and a test edge that stands in for
Cloudflare Access + Envoy: it sets a verified `X-User-Email` per user, from an allowed network,
so the scoreboard and the gateway run their production auth mode `cloudflare_headers` (D5), and
the two-user flows use real identities. The model answers come from the committed `ifeval` snapshot, so
a cache miss is a loud `404 profile_not_found`, never spend
(`packages/screamingface/tests/e2e/harness/cache_seeded.py:25-29`).

**Tech stack:** Python 3.12, pytest (`asyncio_mode = "strict"`), httpx, testcontainers
(Postgres), PyNaCl (already a runtime dependency of the SDK:
`packages/screamingface/pyproject.toml:21`), GitHub Actions.

**Spec (the rubric):** `docs/spec/2026-09-29-e14-reproducible-submission/` —
`prd/edit-metadata.md` (MD-21), `prd/submit-and-cluster.md` (SC-23),
`prd/replay-pinned-run.md` (RP-21), `prd/publish-and-takedown.md` (PB-22),
`contracts.md` (C1–C10), `test-plan.md` §1, §4, §6.

## Global constraints

- Component: `packages/screamingface` (tests only) plus `.github/workflows/`. The root for the
  gates is `packages/screamingface`. **Change no file under `src/`**, and no file under `apps/`.
  If a test needs a product change, **STOP**: that change belongs to the unit that owns the
  component.
- Gates: `uv run .claude/scripts/run_gates.py screamingface --base e14-reproducible-submission-spec`
  from the repo root (the `screamingface` card in `.claude/sdlc.local.md:59-70`). WHY this
  `--base`: the unit branch starts at the e14 branch HEAD (D1).
- The e2e tests skip loudly when the stack cannot run (`harness/_gating.py:28-45`). The
  normal SDK test job (`.github/workflows/screamingface-tests.yml:65-74`) runs all tests, so
  every new test must go through the gate and skip there. It must never error there.
- Clean-environment rule: each child gets `clean_env()` plus the variables the harness sets,
  never the shell (`harness/_local_proc.py:9-15`). Put no provider key in any child env.
- The `ReplayBackend` port stays exactly `start() -> base_url` and `stop()`
  (`harness/ports.py:8-11`). Put new backend setup in the constructor.
- Do not import `apps/*` packages into the SDK test process. Talk to each service over HTTP
  only. Two exceptions: (1) the SQL step in §4.3 step 5 (board preparation), which runs `psql`
  inside the scoreboard's own test container; (2) the harness imports the SDK local-runtime env
  builders (`screamingface._runtime.signing_keys` of SDK-replay, and the WIRING hook of §4.1).
  They are SDK code, not app code, and they are the same code that `screamingface up` runs.
- Auth mode (D5): the scoreboard and the gateway of the E14 stack run `cloudflare_headers`.
  `disabled` is a dev/local fallback only. Do not design a test around `disabled`.
- Tests are append-only. Do not change an existing test. Do not add a sleep, a retry or a
  skip to get green (`test-plan.md` §1.7). Polling with a deadline for an async state (the
  publish worker) is allowed, with the deadline from the NFR.
- Comment anchors: `WHY:`, `INVARIANT:`, `AIDEV-NOTE:`, `FEATURE:`, `STORY:` only.
- Commits: conventional (`test(e2e): …`, `ci(e2e): …`) on `unit/E2E`. Do not open a PR
  (D1). **No `Co-Authored-By` trailer.**
- Files stay under 450 lines.

## 1. Scope

**Owns exactly these test ids:**

| Id | Test name | Source |
|---|---|---|
| MD-21 | `test_submit_then_edit_then_read_on_leaderboard` | `prd/edit-metadata.md:222`, MD-D5 |
| SC-23 | `test_two_users_same_system_one_row_two_results_original_ranks` | `prd/submit-and-cluster.md:239`, SC-H2, SC-H3 |
| RP-21 | `test_submit_then_other_user_replays_all_hits_zero_cost_then_submit_labelled_replay` | `prd/replay-pinned-run.md:243`, RP-H1, RP-D9 |
| ~~RP-22~~ | ~~`test_changed_recipe_pin_by_date_partial_hits`~~ | Dropped (owner, 2026-09-30, Q30): no paid run is used as a test |
| PB-22 | `test_submit_publish_download_asset_digest_matches_version` | `prd/publish-and-takedown.md:221` (nightly, sandbox repo) |

**Out of scope** (other units own them; do not test them here):

- Every unit and integration row of every PRD (SR-*, CV-*, MD-1..20, SC-1..22, RP-1..20,
  PB-1..21).
- Races, retries and idempotency (SC-3, SC-10, PB-4, PB-8). E2E proves the happy spines.
- The portal UI (SC-22, MD-20, PB-21 portal half). E2E reads the JSON API only.
- The literal `screamingface up` supervisor wiring (RP-20 in `SDK-replay`; flags and archive
  dir in `WIRING`, D6). E2E reuses their env builders (§4.1), so a wrong key or flag in them
  fails E2E, but E2E does not test `up` itself. See OD-1.
- Deploy charts and the ingress precondition (WIRING, D6).
- Admin takedown (PB-10). PB-22 covers publish and download only.
- NFR benchmarks (capture p99, replay p99, freeze time).

## 2. Depends on

- **Code dependencies (real):** all product units of waves 1 to 4 — `SB-schema`, `URL4-fp`,
  `GW-capture`, `SB-meta`, `SB-registry`, `GW-freeze`, `ENG-freeze`, `SDK-meta`, `SB-submit`,
  `GW-replay`, `ENG-replay`, `SDK-submit`, `SB-grants`, `SB-publish`, `SDK-replay`. They are on
  the e14 branch HEAD when this unit starts (D2).
- **WIRING (wave 5, same wave; D6).** E2E uses the WIRING local-runtime wiring (the E14 flags and
  the archive dir of `screamingface up`) and the WIRING admin route that sets
  `Benchmark.redistributable`. **As built (2026-09-30):** WIRING was merged (093330ec) before
  E2E started, so the E2E review removed the planned fallback. The harness imports
  `apply_local_e14_environment` directly, and it always calls the admin route. A missing or
  broken WIRING hook is an import error or a test failure, never a silent fallback. The
  original plan text (a fallback when WIRING is absent, and a drift check in Step 1.2) is
  superseded.
- **Contracts consumed (black box, over HTTP and the SDK):**
  - C1 (SDK → engine run with `X-SF-Cache-Replay` on the start request `GET /?q=`, D7 X-5):
    RP-21.
  - C2a/C2b (freeze through the engine): all four tests, through `client.leaderboards.submit`.
  - C3 (receipt, gateway → scoreboard; `sub` is the verified email, and the scoreboard checks
    it in `cloudflare_headers` mode): all four tests.
  - C4 (submit with `paper_url`, `revision_of`, receipt, `replay` block): all four tests.
  - C5 (metadata `PATCH` and read; owner check on the verified email): MD-21.
  - C6 (replay grant; `sub` is the verified email): RP-21.
  - C7 (GitHub releases): PB-22 only.
  - C8a/C8b (archive, gateway writes and scoreboard reads): PB-22.
  - C9 (chat call with the grant header, `X-AIGW-Cache-Version`; the gateway checks the grant
    `sub` against the caller): RP-21 (seen through the report counters).
  - C10 (results list, publish): SC-23, RP-21, PB-22.
  - The engine counter frame (D7 X-7), through the SDK report: RP-21.
- **Implements no contract.** This unit adds no product code.

### 2.1 Integration notes

- Same-wave unit: WIRING. Merge order: WIRING before E2E.
- Possible shared files with WIRING: `packages/screamingface/pyproject.toml` (E2E adds one
  marker line), `packages/screamingface/tests/e2e/README.md`, and
  `.github/workflows/screamingface-e2e-replay.yml`. E2E changes are additive (one marker, one
  README section, two `paths:` lines and `timeout-minutes`). If WIRING changes the same lines,
  the integrator keeps both.
- The WIRING names that E2E needs (the hook module and function, the admin route, the admin
  allowlist variable, the archive-dir variables) come from
  `docs/plan/2026-09-29-e14-reproducible-submission/WIRING.md`. Step 0 copies them into the
  ledger. If WIRING.md does not name one of them, **STOP** and ask.

**Values this plan reads from the merged code, not from the spec** (the spec names them, but
not their encoding). Before Task 2, read each one in the merged code and write it into the
work ledger with its `file:line`:

| Value | Spec source | Where to read it |
|---|---|---|
| Key env names and forms: `AIGATEWAY_RECEIPT_SIGNING_KEY`, `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS`, `SCOREBOARD_RECEIPT_PUBLIC_KEYS`, `SCOREBOARD_REPLAY_GRANT_SIGNING_KEY`, `SCOREBOARD_REPLAY_GRANT_SIGNING_KID` | D7 X-4 (raw base64, JSON `{kid: b64}`, receipt kid derived) | `packages/screamingface/src/screamingface/_runtime/signing_keys.py` (SDK-replay §4.12), and the four settings classes (GW-freeze, GW-replay, SB-submit, SB-grants) |
| The WIRING local-runtime hook (module, function, signature) that sets the E14 flags and the archive dir for `screamingface up` | D6 | `WIRING.md` §4, then the merged WIRING code |
| The WIRING admin route that sets `Benchmark.redistributable`, and the scoreboard admin allowlist variable it checks | D6 | `WIRING.md` §4 (the same allowlist pattern as the SB-publish withdraw route) |
| Every E14 feature flag whose code default is off: `SCOREBOARD_CLUSTERING_ENABLED` (SB-submit §4.1), `AIGW_CACHE_VERSIONS_ENABLED` (GW-capture), and any flag of SB-grants or SB-publish | index X-12 | each settings class, and the WIRING hook (it must set each one) |
| The filesystem archive directory variables (gateway writer and scoreboard reader) | `contracts.md` C8 "Local mode" | GW-freeze and SB-publish settings classes, and the WIRING hook |
| The file layout of the filesystem `VersionArchiveStore` adapter: where the object key `cache-versions/<vid>/entries.jsonl.gz` lands under the root | `contracts.md` C8, `erd.md` §3.5 | the GW-freeze filesystem adapter |
| `archive_sha256` preimage: the sha256 of the gzip bytes of `entries.jsonl.gz` (mtime 0, level 9), and the preimage of the manifest `entries_sha256` | Decided: D7 X-16 | the GW-freeze archive exporter (record `file:line`) |
| Auth env of the scoreboard: `SCOREBOARD_AUTH_MODE`, `SCOREBOARD_ALLOWED_NETWORKS`, the `FORWARDED_ALLOW_IPS` guard | D5 | `apps/scoreboard/src/scoreboard/config.py:43-63`, `apps/scoreboard/src/scoreboard/main.py:115-176` |
| Auth env of the gateway: `AIGW_AUTH_MODE`, `AIGW_ALLOWED_NETWORKS`, admin emails `AIGATEWAY_ADMIN_EMAILS`, account get-or-create per email | D5 | `apps/aigateway/src/aigateway/config.py:38-58`, `apps/aigateway/src/aigateway/main.py:386-392`, `apps/aigateway/src/aigateway/core/auth/cloudflare_identity.py` (`account_for_identity`) |
| The engine forwards the inbound `X-User-Email` of the start request (`GET /?q=`) and of `POST /v1/cache-versions` to the gateway, in the local app that the harness runs | ENG-freeze §4, ENG-replay | `apps/screamingface-engine/src/screamingface_engine/request_scope.py:169`, `job_env.py:76-90`, and the ENG-freeze route |
| The global request cache (the seeded snapshot) is shared by all accounts, so a new `cloudflare_headers` account still gets the snapshot hits | OME-305 | `apps/aigateway/src/aigateway/core/request_cache/global_controls.py` |
| The report replay attribute (`candidate.replay.*`) | RP-H1 | SDK-replay §4.9 |
| The SDK kwargs `paper_url=`, `revision_of=` on `submit`, and `update_submission`, `publish_cache_version` | C4, C5, C10, MD-H6, PB-H1 | SDK-meta, SDK-submit, SDK-replay |
| The results-list item field names. SB-submit §4.3 `ReportedResultSchema`: `reporter`, `is_original`, `cache_version` (`id`, `sha256`, `entry_count`, `call_count`, `coverage_status`), `publication_state`, and a nested `replay` block (`replayed_from_result_id`, `hits`, `misses`, `pinned_baseline_result_id`). Envelope `{"results": [...], "next_cursor": ...}` (C10). | `erd.md` §2.2, C4, C10 | SB-submit results schema |
| Whether the leaderboard entry carries `paper_url` (MD-D5), `score_id` and `reported_results_count` (SB-submit §4.10) | MD-D5, SC-22 | SB-meta and SB-submit leaderboard schemas |
| The GitHub App and target repo variables | PB-D7 | SB-publish settings class, WIRING chart values |

**STOP** if one of these values is not in the merged code, or if its docstring does not state
the encoding. Do not guess an encoding.

**Assumption resolutions for this track:**

- **A3 (grant life vs job deadline).** "[checked] false, accepted" (Decided: D4). The grant
  lives 43,200 s (12 h). The job deadline (57,600 s) plus the queue wait can exceed it. A grant
  that expires mid-run fails that run with the typed error (the RP-14 path). E2E runs are
  short (minutes), so no E2E test changes and no E2E test waits for an expiry.
- **A5 (scoreboard depends on `packages/url4`).** Not this track. SB-registry adds it.
- **SR-5 parity.** Not this track (SR-5 is in `URL4-fp`). E2E adds an indirect check only:
  SC-23 fails if the SDK and the scoreboard disagree on the system, because the second run
  would not cluster.
- **Ed25519 JWS.** E2E never signs or verifies a token. It gets the two keypairs from the SDK
  local-runtime builder (`apply_local_signing_environment`, SDK-replay §4.12: PyNaCl, raw
  base64, derived receipt kid). The gateway and the scoreboard sign and verify with their own
  service-local ports (PyJWT, D7 X-3).

## 3. Files

| File | Change | Exemplar to imitate |
|---|---|---|
| `packages/screamingface/tests/e2e/harness/e14_env.py` | create: the E14 env of the stack (keys from SDK-replay, flags and archive dir from the WIRING hook; as built: no fallback) | `harness/_gating.py:1-45` (small pure module, typed, `Final` names) |
| `packages/screamingface/tests/e2e/harness/identity.py` | create: the test edge (`EdgeIdentityTransport`) | `harness/ports.py` (one small seam with a docstring that states the invariant) |
| `packages/screamingface/tests/e2e/harness/scoreboard_proc.py` | create | `harness/cache_seeded.py:108-175` (Postgres container, migrate, subprocess, health) |
| `packages/screamingface/tests/e2e/harness/e14_stack.py` | create | `harness/stack.py:94-116` (`replay_stack` context manager, reverse teardown) |
| `packages/screamingface/tests/e2e/harness/cache_seeded.py` | change: add `extra_env` and `auth_mode` constructor kwargs; send the admin identity on the seed calls in `cloudflare_headers` mode | same file, `__init__` at `:71-77`, env at `:147-160`, seed client at `:203` |
| `packages/screamingface/tests/e2e/harness/stack.py` | change: add `extra_env` kwarg to `EngineProcess.__init__` | same file, `:47-72` |
| `packages/screamingface/tests/e2e/harness/_local_proc.py` | change: add `refuse_secret_env(extra_env: Mapping[str, str] \| None) -> None` (§4.5) | same file, `clean_env` at `:46-49` |
| `packages/screamingface/tests/e2e/conftest.py` | change: add the E14 fixtures | same file, `:23-39` (`synthetic_gateway`) |
| `packages/screamingface/tests/e2e/test_e14_submit_edit.py` | create (MD-21) | `tests/e2e/test_boards.py:110-150` |
| `packages/screamingface/tests/e2e/test_e14_cluster.py` | create (SC-23) | `tests/e2e/test_boards.py:110-150` |
| `packages/screamingface/tests/e2e/test_e14_replay.py` | create (RP-21) | `tests/e2e/test_boards.py:110-150` |
| `packages/screamingface/tests/e2e/test_e14_publish_nightly.py` | create (PB-22) | `tests/e2e/test_boards.py:110-150` |
| `packages/screamingface/tests/e2e/test_e14_harness_contracts.py` | create (harness self-tests, no stack) | `tests/e2e/test_harness_contracts.py` |
| `packages/screamingface/pyproject.toml` | change: add marker `e2e_github` next to `e2e` and `paid` | same file, `:132-140` |
| `packages/screamingface/tests/e2e/README.md` | change: add a short "E14 spines" section | same file |
| `.github/workflows/screamingface-e2e-replay.yml` | change: add `apps/scoreboard/**` to both `paths:` lists; `timeout-minutes: 60` | same file |
| `.github/workflows/screamingface-e14-publish-nightly.yml` | create | `.github/workflows/screamingface-e2e-replay.yml` (steps) and `screamingface-paid-inspect-smoke.yml:1-40` (secret gate, header comment) |
| `docs/work/2026-09-29-e14-e2e.md` | create (work ledger) | any file in `docs/work/` |

## 4. Signatures and data shapes

### 4.1 `harness/e14_env.py`

```python
GATEWAY_PREFIXES: Final = ("AIGATEWAY_", "AIGW_")
SCOREBOARD_PREFIXES: Final = ("SCOREBOARD_",)

# As built: a direct import. No harness copy of the WIRING flags exists.
from screamingface._runtime.local_features import apply_local_e14_environment
from screamingface._runtime.signing_keys import apply_local_signing_environment

@dataclass(frozen=True, slots=True)
class E14Env:
    gateway: Mapping[str, str]      # AIGATEWAY_* and AIGW_* keys only
    scoreboard: Mapping[str, str]   # SCOREBOARD_* keys only
    archive_dir: Path               # the root of the filesystem archive adapter (C8 local mode)

def e14_env(data_dir: Path) -> E14Env: ...
def split_env(env: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]: ...
```

`e14_env(data_dir)` steps, in this order:

1. `env: dict[str, str] = {}`. `data_dir.mkdir(parents=True, exist_ok=True)`.
2. `apply_local_signing_environment(env, data_dir)` from
   `screamingface._runtime.signing_keys` (SDK-replay §4.12). The env is empty, so it sets all
   five key variables and writes `data_dir / "signing-keys.json"` (mode 0600). WHY: this is
   the code `screamingface up` runs, so the E2E keys have the same form as the local runtime
   keys (raw base64, JSON `{kid: b64}`, receipt kid `sha256(raw public key).hexdigest()[:16]`,
   grant kid `"local-" + …`, D7 X-4).
3. **As built:** `apply_local_e14_environment(env, data_dir)` (WIRING,
   `screamingface._runtime.local_features`). It sets `AIGW_CACHE_VERSIONS_ENABLED` and
   `SCOREBOARD_CLUSTERING_ENABLED` to `"true"`, the two archive backends to `"filesystem"`, and
   the two archive dirs to `str(data_dir / "cache-version-archive")`. There is no fallback and
   no `source` field: a renamed or broken hook fails at import or at call time.
4. `archive_dir = Path(env["AIGW_CACHE_VERSION_ARCHIVE_DIR"])`; `mkdir(parents=True,
   exist_ok=True)`. Raise `RuntimeError` when `env["SCOREBOARD_ARCHIVE_FS_ROOT"]` has another value
   (C8 local mode: one shared directory).
5. `gateway, scoreboard = split_env(env)`. `split_env` puts a key with a `GATEWAY_PREFIXES`
   prefix into `gateway`, a key with a `SCOREBOARD_PREFIXES` prefix into `scoreboard`, and
   raises `ValueError(f"E14 env key has no service prefix: {key}")` for any other key (the key
   name, never the value).

INVARIANTS:
- The harness never logs a key value. The only key file is the SDK-replay file under the
  test's `tmp_path` data dir (mode 0600). It goes away with `tmp_path`.
- The private receipt key goes only to the gateway map, and the private grant key goes only to
  the scoreboard map (Step 1.2 checks it).
- `refuse_secret_env` (§4.5) runs on both maps, so no `*_API_KEY` and no
  `AIGATEWAY_SECRET_KEY` can reach a child.

### 4.2 `harness/identity.py` — the test edge

```python
EDGE_NETWORK: Final = "127.0.0.1/32"   # the allowed network of the scoreboard and the gateway
FORWARDED_ALLOW_IPS_E2E: Final = "192.0.2.1"
# WHY 192.0.2.1 (TEST-NET-1, never a real peer): uvicorn defaults FORWARDED_ALLOW_IPS to
# 127.0.0.1, which overlaps EDGE_NETWORK, and the scoreboard create_app refuses that overlap in
# cloudflare_headers mode (apps/scoreboard/src/scoreboard/main.py:152-176). The same value as the
# SB-submit clustered_cf_app fixture.

class EdgeIdentityTransport(httpx.BaseTransport):
    """Test-only stand-in for Cloudflare Access + Envoy: every request leaves as `user`."""
    def __init__(self, user: str, inner: httpx.BaseTransport | None = None) -> None: ...
    def handle_request(self, request: httpx.Request) -> httpx.Response: ...
    def close(self) -> None: ...   # closes `inner`
```

- `handle_request`: remove every `X-User-Email` header of the request (any casing; Envoy clears
  a client copy first), then set `X-User-Email: <user>`. Change nothing else (method, URL, body,
  other headers). Then `return self._inner.handle_request(request)`. `inner` defaults to
  `httpx.HTTPTransport()`.
- WHY this is the production path (D5): the scoreboard and the gateway run
  `cloudflare_headers`. Each checks that the TCP peer is in `EDGE_NETWORK` (the loopback peer
  of the test process and of the engine), and only then reads `X-User-Email`
  (`apps/scoreboard/src/scoreboard/routes/scores.py:105-117`,
  `apps/aigateway/src/aigateway/core/auth/middleware.py:47-80`). So the submitter, the result
  `reporter`, the receipt `sub`, the grant `sub`, the metadata owner and the publish owner are
  all the verified email. No test seam writes `submitted_by`.
- The SDK takes the edge on both sides: `sf.Client(engine_url=..., scoreboard_url=...,
  http_transport=EdgeIdentityTransport(user), scoreboard_transport=EdgeIdentityTransport(user))`
  (`packages/screamingface/src/screamingface/client.py:49-50`). The engine forwards
  `X-User-Email` from the start request and from `POST /v1/cache-versions` to the gateway
  (§2 value table row). So Bruno's run reaches the gateway as Bruno.
- Helper, in the same module:

```python
# `from __future__ import annotations` and `if TYPE_CHECKING: from .e14_stack import E14Stack`
# (no import cycle: e14_stack imports this module, not the reverse at run time).
def edge_client(stack: E14Stack, user: str) -> sf.Client:
    return sf.Client(engine_url=stack.engine_url, scoreboard_url=stack.scoreboard_url,
                     http_transport=EdgeIdentityTransport(user),
                     scoreboard_transport=EdgeIdentityTransport(user))

def edge_http(base_url: str, user: str | None) -> httpx.Client:
    # user None: an anonymous read of a public board (no header at all).
```

### 4.3 `harness/scoreboard_proc.py`

```python
SCOREBOARD_ADMIN: Final = "e2e-scoreboard-admin@e2e.example"

class ScoreboardProcess:
    def __init__(self, *, work_dir: Path, extra_env: Mapping[str, str] | None = None) -> None: ...
    # As built: no `wiring_present` kwarg. The admin route is always called (step 5).
    def start(self, *, engine_url: str, board: str) -> str: ...   # returns the base URL
    def stop(self) -> None: ...                                   # idempotent
```

`__init__` calls `refuse_secret_env(extra_env)`. `start` stages, in order:

1. Start a `postgres:16-alpine` `PostgresContainer(driver=None)` (copy
   `cache_seeded.py:110-121`). Use its own container. Do not share the gateway's database.
   WHY Postgres, not sqlite: the publish worker leases with `SELECT … FOR UPDATE SKIP LOCKED`
   (PB-D2), which sqlite does not have.
2. `uv sync` `apps/scoreboard` (`sync_project`), then run
   `.venv/bin/python -m tortoise -c scoreboard.db.TORTOISE_CONFIG migrate` with
   `SCOREBOARD_DATABASE_URL=<dsn>` (the config reads that variable:
   `apps/scoreboard/src/scoreboard/db.py:11-13`).
3. Seed: `.venv/bin/python -m scoreboard.seed --engine-url <engine_url>` with the same
   `SCOREBOARD_DATABASE_URL` (`apps/scoreboard/src/scoreboard/seed.py:552-638`). Fail loudly on
   a non-zero exit.
4. Start `.venv/bin/uvicorn --factory scoreboard.main:create_app --host 127.0.0.1 --port
   <free_port> --log-level warning` (`create_app` at `apps/scoreboard/src/scoreboard/main.py:106`)
   with `clean_env({SCOREBOARD_DATABASE_URL: <dsn>, SCOREBOARD_AUTH_MODE: "cloudflare_headers",
   SCOREBOARD_ALLOWED_NETWORKS: EDGE_NETWORK, FORWARDED_ALLOW_IPS: FORWARDED_ALLOW_IPS_E2E,
   SCOREBOARD_ADMIN_EMAILS: SCOREBOARD_ADMIN, **extra_env})`.
   `extra_env` is `E14Env.scoreboard` (keys, flags, archive dir) plus the PB-22 App variables.
   Wait on `GET /healthz` (`apps/scoreboard/src/scoreboard/routes/health.py:8`).
   WHY the clustering flag is in `extra_env`: the SB-submit code default is `False`, and with it
   off `POST /v1/scores` runs the legacy path and ignores the receipt (SB-submit §4.1).
5. Board preparation (after the app is healthy):
   - `redistributable = true` (**as built: always by the route**). Call the WIRING admin route
     `PUT /v1/admin/benchmarks/<board>/redistributable` with the body
     `{"redistributable": true, "reason": "e2e"}` (WIRING.md §2.1, §4.1; success is `200`)
     through `edge_http(base_url, SCOREBOARD_ADMIN)`. Raise `RuntimeError` unless the status is
     2xx and the response has `redistributable is true` (`GET /v1/benchmarks` has no
     `redistributable` field, ledger D-6). There is no SQL fallback for this column. WHY: D6
     makes the route the product path, so E2E proves it.
   - SQL, test-only (as built: `case_count` only): `container.exec(["psql", "-U", user, "-d",
     dbname, "-v", "ON_ERROR_STOP=1", "-c", "UPDATE benchmarks SET case_count = NULL WHERE id =
     '<board>'"])`. `container.exec` (testcontainers 4) returns
     `(exit_code, output)`. Raise `RuntimeError` unless `exit_code == 0` and `b"UPDATE 1" in
     output`.
   - WHY `case_count = NULL`: the golden replays 50 cases (`fixtures/goldens/ifeval.golden.json`,
     `limit: 50`), and the leaderboard hides a run with fewer cases than `case_count`
     (`apps/scoreboard/src/scoreboard/scores/store.py:661-662`). With `NULL` the filter is off
     (`store.py:655-656`). No product path sets it, and none is needed.
   - WHY `redistributable`: the column defaults to `false` (`erd.md:225`). RP-21 (a non-owner
     replay) and PB-22 need a public, redistributable board.

### 4.4 `harness/e14_stack.py`

```python
@dataclass(frozen=True, slots=True)
class E14Stack:
    engine_url: str
    aigateway_url: str
    scoreboard_url: str
    archive_dir: Path
    # As built: no `env_source` field (the hook is always the source).

@contextmanager
def e14_stack(
    *,
    work_dir: Path,
    assets_dir: Path,
    board: str = "ifeval",
    scoreboard_extra_env: Mapping[str, str] | None = None,
) -> Iterator[E14Stack]: ...
```

Order (teardown in reverse, also after a failed boot, as in `stack.py:104-116`):

1. `env = e14_env(work_dir / "runtime-data")` (§4.1).
2. Gateway: `CacheSeededGateway(snapshot=SNAPSHOTS_DIR / f"{board}.snapshot.gz",
   manifest=<manifest or None>, work_dir=work_dir, auth_mode="cloudflare_headers",
   extra_env=env.gateway)`.
3. Engine: `EngineProcess(work_dir=work_dir, assets_dir=assets_dir)`, `start(gateway_url)`.
   The engine keeps its local mode. It reads no identity mode of its own; it forwards
   `X-User-Email` (§2 value table).
4. Scoreboard: `ScoreboardProcess(work_dir=work_dir, extra_env={**env.scoreboard,
   **(scoreboard_extra_env or {})})`, `start(engine_url=..., board=board)`.
5. Yield `E14Stack(..., archive_dir=env.archive_dir)`. (As built: no `env_source` log line.)

WHY one shared `archive_dir`: this is the local-mode filesystem adapter of C8 (gateway writes,
scoreboard reads). No MinIO container is needed.

### 4.5 Changes to existing harness classes

- `CacheSeededGateway.__init__(..., extra_env: Mapping[str, str] | None = None,
  auth_mode: Literal["disabled", "cloudflare_headers"] = "disabled")`.
  - `auth_mode == "disabled"` (default): the env and the seed calls do not change. The OME-961
    tests keep their behavior.
  - `auth_mode == "cloudflare_headers"`: the fixed env gets `AIGW_AUTH_MODE:
    "cloudflare_headers"`, `AIGW_ALLOWED_NETWORKS: EDGE_NETWORK`, `FORWARDED_ALLOW_IPS:
    FORWARDED_ALLOW_IPS_E2E` in place of `AIGW_AUTH_MODE: "disabled"`. The seed client
    (`cache_seeded.py:203`) sends `headers={"X-User-Email": ADMIN_ROLE_EMAIL}`
    (`cache_seeded.py:53`, already in `AIGATEWAY_ADMIN_EMAILS`). WHY: in this mode the admin
    route needs the verified admin identity (`apps/aigateway/src/aigateway/core/auth/admin.py:104-111`).
  - Merge `extra_env` **after** the fixed env in `_start_gateway` (`cache_seeded.py:149-163`).
    Raise `ValueError` in `__init__` (before any container starts) if `extra_env` has a key
    that ends with `_API_KEY`, or the key `AIGATEWAY_SECRET_KEY` (message
    `"refusing secret env key: <KEY>"`, from `refuse_secret_env`), or the key `AIGW_AUTH_MODE`
    (message `"refusing env key: AIGW_AUTH_MODE (use auth_mode=)"`, a check in
    `CacheSeededGateway.__init__` only). The message names the key, never the value. INVARIANT: spend stays
    impossible by construction, and the harness never sets the credential master key.
- `EngineProcess.__init__(..., extra_env: Mapping[str, str] | None = None)`. Merge it after
  the fixed env in `start` (`stack.py:56-70`). Same guard, in `__init__`. Put the guard in one
  function `refuse_secret_env(extra_env)` in `harness/_local_proc.py`, and call it from all
  three classes. (Pass `None` for the engine in this unit unless ENG-freeze or ENG-replay added
  a required engine variable; if so, record it in the ledger with its `file:line`.)
- Existing callers pass nothing, so their behavior does not change.

### 4.6 Fixtures (`conftest.py`)

- `e14_assets() -> Path` (session): the same rule as `test_boards.py:74-82` (`_assets_root`):
  `Path(os.environ["SCREAMINGFACE_E2E_ASSETS"])` when set, else
  `screamingface._runtime.config.default_data_dir() / "benchmark-assets"`. Then
  `/ "ifeval"` must be a directory, or `pytest.skip` with the reason. Write these few lines in
  `conftest.py`. Do not import from `test_boards.py` (a test module is not a library), and do
  not change `test_boards.py` (append-only).
- `e14_golden() -> GoldenReport` (session): `load_golden(GOLDENS_DIR / "ifeval.golden.json")`.
- `e14` (**function** scope, `tmp_path` as `work_dir`): `require_e2e_stack()`, then
  `with e14_stack(work_dir=tmp_path, assets_dir=e14_assets) as stack: yield stack`.
  WHY function scope: RP-21 and SC-23 use the same recipe
  (`build_candidate(golden)`), so on a shared stack one test's head would absorb the next
  test's submit (it would cluster, or get `system_already_named`) and the result depends on
  test order. One stack per test removes that. INVARIANT: no test reads rows that another test
  wrote.

### 4.7 Constants used by the tests

- Board: `"ifeval"`. Candidate: `build_candidate(e14_golden)` (`harness/goldens.py:313-343`),
  `limit=e14_golden.limit` (50), `progress=False`.
- Users (verified emails set by the edge): `"ana@e2e.example"`, `"bruno@e2e.example"`,
  `"carol@e2e.example"` (RED proofs only). The published local parts
  are `"ana"`, `"bruno"` (`schemas.py:179-230`).
- `paper_url` values: `"https://arxiv.org/abs/2609.01234"`, then `"https://doi.org/10.1234/abc"`
  (MD-H1, MD-H3).
- Every SDK client is `with edge_client(stack, user) as client:` (§4.2).
- Raw reads of public data (`GET /v1/leaderboard/ifeval`, `GET /v1/scores/{id}`,
  `GET /v1/scores/{id}/results`, metadata history) use `edge_http(stack.scoreboard_url, None)`
  (anonymous, as a public reader). A read that needs the owner uses the owner's email.
- Find a head's leaderboard entry by `entry["url4_expression"] == str(candidate_result.url4)`.
  WHY: the entry has no `id` field (`apps/scoreboard/src/scoreboard/scores/schemas.py:763-784`),
  and `score_id` is set only for heads with 2 or more results (SB-submit §4.10).

## 5. Migrations

None. This unit adds no model and no migration. The harness runs the migrations that the
other units merged (gateway: `harness/cache_seeded.py:123-142`; scoreboard: §4.3 step 2).

## 6. TDD order

The product code is merged before this unit starts, so a new E2E test can pass at once. A test
that passes at once proves nothing (`test-plan.md` §1.1). So each test has a **RED proof**: a
named, temporary harness mutation that must make the test fail **on the named assertion**.
Run the mutation once, see the failure, record it in the ledger, and revert the mutation
before the commit. Never commit a mutation.

There are no CHAR rows in this unit.

- [ ] **Step 0 — Ledger and value table.** Start `docs/work/2026-09-29-e14-e2e.md`. Fill
  the §2 value table with `file:line` from the e14 branch HEAD, and the WIRING names from
  `WIRING.md` (§2.1). Write in the ledger whether WIRING is merged on `unit/E2E` (as built: it
  was merged, 093330ec). **STOP** if one value is missing.

- [ ] **Step 1 — Harness self-tests (no stack), `test_e14_harness_contracts.py`.**
  These run in the normal SDK job (no Docker needed).
  1. `test_e14_env_keys_come_from_the_local_runtime_builder` — `e14_env(tmp_path)`: the
     receipt kid (the one key of the JSON map in `scoreboard["SCOREBOARD_RECEIPT_PUBLIC_KEYS"]`)
     equals `hashlib.sha256(base64.b64decode(<its public key>)).hexdigest()[:16]`; each b64 value
     decodes to 32 bytes; a signature made with the seed of
     `gateway["AIGATEWAY_RECEIPT_SIGNING_KEY"]` verifies with that public key
     (`nacl.signing.VerifyKey(...).verify(...)`); the same for the grant pair
     (`SCOREBOARD_REPLAY_GRANT_SIGNING_KEY`, `SCOREBOARD_REPLAY_GRANT_SIGNING_KID`,
     `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS`). Also: the gateway map has only the receipt
     **private** key and the grant **public** map; the scoreboard map has only the grant
     **private** key and the receipt **public** map. RED: create the module with a stub
     `e14_env` that returns empty maps, so the failure is behavioral, not an import error.
  2. **As built (the E2E review replaced the fallback drift check):**
     `test_e14_env_flags_and_archive_dir_are_what_the_wiring_hook_sets` — the flags and the
     archive dir of `e14_env(tmp_path)` equal what the real `apply_local_e14_environment` sets
     on an empty env. `test_e14_env_surfaces_a_failing_wiring_hook` — monkeypatch the
     module-level hook name with a hook that raises, and assert that `e14_env` raises (no silent
     fallback). `test_scoreboard_board_prep_always_uses_the_admin_route` — `ScoreboardProcess`
     takes no `wiring_present`, always calls the route, and its board SQL never sets
     `redistributable`. RED: the first run failed (no direct import, `wiring_present` still
     required), then GREEN (ledger, review-fix round).
  3. `test_e14_env_refuses_a_key_with_no_service_prefix` — `split_env({"OTHER": "x"})` raises
     `ValueError` with the text `OTHER` and never `x`. RED: a stub that drops the key.
  4. `test_edge_sets_the_verified_email_and_drops_a_client_copy` — use `httpx.MockTransport` as
     `inner`. A `POST /v1/scores` with a client header `x-user-email: mallory@x.example`
     arrives with exactly one `X-User-Email` value, `"ana@e2e.example"`
     (`request.headers.get_list("x-user-email") == ["ana@e2e.example"]`), and the same body
     bytes. A `GET` and a `PATCH` get the same header. RED: a pass-through stub.
  5. `test_extra_env_refuses_secrets_and_the_auth_override` —
     `CacheSeededGateway(..., extra_env={"OPENROUTER_API_KEY": "x"})`,
     `CacheSeededGateway(..., extra_env={"AIGATEWAY_SECRET_KEY": "x"})`,
     `CacheSeededGateway(..., extra_env={"AIGW_AUTH_MODE": "disabled"})`,
     `EngineProcess(..., extra_env={"OPENROUTER_API_KEY": "x"})` and
     `ScoreboardProcess(..., extra_env={"OPENROUTER_API_KEY": "x"})` raise
     `ValueError` whose message is exactly `"refusing secret env key: <KEY>"` (for
     `AIGW_AUTH_MODE`: `"refusing env key: AIGW_AUTH_MODE (use auth_mode=)"`). The key name,
     never the value. RED: `refuse_secret_env` is a stub that returns `None`.

- [ ] **Step 2 — Build the harness** (§4.1–4.6). Boot the stack once by hand with a scratch
  test that you do not commit. It asserts: `GET {scoreboard_url}/healthz == 200`;
  `GET {scoreboard_url}/v1/benchmarks` lists `ifeval`; an anonymous
  `GET {scoreboard_url}/v1/leaderboard/ifeval` is `200` (a public board stays readable with no
  identity); and the scoreboard log shows no `create_app` guard error. Write the result in
  the ledger (as built: `stack.env_source` does not exist). Delete the scratch test after. (The committed check that
  the auth mode is real is MD-21 step 0.)
  Also run one `limit=1` evaluation of `build_candidate(golden)` through
  `edge_client(stack, "ana@e2e.example")`. **STOP** and report if any engine or preflight call
  gets `401` or `403` from the gateway: then an engine path does not forward `X-User-Email`
  in the local app, and the fix belongs to the engine units, not to this harness.

- [ ] **Step 3 — SC-23 (H×H, first).** File `tests/e2e/test_e14_cluster.py`,
  `test_two_users_same_system_one_row_two_results_original_ranks`.
  1. Ana: `with edge_client(e14, "ana@e2e.example") as client:`,
     `report = client.evaluate(candidate, benchmark="ifeval", limit=golden.limit, progress=False)`
     with `candidate = build_candidate(golden)`, then
     `a = client.leaderboards.submit(report.candidates.only)`.
  2. Assert `a.reported_result.is_original is True`, `a.reported_result.cache_version` is not
     `None`, its `coverage_status == "complete"`, and `a.cache_version_warning is None`. WHY the
     warning check: in `cloudflare_headers` mode the scoreboard checks that the receipt `sub`
     equals the verified submitter (C3). A `sub` mismatch would give `403
     cache_version_not_yours`, and a gateway that did not see Ana's email would give no receipt.
  3. Record the head's ranked columns (`score`, `run_cost_usd`, `total_questions`,
     `submitted_by`) with a raw `GET /v1/scores/{a.id}`.
  4. Bruno: a second client `edge_client(e14, "bruno@e2e.example")`, a new run of the same
     candidate, `b = submit(...)`.
  5. Assert `b.id == a.id` (no new head), `b.reported_result.is_original is False`, and the
     notices have `{"code": "clustered_under", "score_id": a.id}`.
  6. Assert the raw `GET /v1/scores/{a.id}` ranked columns equal step 3 (SC-H3).
  7. Assert the raw `GET /v1/leaderboard/ifeval` `entries` list has exactly one entry with
     `url4_expression == str(report.candidates.only.url4)`. That entry has `score` and
     `run_cost_usd` equal to step 3, `submitted_by == "ana"`, `score_id == a.id` and
     `reported_results_count == 2` (SB-submit plan §4.10).
  8. Assert `GET /v1/scores/{a.id}/results` has `len(body["results"]) == 2`, newest first,
     `reporter` values in order `["bruno", "ana"]` (the published local-part form), and two
     different `cache_version.id` values.
  **RED proof:** give Bruno's client the edge user `"ana@e2e.example"` (one user twice).
  Expected failure: step 8, the reporter assertion (`["ana", "ana"]`). **RED proof 2:** in the
  gateway extra env, set `AIGW_CACHE_VERSIONS_ENABLED` to `"false"`. Expected failure: step 2
  (`cache_version` is `None`, because the freeze gets `503 capture_disabled` (C2b), and the SDK
  submits with no receipt, SC-E1). Set it in `E14Env.gateway` after `e14_env` returns (a
  temporary edit of `e14_stack`), so the value of the WIRING hook is overridden.

- [ ] **Step 4 — RP-21 (H×H).** File `tests/e2e/test_e14_replay.py`,
  `test_submit_then_other_user_replays_all_hits_zero_cost_then_submit_labelled_replay`.
  1. Ana runs and submits (as Step 3.1). Keep `x = a.reported_result.id`.
  2. Bruno (`edge_client(e14, "bruno@e2e.example")`, not the owner): `report =
     client.evaluate(candidate, benchmark="ifeval", limit=50, replay=f"result:{x}",
     progress=False)`. The scoreboard signs the grant with `sub = "bruno@e2e.example"` (the
     verified email, D5). The engine forwards Bruno's email to the gateway, and the gateway
     checks the grant `sub` against it (C9). A non-owner replay needs the redistributable
     board (§4.3 step 5).
  3. Assert on `report.candidates.only.replay`: `result_id == x`,
     `cache_version_id == a.reported_result.cache_version.id`, `misses == 0`,
     `hits == a.reported_result.cache_version.call_count` (`hits` counts calls, and
     `call_count` counts the ledger rows of the original trace, `erd.md` §3.3; RP-H1 shows
     `hits: 420` for `c: 420`), and `coverage == "complete"`. Do NOT compare `hits` with
     `entry_count`: `entry_count` counts distinct `(key_hash, blob)` pairs, so it is smaller
     when a call repeats.
  4. Assert zero provider cost: `report.candidates.only.usage.cost_usd == Decimal("0")`.
     If `cost_usd` is `None`, **STOP** and report it (the RP-21 oracle is "$0", RP NFR); do not
     change the assertion. AIDEV-NOTE in the test: in this keyless stack a global-cache hit is
     also free, so the cost check alone is weak. The strong check is `misses == 0` (every call
     was served from the version).
  5. Bruno submits the replay result. Assert `reported_result.is_original is False` and it
     clusters under `a.id`.
  6. Assert the results-list item with `id == <Bruno's reported_result.id>` has
     `replay.replayed_from_result_id == x`, `replay.hits == <hits of step 3>`,
     `replay.misses == 0` (SC-D7; nested names from the SB-submit plan §4.3, confirmed in the
     §2 table).
  **RED proof:** in `E14Env.gateway`, replace `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS` with a map
  built from a **different** fresh pair (`nacl.signing.SigningKey.generate()`, same kid).
  Expected failure: the run fails with the typed `replay_grant_invalid` error (RP-E6), so
  step 2 raises. Record the error type in the ledger. **RED proof 2 (the subject check is
  live, D5):** get the grant as Bruno, but send the run with the engine-side edge user
  `"carol@e2e.example"` (a client with `http_transport=EdgeIdentityTransport("carol@e2e.example")`
  and `scoreboard_transport=EdgeIdentityTransport("bruno@e2e.example")`). Expected failure:
  step 2 raises the typed run error for a gateway `403` with reason `subject` (RP-5, RP-14
  path). Record it in the ledger.

- [ ] **Step 5 — MD-21 (M×H).** File `tests/e2e/test_e14_submit_edit.py`,
  `test_submit_then_edit_then_read_on_leaderboard`.
  0. The auth mode is real (D5). Ana runs with `edge_client(e14, "ana@e2e.example")`. Then
     submit that result through a plain `sf.Client(engine_url=..., scoreboard_url=...)` with
     **no** edge. Assert `LeaderboardError` with `status == 401` (no verified identity), and
     that an anonymous `GET /v1/leaderboard/ifeval` has no entry with this `url4_expression`
     (nothing was written).
  1. Ana submits the same result through her edge client with
     `paper_url="https://arxiv.org/abs/2609.01234"` and `authors=["ana@e2e.example"]`. Assert
     `metadata_revision == 1`, and the raw `GET /v1/scores/{id}` has `submitted_by == "ana"`.
  2. `client.leaderboards.update_submission(s.id, authors=["ana@e2e.example",
     "carol@z.example"], paper_url="https://doi.org/10.1234/abc", expected_revision=1)`.
     Assert the returned score has `paper_url == "https://doi.org/10.1234/abc"`,
     `metadata_revision == 2`, and `list(score.authors) == ["ana", "carol"]` (the SDK decodes the public JSON of the `PATCH` response, which is
     local-part only, `schemas.py:309-317`).
  3. Assert the raw `GET /v1/scores/{id}` JSON has `paper_url == "https://doi.org/10.1234/abc"`,
     `authors == ["ana", "carol"]` (public JSON is local-part only,
     `apps/scoreboard/src/scoreboard/scores/schemas.py:276-317`), and `metadata_revision == 2`.
  4. Assert the raw `GET /v1/leaderboard/ifeval` `entries` list has exactly one entry with
     `url4_expression == str(report.candidates.only.url4)`, with `authors == ["ana", "carol"]`
     and `paper_url == "https://doi.org/10.1234/abc"` (MD-D5). If the merged entry has no
     `paper_url` key, **STOP** and report it as an SB-meta gap against MD-D5 (see the §2 table
     and the spec gap). Do not drop the assertion.
  5. Assert `GET /v1/scores/{id}/metadata-history` has one event with `from_revision == 1`
     and `to_revision == 2`.
  **RED proof:** send `expected_revision=2`. Expected failure: step 2 raises the SDK error with
  `code == "metadata_revision_conflict"` (`412`). (This proves the test reaches the real
  `PATCH`. Do not use `0`: the SDK refuses it before any request, SDK-meta §4.3 step 2.)
  **RED proof 2 (the owner check uses the verified email, D5):** send the step 2 edit through
  `edge_client(e14, "bruno@e2e.example")`. Expected failure: step 2 raises
  `code == "not_submission_owner"` (`403`).

- **Step 6 — RP-22 feasibility probe. Dropped (Q30).** The owner decided (2026-09-30) that no
  paid run is used as a test. There is no probe and no fixture. The step number stays, so the
  other step numbers stay stable.

- **Step 7 — RP-22. Dropped (Q30).** No test is built. The behavior stays covered by RP-6 and
  RP-7 (pin by date), CV-17 and RP-13 (a miss falls through and is counted), and RP-21 (the E2E
  replay spine).

- [ ] **Step 8 — PB-22 (H×M, nightly).** File `tests/e2e/test_e14_publish_nightly.py`,
  `test_submit_publish_download_asset_digest_matches_version`. Marks: `pytest.mark.e2e` and
  `pytest.mark.e2e_github`.
  - Nightly only. The E2E replay lane (push and pull request) never runs it.
  - Gate (in the test, before the stack boots and before any Docker call):
    `SCREAMINGFACE_TEST_E2E_GITHUB == "1"`, and the scoreboard GitHub App variables (§2 table)
    plus `E14_SANDBOX_TOKEN` and `E14_SANDBOX_REPO` are set and non-blank. Else `pytest.skip`
    with the missing names (never their values). A missing secret is a clean skip, never an
    error and never a failure.
  - Boot `e14_stack(..., scoreboard_extra_env=<the GitHub App vars, target repo =
    E14_SANDBOX_REPO>)`.
  1. Ana (`edge_client(e14, "ana@e2e.example")`) runs and submits. Keep `x`,
     `vid = cache_version.id`, `sha = cache_version.sha256`.
  2. Ana: `client.leaderboards.publish_cache_version(result_id=x)`. Assert state `requested`.
     WHY Ana: the publish owner check uses the verified email (D5). In `disabled` mode publish
     answers 503, so this spine needs `cloudflare_headers`.
  3. Poll `GET /v1/scores/{head}/results` every 2 s, deadline 300 s (the PB NFR: ≤ 5 min p95),
     until the item's `publication_state == "published"`. Fail at the deadline with the last
     state and `last_error`.
  4. With `E14_SANDBOX_TOKEN`: `GET https://api.github.com/repos/{E14_SANDBOX_REPO}/releases/tags/cv-{vid}`.
     Assert it exists and has exactly the assets `entries.jsonl.gz` and `manifest.json`.
  5. Download both assets (`Accept: application/octet-stream`). Assert
     `sha256(<entries.jsonl.gz bytes>).hexdigest() == sha` (Decided: D7 X-16: `archive_sha256`
     is the sha256 of the gzip bytes), `manifest["version_id"] == vid`, and
     `manifest["entries_sha256"]` equals the digest of the preimage recorded in the §2 table.
  6. Assert the two local archive files of `vid` (under `archive_dir`, at the layout recorded
     in the §2 table) are byte-identical to the two downloaded assets (`erd.md` §3.5, PB-H3
     "The asset bytes equal the bucket archive").
  7. `finally`: delete the release and the tag `cv-{vid}` with `E14_SANDBOX_TOKEN`
     (`DELETE /repos/{r}/releases/{id}`, `DELETE /repos/{r}/git/refs/tags/cv-{vid}`). Ignore
     `404`. This keeps the sandbox repo clean.
  **RED proof:** set the scoreboard target repo variable to a repo the App cannot write.
  Expected failure: step 3 times out with state `requested` or `failed`.

- [ ] **Step 9 — CI wiring.**
  1. `pyproject.toml`: add marker
     `"e2e_github: nightly E14 publish spine against a sandbox GitHub repo (secrets + docker)"`.
  2. `screamingface-e2e-replay.yml`: add `"apps/scoreboard/**"` to the `push` and
     `pull_request` `paths:` lists; set `timeout-minutes: 60`. WHY: the E14 spines break when
     the scoreboard changes, and they add three stack boots (each with two Postgres
     containers) and five 50-case runs (SC-23 2, RP-21 2, MD-21 1). With D1 there is
     no unit PR: the lane runs on the push of the e14 branch after the wave-5 integration, and
     the integrator also runs it locally (§8). The existing
     `pytest tests/e2e -rs -v` step runs MD-21, SC-23, RP-21. PB-22 skips there (no
     `SCREAMINGFACE_TEST_E2E_GITHUB`).
  3. Create `screamingface-e14-publish-nightly.yml`:
     - `on: schedule: - cron: "17 3 * * *"` and `workflow_dispatch`.
     - `permissions: contents: read`.
     - One job, `timeout-minutes: 60`, `working-directory: packages/screamingface`.
     - Steps: checkout, setup-uv (as the replay workflow), `uv sync`, the asset cache and
       `screamingface prepare` steps, the synthetic fixture step (copy the replay workflow
       steps verbatim), then a "Check the sandbox secrets" step (`id: sandbox`; copy the header
       comment shape of `screamingface-paid-inspect-smoke.yml`). It writes
       `present=true|false` to `$GITHUB_OUTPUT` and, when false, a `::notice::` that names the
       missing secrets (never values). Every later step has
       `if: steps.sandbox.outputs.present == 'true'`, so a run with no secrets ends green and
       skipped, not red. Then `actions/create-github-app-token@v2`
       with `app-id: ${{ secrets.E14_SANDBOX_APP_ID }}`,
       `private-key: ${{ secrets.E14_SANDBOX_APP_PRIVATE_KEY }}`, `repositories:` the sandbox
       repo name, to mint `E14_SANDBOX_TOKEN`.
     - Test step: `uv run pytest tests/e2e/test_e14_publish_nightly.py -rs -v -m e2e_github`
       with `SCREAMINGFACE_TEST_E2E: "1"`, `SCREAMINGFACE_TEST_E2E_GITHUB: "1"`,
       `SCREAMINGFACE_E2E_ASSETS`, `E14_SANDBOX_REPO: ${{ vars.E14_SANDBOX_REPO }}`,
       `E14_SANDBOX_TOKEN: ${{ steps.<id>.outputs.token }}`, and the scoreboard App variables
       mapped from the same secrets.
  4. README: add an "E14 spines" section: what the four tests prove, how to run them
     (`SCREAMINGFACE_TEST_E2E=1 uv run pytest tests/e2e -k e14 -rs`), and the nightly secrets.

## 7. Edge cases and what not to do

- **Zero spend.** Never add a provider key to any child env. The `_API_KEY` guard (§4.5)
  enforces it. A `profile_not_found` in a report means a cache miss: that is a fixture
  problem, not a flake. Classify it; do not retry.
- **No cross-app imports.** The test process imports `screamingface` (including the two SDK
  local-runtime env builders of §4.1) and the harness only.
  Never import `aigateway`, `scoreboard`, `screamingface_engine` or `url4` internals into a
  test. (The layering rules of `contracts.md` C11 apply to product code; the harness keeps the
  same spirit by talking HTTP.)
- **No shared database.** Each service has its own Postgres container (`erd.md` "No service
  reads the database of another service").
- **Credentials.** The E2E stack creates no AIGateway credential. Do not add one. Never set
  or log `AIGATEWAY_SECRET_KEY`. No OS keychain.
- **Secrets in logs.** Never print a private key, the App private key or a token. Skip
  messages name missing variables, never values.
- **Test independence.** Each test boots its own stack (the function-scoped `e14` fixture,
  §4.6) and submits its own runs. Still filter the leaderboard by `url4_expression`, never by
  a global entry count.
- **Identity (D5).** The scoreboard and the gateway run `cloudflare_headers`. Every identity is
  the `X-User-Email` that `EdgeIdentityTransport` sets, from the allowed loopback network. Give
  each SDK client the edge on both transports (`edge_client`), so the engine forwards the same
  email to the gateway. Never put `submitted_by` in a body. Never run an E14 spine in
  `disabled` mode (it is a dev/local fallback: content-hash clustering, grant `sub`
  `"anonymous"`, publish 503).
- **Peer trust.** Keep `FORWARDED_ALLOW_IPS` at `192.0.2.1` for both services. Never set it to
  `*` or to a loopback value: the scoreboard refuses to start, and a `*` would let a forged
  `X-Forwarded-For` pass the peer check.
- **Grant life (D4).** The grant lives 12 h. E2E runs take minutes. Do not add a test that
  waits for an expiry; SDK-replay row 25 and ENG-replay RP-14 cover the expiry path.
- **Do not** add a sleep between submits. Do not build a pin-by-date E2E test (RP-22 is dropped, Q30).
- **Do not** weaken an assertion to fit the result. If an assertion fails, classify it
  (product defect, test defect, environment, flake). Report a product defect to the
  orchestrator with the owning unit id (D1: the fix goes on that unit's branch or on the e14
  branch). Do not fix it here.
- **Do not** change `src/`. If the SDK lacks a method this plan names, **STOP**.

## 8. Verification

Commands (from `packages/screamingface`, Docker running, assets prepared):

```sh
uv run --extra runtime screamingface prepare ifeval --data-dir /tmp/screamingface-data
(cd ../../apps/aigateway && uv sync && .venv/bin/python ../../packages/screamingface/tests/e2e/fixtures/generate_synthetic.py)
SCREAMINGFACE_TEST_E2E=1 SCREAMINGFACE_E2E_ASSETS=/tmp/screamingface-data/benchmark-assets \
  uv run pytest tests/e2e -k "e14" -rs -v
uv run pytest tests/e2e/test_e14_harness_contracts.py -v          # no Docker needed
uv run pytest -q                                                   # the whole SDK suite: e14 stack tests SKIP, never error
uv run .claude/scripts/run_gates.py screamingface --base e14-reproducible-submission-spec   # from the repo root
```

PB-22 locally (only with sandbox access):

```sh
SCREAMINGFACE_TEST_E2E=1 SCREAMINGFACE_TEST_E2E_GITHUB=1 E14_SANDBOX_REPO=<owner/repo> \
  E14_SANDBOX_TOKEN=<token> <scoreboard App vars> \
  uv run pytest tests/e2e/test_e14_publish_nightly.py -m e2e_github -rs -v
```

**Done when:**

1. MD-21, SC-23 and RP-21 pass locally on `unit/E2E`. (RP-22 is dropped, Q30.)
2. **As built:** after the integrator merges WIRING and then E2E into the e14 branch, the
   stack tests pass again on the e14 branch, and the Step 1.2 tests of the direct hook import
   pass (there is no `env_source` and no fallback). Result on the e14 branch (2026-09-30):
   docker E2E lane 15 passed, 1 skipped (PB-22: nightly only),
   no paid calls. The `ScreamingFace E2E Replay` workflow is green on the push of the e14 branch.
3. PB-22 skips cleanly with no secrets (local and nightly), and passes once through
   `workflow_dispatch` of the nightly workflow after OD-5 is done. Its release is deleted
   after.
4. Each test has its RED proofs recorded in the ledger (mutation, the failing assertion, then
   the revert).
5. Without `SCREAMINGFACE_TEST_E2E=1`, all new stack tests skip with a reason; the harness
   self-tests pass; the `screamingface` gates are green.
6. No file under `src/` or `apps/` changed
   (`git diff --stat e14-reproducible-submission-spec -- packages/screamingface/src apps` is
   empty on `unit/E2E`).
7. Conventional commits on `unit/E2E`, no `Co-Authored-By`. Do not open a PR. Tell the
   integrator that the unit branch is ready, and that WIRING must merge first (D1, D2).

## 9. Open decisions

Still open (they need the owner; they do not block Steps 0 to 5):

- ~~**OD-4 — RP-22 fixture.**~~ **Dropped (owner, 2026-09-30, Q30).** The owner said: "We will
  not use a paid run as a test." RP-22 is dropped. It is not deferred, and no fixture is
  planned.
- **OD-5 — Nightly GitHub sandbox.** Somebody must create the sandbox repo and a GitHub App
  installed only on it, and add the secrets `E14_SANDBOX_APP_ID`,
  `E14_SANDBOX_APP_PRIVATE_KEY` and the variable `E14_SANDBOX_REPO`. Until then PB-22 skips
  cleanly (Step 8, Step 9.3). The scoreboard-side variable names come from SB-publish and the
  WIRING chart.

Decided:

- **OD-1 — the E2E harness vs a literal `screamingface up`.** Decided (default): use the OME-961
  harness plus the SDK local-runtime env builders (SDK-replay keys, WIRING flags and archive
  dir, §4.1). A literal `up` cannot give a zero-spend run: it hard-wires sqlite and refuses
  `AIGATEWAY_DATABASE_URL` (`packages/screamingface/src/screamingface/_runtime/cli.py:253-268`),
  and the snapshot seed needs Postgres COPY (`harness/cache_seeded.py:1-29`). The env is the
  same code as `up`, so a wrong key or flag still fails E2E.
- **OD-2 — two users on a local stack.** Decided: D5. The scoreboard and the gateway run
  `cloudflare_headers`, and the test edge sets `X-User-Email` per user from an allowed network
  (§4.2). The `submitted_by` test transport is gone.
- **OD-3 — how a board becomes `redistributable`.** Decided: D6. The WIRING admin route sets
  it (§4.3 step 5). As built: the route is always called; SQL sets only `case_count`.
- **OD-6 — PB-E6 "local mode" and the publish owner check.** Decided: D5. E2E runs
  `cloudflare_headers`, so publish is allowed when the App is configured, and the owner check
  uses the verified email. In `disabled` mode publish answers 503; E2E does not use it.
- **OD-7 — A3 is false.** Decided: D4. Keep the 12 h grant. A grant that expires mid-run fails
  the run with the typed error (RP-14 path). A3 is "[checked] false, accepted". No E2E change.
- **OD-8 — `archive_sha256` preimage.** Decided: D7 (X-16). The sha256 of the gzip bytes of
  `entries.jsonl.gz` (mtime 0, level 9). PB-22 step 5 asserts it.
- **OD-9 — local-mode E14 key, flag and archive wiring in `screamingface up`.** Decided: D6.
  SDK-replay (RP-20) owns the keys; WIRING owns the flags and the archive dir. E2E uses both.
