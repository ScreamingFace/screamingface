# WIRING — Plan: deploy charts, admin `redistributable` route, key helper, local runtime (E14, OME-1307)

- **Epic:** OME-1307 (E14).
- **Spec (the rubric):** `docs/spec/2026-09-29-e14-reproducible-submission/` — `prd/cache-version-store.md` §4 "Security" (the WIRING row), `prd/publish-and-takedown.md` PB-D7, PB-D8, `prd/replay-pinned-run.md` RP-H2, `contracts.md` C3, C6, C8 "Local mode", `erd.md` §2.3 (`Benchmark.redistributable`), §3.5. User decisions D4, D5, D6, D7 (00-index.md).
- **Plan:** this file, `docs/plan/2026-09-29-e14-reproducible-submission/WIRING.md`. **Ledger:** `docs/work/2026-09-29-e14-wiring.md` (`ticket: unfiled`). Start it before the first RED.
- **Delivery (D1):** build this unit in its own temporary worktree on the branch `unit/WIRING`, made from the HEAD of `e14-reproducible-submission-spec` after the wave-4 integration (`git checkout -B unit/WIRING e14-reproducible-submission-spec`). Commit on `unit/WIRING` only. Do not open a PR. Do not file a Linear issue. After wave 5, the integrator merges `unit/WIRING` FIRST and `unit/E2E` second into the e14 branch, and runs the gates.
- **Components:** `apps/scoreboard` (one route, one audit change, the chart, `DEPLOYMENT.md`), `apps/aigateway` (the chart and `DEPLOYMENT.md` only, no Python), `packages/screamingface` (`_runtime/` only), `.github/` (`charts.yml`, `release-scoreboard.yml`, `scripts/verify_chart_wiring.py`).
- **Wave:** 5 (D2), in parallel with E2E. **Size:** 3–4 d. **Implementer:** Sonnet, `sdlc-python` loop. Do the task groups of §6 in order. Commit after each group is green.

## Global constraints

- Stacks and gates: `scoreboard` and `screamingface` through `run_gates.py` (§7.3). The charts have no stack card; their gate is `python3 .github/scripts/verify_chart_wiring.py` plus `helm lint` (§7.3).
- Scoreboard code rules: the same as `SB-publish.md` "Global constraints" (ruff `max-returns = 3`, `max-branches = 7`, `max-statements = 26`, `max-complexity = 8`; `asyncio_mode = "strict"`; files ≤ 450 lines for new files; no import from another app; never import `screamingface`).
- **Append-only tests.** Add new test files only. Do not change an existing test. `.github/scripts/verify_chart_wiring.py` is not a test file: add a new block to it (§4.7), and do not change its old checks.
- Comment anchors: `WHY:`, `INVARIANT:`, `AIDEV-NOTE:`, `FEATURE:`, `STORY:` only.
- Conventional commits on `unit/WIRING` (`feat(scoreboard): …`, `feat(charts): …`, `feat(sdk): …`, `ci(charts): …`). No `Refs:` line. No `Co-Authored-By`.
- **Identity (D5).** Production runs `cloudflare_headers` on the gateway (today) and on the scoreboard (this unit switches `values-prod.yaml`). The admin route works only in `cloudflare_headers`. `disabled` is the dev/local fallback: the admin route answers 503 there (the SB-publish `require_admin` rule).
- **Key material never enters git.** No private key, App key or bucket secret in a values file, a test fixture that is committed as a real key, a log line, an exception text or stdout. Public keys and key ids are not secret, but this unit still commits no real one (§9 checklist adds them at install time).
- AIGateway credentials stay only in `credential_blobs` (AES-256-GCM). This unit adds no AIGateway credential. `AIGATEWAY_SECRET_KEY` is not touched. No OS keychain.
- No real network in any test. No `helm` call in a Python test.

## 1. Scope

### 1.1 What this unit owns

| Part | Test ids (plan-local; no PRD id) |
|---|---|
| Admin route `PUT /v1/admin/benchmarks/{benchmark_id}/redistributable` (D6, audited) | WR-1 … WR-9 |
| Ed25519 key helper for operators (raw base64, derived kid) | KG-1 … KG-7 |
| Local runtime `screamingface up`: E14 flags on, archive dir, keys wired | LR-1 … LR-6 |
| Scoreboard chart (auth mode, allowed networks, `FORWARDED_ALLOW_IPS` guard, NetworkPolicy peers, receipt public keys, grant key, admin allowlist, GitHub App, bucket read creds, flags) and `values-prod.yaml` switch to `cloudflare_headers` (D5) | CH-1 … CH-8 |
| Aigateway chart (`AIGW_CACHE_VERSIONS_ENABLED`, receipt key Secret, grant public keys, bucket write creds, archive bucket and prefix, Garage reader peers) | CH-9 … CH-14 |
| `charts.yml`, `release-scoreboard.yml` render lanes, `verify_chart_wiring.py` coverage | CH-7, CH-15 |

PRD ids: none. Every PRD id has an owner in another unit (00-index.md §2). This unit closes the old index items X-12 (flags off by default), X-13 (nothing writes `redistributable`), X-14 (deploy wiring) and the E2E OD-9 (receipt keypair and archive dir in `screamingface up`).

### 1.2 Out of scope

- The settings classes. GW-capture, GW-freeze, GW-replay, SB-submit, SB-grants and SB-publish added every setting that this unit feeds. This unit adds no setting.
- The engine chart and engine settings. ENG-freeze and ENG-replay add no setting (`ENG-freeze.md` §1: the route uses the existing `aigateway_base_url`). No file under `apps/screamingface-engine/` changes.
- An Envoy `HTTPRoute`, a Cloudflare Access application, or DNS for the scoreboard host. That is the D5 ops precondition (§9 item 1), not code.
- The Garage bucket, the Garage keys and the GitHub App themselves. They are ops steps (§9). The chart only consumes them.
- The local signing keys of `screamingface up`. SDK-replay (RP-20) owns `_runtime/signing_keys.py` and its call in `server.run()`. This unit reuses that generator (§4.4) and adds the flags and the archive dir next to it.
- A public `redistributable` field on `GET /v1/benchmarks` (OD-W7).
- A banner line for the new flags in `screamingface up` (it would change `_gateway_config_summary`, and `tests/test_runtime_cli.py:901-916` asserts its exact dict).
- E2E tests (unit E2E, same wave).

## 2. Depends on

- **Code dependencies (real), all merged on the e14 branch HEAD before this unit starts:**
  - SB-schema (`Benchmark.redistributable`, `SB-schema.md` §4, line `redistributable = fields.BooleanField(default=False, db_default=False)`).
  - SB-submit (`clustering_enabled`, `receipt_public_keys`, `routes/errors.py::coded_error`; `SB-submit.md` §4.1, §4.2 error map).
  - SB-grants (`replay_grant_signing_key`, `replay_grant_signing_kid`; `SB-grants.md` §4.1).
  - SB-publish (`admin_emails`, `github_*`, `public_base_url`, `archive_*`, `publish_*`; `routes/admin.py::require_admin`, `AdminAuditRoute`, `_audit`; the `tests/unit/publish/conftest.py` fixtures; `SB-publish.md` §4.1, §4.10, §6).
  - GW-capture (`AIGW_CACHE_VERSIONS_ENABLED`, `GW-capture.md` §4.1), GW-freeze (`AIGATEWAY_RECEIPT_SIGNING_KEY`, `AIGW_CACHE_VERSION_*`, `GW-freeze.md` §4.1), GW-replay (`AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS`, `GW-replay.md` §4.1).
  - SDK-replay (`screamingface._runtime.signing_keys`: `LocalKeyPair`, `ensure_local_signing_keys`, `apply_local_signing_environment`, and its call in `server.run()`; `SDK-replay.md` §4.12).
  - The other W1–W4 units (URL4-fp, SB-meta, SB-registry, ENG-freeze, ENG-replay, SDK-meta, SDK-submit) are not code dependencies of this unit, but they are on the branch.
- **Contracts consumed:** C3 and C6 key forms (Decided: D7 X-4: standard base64 of the raw 32-byte key, JSON `{kid: b64}` public maps, receipt kid `sha256(raw public key).hexdigest()[:16]`, grant kid from `SCOREBOARD_REPLAY_GRANT_SIGNING_KID`). C8 "Local mode" (one filesystem directory: the gateway writer root and the scoreboard reader root are the same). C10 admin rules (PRD §4 "works only in the verified auth mode").
- **Contracts implemented:** none new. The admin route is a new scoreboard surface (D6); it uses the C10 admin rules and the X-8 coded error body.

**Before RED (Step 0):** read the merged settings classes and write each variable of the §4.8 table in the ledger with its `file:line`. Read the merged `routes/admin.py` and write the signatures of `require_admin`, `AdminAuditRoute`, `_audit` and the name of the `request.state` reason attribute. Read the merged `_runtime/signing_keys.py` and write its function names and the five env names. If a name, a form or a signature differs from this plan, **STOP** and ask.

### 2.1 Integration notes (D2)

- Same-wave unit: **E2E**. Merge order: WIRING first, then E2E. Expected shared files: none. E2E changes only `packages/screamingface/tests/e2e/**`, `packages/screamingface/pyproject.toml` (one marker), `packages/screamingface/tests/e2e/README.md` and `.github/workflows/screamingface-e2e-replay.yml`. This unit changes none of them. If the integrator sees an overlap, both changes are additive: keep both.
- E2E reads these names from this plan (E2E §2.1, §4.1, §4.3). They are fixed; do not rename them:

| Name E2E needs | Value |
|---|---|
| Hook module | `screamingface._runtime.local_features` |
| Hook function | `apply_local_e14_environment` |
| Hook signature | `(environment: MutableMapping[str, str], data_dir: Path) -> None` |
| Flags the hook sets | `LOCAL_E14_FLAGS` = `{"AIGW_CACHE_VERSIONS_ENABLED": "true", "SCOREBOARD_CLUSTERING_ENABLED": "true"}` (the only two off-by-default E14 flags; SB-publish `publish_worker_enabled` defaults to True, SB-grants has no flag) |
| Archive-dir variables | gateway writer `AIGW_CACHE_VERSION_ARCHIVE_DIR` (with `AIGW_CACHE_VERSION_ARCHIVE_BACKEND=filesystem`); scoreboard reader `SCOREBOARD_ARCHIVE_FS_ROOT` (with `SCOREBOARD_ARCHIVE_BACKEND=filesystem`). Both = `str(data_dir / "cache-version-archive")`. |
| Admin route | `PUT /v1/admin/benchmarks/{benchmark_id}/redistributable`, body `{"redistributable": true, "reason": "<text>"}`, 2xx = `200` |
| Admin allowlist variable | `SCOREBOARD_ADMIN_EMAILS` (comma list; SB-publish §4.1) |

- This unit changes three files that earlier waves made. Each change is small and additive:
  - `apps/scoreboard/src/scoreboard/routes/admin.py` (SB-publish): the audit line names the target (§4.2). The withdraw audit line keeps `result_id=<id>` unchanged.
  - `packages/screamingface/src/screamingface/_runtime/signing_keys.py` (SDK-replay): extract `generate_key_pair` and `derive_kid`, and name the five env constants (§4.4). No behavior change; the RP-20 tests stay green.
  - `packages/screamingface/src/screamingface/_runtime/server.py` (SDK-replay changed `run()`): one call after the key call (§4.5).
- `apps/scoreboard/DEPLOYMENT.md` and `apps/aigateway/DEPLOYMENT.md` already have E14 sections from W2–W4 units. Add one new section at the END of each (§3). Do not edit their sections.

## 3. Files

| C/M | Path | What | Exemplar |
|---|---|---|---|
| C | `apps/scoreboard/src/scoreboard/routes/admin_benchmarks.py` | The route (§4.1). | withdraw route: `routes/admin.py` (SB-publish §4.2, §4.10); visibility setter `scores/store.py:790-798` |
| M | `apps/scoreboard/src/scoreboard/routes/admin.py` | `_audit` names the target and an optional change (§4.2). | the file itself; gateway `apps/aigateway/src/aigateway/routes/admin.py:54-97` |
| M | `apps/scoreboard/src/scoreboard/scores/store.py` | `ScoreStore.set_redistributable` (§4.3), placed right after `set_visibility`. | `store.py:790-798` |
| M | `apps/scoreboard/src/scoreboard/scores/schemas.py` | `RedistributableRequest`, `RedistributableResponse` (§4.1). Append at the END of the file. | `WithdrawRequest` (SB-publish §4.2) |
| M | `apps/scoreboard/src/scoreboard/main.py` | `app.include_router(admin_benchmarks.router)` directly after the SB-publish admin router, and BEFORE `register_portal(app, settings)` (the portal is the catch-all, so a router after it can be shadowed). | `main.py:192-195` |
| M | `apps/scoreboard/DEPLOYMENT.md` | New section "E14 deploy wiring" (§4.9). | — |
| C | `apps/scoreboard/tests/unit/publish/test_admin_redistributable.py` | WR-1 … WR-9. In the `publish/` directory to reuse its `conftest.py` fixtures. | `tests/unit/publish/test_withdraw.py` (SB-publish) |
| M | `apps/scoreboard/charts/scoreboard/values.yaml` | New keys (§4.6.1). | `apps/aigateway/charts/aigateway/values.yaml:79-91` (admin list comment), `:303-311` (storage block) |
| M | `apps/scoreboard/charts/scoreboard/values-prod.yaml` | D5 switch and E14 posture (§4.6.2). | `apps/aigateway/charts/aigateway/values-prod.yaml:14-24` |
| M | `apps/scoreboard/charts/scoreboard/templates/_helpers.tpl` | `scoreboard.validateAuth`, `scoreboard.validateE14`, `scoreboard.e14SecretName`, `scoreboard.e14InlineSecret`, `scoreboard.e14HasSecret`. | `apps/aigateway/charts/aigateway/templates/_helpers.tpl:50-61`, `:139-146`, `:154-175` |
| M | `apps/scoreboard/charts/scoreboard/templates/configmap.yaml` | Include the two validators; new keys (§4.6.3). | `apps/aigateway/charts/aigateway/templates/configmap.yaml:1-3, 21-43` |
| C | `apps/scoreboard/charts/scoreboard/templates/secret-e14.yaml` | Dev-only inline Secret (§4.6.4). | `apps/aigateway/charts/aigateway/templates/secret-tracing.yaml` |
| M | `apps/scoreboard/charts/scoreboard/templates/deployment.yaml` | `checksum/config` annotation; `envFrom.secretRef` to the E14 Secret. | `apps/aigateway/charts/aigateway/templates/deployment.yaml:30-38, 60-75` |
| M | `apps/scoreboard/charts/scoreboard/templates/networkpolicy.yaml` | Paired namespace+pod peers; fail on no peers in `cloudflare_headers` (§4.6.5). | `apps/aigateway/charts/aigateway/templates/networkpolicy.yaml:20-35` |
| M | `apps/scoreboard/charts/scoreboard/README.md` | A short "E14 values" section that points to `DEPLOYMENT.md`. | — |
| M | `apps/aigateway/charts/aigateway/values.yaml` | `config.cacheVersions` block (§4.7.1). | `values.yaml:269-311` (`snapshot`) |
| M | `apps/aigateway/charts/aigateway/values-prod.yaml` | `config.cacheVersions` prod posture (§4.7.2). | the file |
| M | `apps/aigateway/charts/aigateway/templates/_helpers.tpl` | `aigateway.validateCacheVersions`, `aigateway.cacheVersionsEndpoint`, `aigateway.cacheVersionsSecretName`, `aigateway.cacheVersionsInlineSecret`. | `_helpers.tpl:133-146` (`validateSnapshot`, `snapshotEndpoint`), `tracingHasSecret` (the "true"-or-empty helper form) |
| M | `apps/aigateway/charts/aigateway/templates/configmap.yaml` | Include the validator; new keys (§4.7.3). | `configmap.yaml:44-54` |
| C | `apps/aigateway/charts/aigateway/templates/secret-cache-versions.yaml` | Dev-only inline Secret (§4.7.4). | `secret-tracing.yaml` |
| M | `apps/aigateway/charts/aigateway/templates/deployment.yaml` | `envFrom.secretRef` when `cacheVersions.enabled`. | `deployment.yaml:70-75` |
| M | `apps/aigateway/charts/aigateway/templates/garage.yaml` | Append `config.cacheVersions.archive.readerPeers` to the Garage ingress `from` (§4.7.5). | `garage.yaml:183-190` |
| M | `apps/aigateway/charts/aigateway/README.md` | A short "Cache versions (E14)" values section. | — |
| M | `apps/aigateway/DEPLOYMENT.md` | New section "E14 deploy wiring" (§4.9). | — |
| M | `.github/scripts/verify_chart_wiring.py` | New E14 block before the summary print (§4.8). | `verify_chart_wiring.py:99-150` (render helpers), `:177-197` (`settings_fields`), `:302-331` (`cidr_overlap`), `:1306-1324` (`cloud_render_flags`) |
| M | `.github/workflows/charts.yml` | Paths, lint lines, a scoreboard prod render step (§4.8.3). | `charts.yml:14-66, 91-139` |
| M | `.github/workflows/release-scoreboard.yml` | The prod render gets the same placeholders (§4.8.3). | `release-scoreboard.yml:78-89` (job `chart`, step `Lint and render charts`; the prod render is the last `helm template` of that step) |
| C | `packages/screamingface/src/screamingface/_runtime/local_features.py` | The local E14 hook (§4.5). | `_runtime/bootstrap.py:22-45` (setdefault defaults) |
| C | `packages/screamingface/src/screamingface/_runtime/keygen.py` | The operator key helper (§4.4). | `_runtime/cli.py:762-775` (0600 exclusive write) |
| M | `packages/screamingface/src/screamingface/_runtime/signing_keys.py` | Extract `generate_key_pair`, `derive_kid`; env name constants (§4.4). | the file (SDK-replay §4.12) |
| M | `packages/screamingface/src/screamingface/_runtime/server.py` | Call `apply_local_e14_environment` in `run()` (§4.5). | `server.py:166-180` |
| C | `packages/screamingface/tests/test_runtime_keygen.py` | KG-1 … KG-7. | `tests/test_runtime_signing_keys.py` (SDK-replay) |
| C | `packages/screamingface/tests/test_runtime_local_features.py` | LR-1 … LR-6. | `tests/test_runtime_signing_keys.py::test_rp20_up_sets_the_keys_before_the_apps_are_built` (SDK-replay row 20) |
| C | `docs/work/2026-09-29-e14-wiring.md` | Work ledger. | any file in `docs/work/` |

No migration. No change under `apps/screamingface-engine/`. No change to any settings class.

## 4. Signatures and data shapes

### 4.1 Admin route (`routes/admin_benchmarks.py`)

```python
# schemas.py (append at the END)
class RedistributableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    redistributable: StrictBool
    reason: Annotated[str, Field(min_length=1, max_length=512)]

class RedistributableResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    benchmark_id: str
    redistributable: bool
    changed: bool
```

```python
# routes/admin_benchmarks.py
router = APIRouter(
    prefix="/v1/admin/benchmarks",
    tags=["Admin"],
    route_class=AdminAuditRoute,              # from scoreboard.routes.admin (SB-publish)
    dependencies=[Depends(require_admin)],    # from scoreboard.routes.admin (SB-publish)
)

@router.put("/{benchmark_id}/redistributable", response_model=RedistributableResponse)
async def set_benchmark_redistributable(
    benchmark_id: Annotated[str, Path(min_length=1, max_length=64)],
    body: RedistributableRequest,
    request: Request,
) -> RedistributableResponse
```

```
PUT /v1/admin/benchmarks/{benchmark_id}/redistributable   {"redistributable": true, "reason": "license: CC-BY-4.0"}
200 {"benchmark_id": "...", "redistributable": true, "changed": true}    the value changed
200 {"benchmark_id": "...", "redistributable": true, "changed": false}   the same value again (idempotent)
401 {"detail": {"code": "identity_not_verified", ...}}                    no X-User-Email (require_admin)
403 {"detail": {"code": "admin_required", ...}}                           not on SCOREBOARD_ADMIN_EMAILS
403 {"detail": "<UNTRUSTED_PEER_DETAIL>"}                                 untrusted peer (require_admin)
404 {"detail": {"code": "benchmark_not_found", "message": "benchmark not found"}}
422 validation error (missing reason, extra field, non-bool value)
503 {"detail": {"code": "admin_unavailable", ...}}                        empty allowlist, or auth_mode disabled (D5 fallback)
```

Handler steps (each one small function; the order is fixed):
1. `require_admin` ran first (router dependency). It set `request.state.admin_actor`.
2. Set the audit fields: `request.state.admin_reason = body.reason` and `request.state.admin_change = f"redistributable={'true' if body.redistributable else 'false'}"`. WHY before the store call: a 404 must also log the reason and the change.
3. `result = await request.app.state.score_store.set_redistributable(benchmark_id, body.redistributable)`.
4. `result is None` → `raise coded_error(404, "benchmark_not_found", "benchmark not found")` (`routes/errors.py`, SB-submit).
5. Return `RedistributableResponse(benchmark_id=benchmark_id, redistributable=body.redistributable, changed=result)`.

WHY `PUT` with the value in the body, and not `POST …/redistribute`: the call sets a state. The same call twice gives the same state (idempotent), and the admin can also set it back to `false`.
WHY `StrictBool`: the string `"yes"` or the number `1` must be a 422, not a silent `true` (a licence decision).

Imports in `admin_benchmarks.py`: `from fastapi import APIRouter, Depends, Path, Request` (FastAPI `Path`, not `pathlib.Path`); `from .admin import AdminAuditRoute, require_admin`; `from .errors import coded_error`; `from ..scores.schemas import RedistributableRequest, RedistributableResponse`. The handler reads the store from `request.app.state.score_store` (`main.py`, `create_app`), the same as the other routes.

INVARIANT: this route changes one column of a row that exists. It never creates a benchmark (the same rule as `set_visibility`, `store.py:790-798`, OME-904).

### 4.2 Audit change (`routes/admin.py`, SB-publish file)

The SB-publish audit line is `admin_action actor=<actor> result_id=<id> reason=<reason> outcome=<status>` and reads `request.path_params["result_id"]`. A benchmark route has no `result_id`, so the line must name the target. Change `_audit` only:

```python
def _audit_target(path_params: Mapping[str, str]) -> str:
    """'result_id=<id>' or 'benchmark_id=<id>'; '<none>' when neither is there."""
```

- The line becomes `admin_action actor=<actor> <target> reason=<reason> outcome=<status>`, then ` change=<change>` at the end when `request.state.admin_change` is set. For the withdraw route the line is byte-for-byte the SB-publish line (it sets no `admin_change`).
- The reason: read `request.state.admin_reason`. If the merged SB-publish handler sets `request.state.withdraw_reason`, change that handler to set `admin_reason` instead, and read `withdraw_reason` as a fallback only if a test under `tests/` names it (`git grep -n withdraw_reason -- apps/scoreboard/tests`). Keep the SB-publish rules: escape the reason with `escape_markdown`, cut it to 120 chars; `<none>` when absent.
- Do not change `require_admin`. Do not change the withdraw route.

### 4.3 Store (`scores/store.py`)

```python
async def set_redistributable(self, benchmark_id: str, value: bool) -> bool | None:
    """Set an EXISTING benchmark's redistributable flag, touching nothing else.
    None: no such benchmark. True: the value changed. False: it already had the value.
    FEATURE: OME-1307 (E14) D6 — the audited admin route is the only writer."""
```

- Steps: `row = await Benchmark.get_or_none(id=benchmark_id)` → `None` → return `None`; `row.redistributable == value` → return `False`; else `await Benchmark.filter(id=benchmark_id).update(redistributable=value)` → return `True`. No row lock: two admins who write at the same time each get an audited answer, and the last write wins (§7.1).
- `register_benchmark` (`store.py:747-777`) does NOT write `redistributable`. Do not add it to its `defaults`. WHY: the seed job runs on every deploy (`job-seed-benchmarks.yaml`), and it must not reset an admin decision (WR-8).

### 4.4 Key helper (`_runtime/keygen.py`, and `_runtime/signing_keys.py`)

Changes in `signing_keys.py` (SDK-replay file; no behavior change):

```python
RECEIPT_SIGNING_KEY_ENV: Final = "AIGATEWAY_RECEIPT_SIGNING_KEY"
RECEIPT_PUBLIC_KEYS_ENV: Final = "SCOREBOARD_RECEIPT_PUBLIC_KEYS"
GRANT_SIGNING_KEY_ENV: Final = "SCOREBOARD_REPLAY_GRANT_SIGNING_KEY"
GRANT_SIGNING_KID_ENV: Final = "SCOREBOARD_REPLAY_GRANT_SIGNING_KID"
GRANT_PUBLIC_KEYS_ENV: Final = "AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS"

KeyPurpose = Literal["receipt", "replay_grant"]

def derive_kid(public_raw: bytes, *, prefix: str = "") -> str:
    """prefix + sha256(public_raw).hexdigest()[:16]  (GW-freeze OD-F2, D7 X-4)."""

def generate_key_pair(purpose: KeyPurpose, *, kid_prefix: str = "", seed: bytes | None = None) -> LocalKeyPair:
    """seed None -> nacl.signing.SigningKey.generate(); else SigningKey(seed) (32 bytes, else ValueError).
    purpose "receipt" with a non-empty kid_prefix -> ValueError("a receipt kid is derived and takes no prefix").
    private_key = b64encode(seed), public_key = b64encode(bytes(verify_key)), kid = derive_kid(public_raw, prefix=kid_prefix)."""
```

- If the merged file already has these as private names, rename them to the public names above and keep a private alias only if a test imports the old name. `ensure_local_signing_keys` calls `generate_key_pair("receipt")` and `generate_key_pair("replay_grant", kid_prefix="local-")`. The env table of SDK-replay §4.12 uses the five constants.

New module `keygen.py` (operators; production keys):

```python
PURPOSES: Final[Mapping[str, KeyPurpose]] = {"receipt": "receipt", "replay-grant": "replay_grant"}

def signer_env(purpose: KeyPurpose, pair: LocalKeyPair) -> dict[str, str]:
    # receipt:      {RECEIPT_SIGNING_KEY_ENV: pair.private_key}
    # replay_grant: {GRANT_SIGNING_KEY_ENV: pair.private_key, GRANT_SIGNING_KID_ENV: pair.kid}

def verifier_env(purpose: KeyPurpose, pair: LocalKeyPair) -> dict[str, str]:
    # receipt:      {RECEIPT_PUBLIC_KEYS_ENV: json.dumps({pair.kid: pair.public_key})}
    # replay_grant: {GRANT_PUBLIC_KEYS_ENV:   json.dumps({pair.kid: pair.public_key})}

def refuse_git_work_tree(path: Path) -> None:
    """SystemExit (message names the path and says "inside a git work tree") when
    path.resolve().parent or any of its parents holds a '.git' entry (dir or file).
    WHY: '*.env' files other than '.env' / '.env.*' are not in .gitignore, so a key file
    written into a checkout is one 'git add .' away from git."""

def write_env_file(path: Path, env: Mapping[str, str]) -> None:
    """refuse_git_work_tree(path) first. Then one 'NAME=value' line per entry, sorted, '\\n' after
    each. os.open(path, O_WRONLY|O_CREAT|O_EXCL, 0o600): an existing file is refused
    (FileExistsError -> SystemExit with a message that names the path).
    INVARIANT: never overwrites; never writes to stdout; never a key in the message."""

def main(argv: Sequence[str] | None = None) -> int:
    """python -m screamingface._runtime.keygen --purpose {receipt,replay-grant} --out PATH
    Writes signer_env to PATH (mode 0600; turn it into a Secret with the §9 item 2 one-file-per-key recipe).
    Prints to stdout ONLY: 'kid=<kid>' and one line per verifier_env entry ('NAME=<json>').
    Returns 0. Exit 2 for bad arguments (argparse)."""

if __name__ == "__main__":
    raise SystemExit(main())
```

- Production kids have no prefix for both purposes (OD-W2). The local runtime keeps `"local-"` for the grant kid (SDK-replay §4.12), so a local key never matches a production map.
- WHY the grant kid goes into the SIGNER file with the key: `SB-grants.md` §4.1 refuses a key without its kid (and the reverse) at `create_app`. One Secret with both keeps the pair together (the SDK-replay "per group" rule, §4.12).
- WHY a module in the SDK and not a new package or a shell script: D7 X-3 (no new shared package), and SDK-replay §2.1 forbids a second key generator. `python -m` keeps the public `screamingface` CLI unchanged. Run it from the checkout, and write OUTSIDE the checkout (the helper refuses a path in a git work tree): `KEYDIR="$(mktemp -d)"; uv run --project packages/screamingface python -m screamingface._runtime.keygen --purpose receipt --out "$KEYDIR/receipt.env"`.
- argparse: `--purpose` with `choices=sorted(PURPOSES)`, required; `--out` as `type=Path`, required. `main` resolves `PURPOSES[args.purpose]`, calls `generate_key_pair(purpose)` (no prefix), `write_env_file(args.out, signer_env(...))`, then prints `kid=<kid>` and the `verifier_env` lines (sorted), each with `print(..., flush=True)`.

### 4.5 Local runtime hook (`_runtime/local_features.py`) and `server.run()`

```python
ARCHIVE_DIRNAME: Final = "cache-version-archive"

LOCAL_E14_FLAGS: Final[Mapping[str, str]] = MappingProxyType({
    "AIGW_CACHE_VERSIONS_ENABLED": "true",      # GW-capture §4.1 (code default False)
    "SCOREBOARD_CLUSTERING_ENABLED": "true",    # SB-submit §4.1 (code default False)
})

ARCHIVE_ENV_GROUP: Final = (
    "AIGW_CACHE_VERSION_ARCHIVE_BACKEND",       # GW-freeze §4.1
    "AIGW_CACHE_VERSION_ARCHIVE_DIR",           # GW-freeze §4.1
    "SCOREBOARD_ARCHIVE_BACKEND",               # SB-publish §4.1
    "SCOREBOARD_ARCHIVE_FS_ROOT",               # SB-publish §4.1
)

def local_archive_dir(data_dir: Path) -> Path:        # data_dir / ARCHIVE_DIRNAME
def apply_local_e14_environment(environment: MutableMapping[str, str], data_dir: Path) -> None:
```

`apply_local_e14_environment` steps, in this order:
1. For each `LOCAL_E14_FLAGS` item: `environment.setdefault(name, value)`. An operator value wins, also `false` (the `enable_local_providers` rule, `bootstrap.py:41-45`).
2. Archive group. Count the names of `ARCHIVE_ENV_GROUP` that are set.
   - None set → `archive = local_archive_dir(data_dir)`; `archive.mkdir(parents=True, exist_ok=True, mode=0o700)`; `archive.chmod(0o700)`; set the two backends to `"filesystem"` and the two dirs to `str(archive)`.
   - All four set → change nothing. Then, if both backends are `"filesystem"` and the two dirs differ → `RuntimeError("AIGW_CACHE_VERSION_ARCHIVE_DIR and SCOREBOARD_ARCHIVE_FS_ROOT must name one directory in local mode (contracts C8)")`.
   - Some set → `RuntimeError("set all of <the four names> or none of them")`.
3. Print nothing. Log nothing.

WHY mode 0700: the archive holds full prompts and model answers (erd §3.5). The data dir already holds the key file with mode 0600 (SDK-replay).
WHY no `AIGW_REQUEST_CACHE_ENABLED`: capture works with the live cache off (every call is `bypass` with an inline body, `GW-capture.md` "Live cache off"). The live cache is a separate user choice (OME-1169). Do not set it.

`server.run()` change: directly after the SDK-replay line `apply_local_signing_environment(os.environ, config.data_dir)` (it follows `config.data_dir.mkdir(...)`, `server.py:176`), add `apply_local_e14_environment(os.environ, config.data_dir)`. Both run before `_migrate` and `_build_apps`. The gateway `Settings(...)` in `_build_apps` (`server.py:254-259`) and the scoreboard `Settings(...)` in `run_scoreboard` (`server.py:302-309`) read the other fields from the environment, and the scoreboard child inherits `os.environ` (`server.py:213-215`). Do not pass any E14 field to those two constructors (LR-6 guards it).

Local posture (D5): `screamingface up` keeps `auth_mode="disabled"` for the gateway and the scoreboard (`server.py:258`, `:306`). So locally: clustering uses the content hash, grants carry `sub="anonymous"`, publish and the admin route answer 503. That is today's dev/local fallback. Do not change it.

### 4.6 Scoreboard chart

#### 4.6.1 `values.yaml` (new keys; keep every old key)

```yaml
config:
  # (existing keys host … allowedNetworks stay)
  # Who may use the /v1/admin surface (withdraw, redistributable). Comma-joined into
  # SCOREBOARD_ADMIN_EMAILS. EMPTY IS THE SAFE DEFAULT: the admin API answers 503.
  # Works only with authMode: cloudflare_headers (D5).
  adminEmails: []
  clustering:
    enabled: true                  # SCOREBOARD_CLUSTERING_ENABLED
  # C3 verifier keys: {kid: base64 of the raw 32-byte Ed25519 public key}. Public; current
  # plus previous during a rotation. From `keygen --purpose receipt` stdout.
  receiptPublicKeys: {}            # SCOREBOARD_RECEIPT_PUBLIC_KEYS (JSON)
  publish:
    enabled: false                 # SCOREBOARD_PUBLISH_WORKER_ENABLED and the GitHub/archive keys
    githubAppId: ""
    githubAppInstallationId: ""
    githubRepo: ScreamingFace/screamingface-cache-versions
    publicBaseUrl: https://scoreboard.screamingface.ai
    archive:
      endpointUrl: ""
      bucket: screamingface-cache-versions
      region: garage

# E14 key material. Keys in the Secret are the env var names (envFrom cannot rename):
#   SCOREBOARD_REPLAY_GRANT_SIGNING_KEY, SCOREBOARD_REPLAY_GRANT_SIGNING_KID,
#   SCOREBOARD_GITHUB_APP_PRIVATE_KEY, SCOREBOARD_ARCHIVE_S3_ACCESS_KEY_ID,
#   SCOREBOARD_ARCHIVE_S3_SECRET_ACCESS_KEY.
e14Secret:
  existingSecret: ""               # RECOMMENDED for prod: created out of band (§9)
  # DEV ONLY — inline values render a chart Secret. No `lookup` reuse (secret-tracing.yaml WHY).
  replayGrantSigningKey: ""
  replayGrantSigningKid: ""
  githubAppPrivateKey: ""
  archiveAccessKeyId: ""
  archiveSecretAccessKey: ""
```

Add a `NetworkPolicy` peer block, same names as the gateway chart:

```yaml
networkPolicy:
  enabled: false
  clientNamespace: ""              # empty => this release's namespace
  clientPodNames: []               # app.kubernetes.io/name of the mesh (Envoy) data plane
  ingressCIDRs: []
```

#### 4.6.2 `values-prod.yaml` (D5 switch; keep every old key that is not named here)

```yaml
config:
  # D5: production identity is the verified X-User-Email of the Cloudflare Access + Envoy edge.
  # PRECONDITION (ops, WIRING.md §9 item 1): the host is routed through that edge. Do not
  # deploy this file before that.
  authMode: cloudflare_headers
  # The same private ranges as the aigateway chart default. NARROW to the Envoy Pod CIDR.
  allowedNetworks: "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10"
  # uvicorn's own loopback default: disjoint from allowedNetworks, never "*" (main.py guard).
  forwardedAllowIps: "127.0.0.1"
  adminEmails: []                  # set at install time (--set-string), never committed
  clustering:
    enabled: true
  receiptPublicKeys: {}            # set at install time from keygen stdout (§9 item 2)
  publish:
    enabled: false                 # turn on after §9 items 3 and 4
e14Secret:
  existingSecret: scoreboard-e14   # created out of band (§9 item 2); the pod does not start without it
# The public route is the Envoy edge (§9 item 1). A direct Traefik Ingress would let any caller
# forge X-User-Email (the chart refuses the pair, scoreboard.validateAuth).
ingress:
  enabled: false
networkPolicy:
  enabled: true
  clientNamespace: ""              # set at install time: the Envoy data-plane namespace
  clientPodNames: []               # set at install time: the Envoy data-plane pod name
```

Delete the `cert-manager` annotation, `hosts` and `tls` entries from `values-prod.yaml` `ingress` (they have no effect with `enabled: false`; the Envoy edge terminates TLS).

#### 4.6.3 Helpers and `configmap.yaml`

`_helpers.tpl`:
- `scoreboard.validateAuth` (mirror `aigateway.validateAuth`, `_helpers.tpl:50-61`): `authMode` not in `disabled`, `cloudflare_headers` → fail. In `cloudflare_headers`: empty `allowedNetworks` → fail; `forwardedAllowIps == "*"` → fail (name `main.py`'s guard); `ingress.enabled` → fail. Each message says what to set, like the gateway messages. The CIDR overlap cannot be checked in Helm; `verify_chart_wiring.py` checks it (CH-3).
- `scoreboard.validateE14`: inline `replayGrantSigningKey` set without `replayGrantSigningKid`, or the reverse → fail. `publish.enabled` and `authMode != cloudflare_headers` → fail ("publishing works only in cloudflare_headers; SB-publish answers 503 publish_unavailable"). `publish.enabled` and an empty `githubAppId`, `githubAppInstallationId` or `archive.endpointUrl` → fail (name the value). `publish.enabled` and no Secret source (`existingSecret` empty and any of `githubAppPrivateKey`, `archiveAccessKeyId`, `archiveSecretAccessKey` empty) → fail. Publish off and an inline `githubAppPrivateKey` → fail (a partial `github_app_*` set, see below).
- `scoreboard.e14SecretName`: `existingSecret` if set, else `printf "%s-e14" (include "scoreboard.fullname" .)`.
- `scoreboard.e14InlineSecret`: prints `true` when any of the five inline `e14Secret` values is set, else prints nothing (the `aigateway.tracingHasSecret` form: a helper that prints `true` or an empty string, so `if include …` works).
- `scoreboard.e14HasSecret`: prints `true` when `e14Secret.existingSecret` is set or `scoreboard.e14InlineSecret` prints `true`, else prints nothing.

`configmap.yaml`: first two lines `{{- include "scoreboard.validateAuth" . -}}` and `{{- include "scoreboard.validateE14" . -}}`. New keys, each with a one-line WHY comment:

```yaml
  SCOREBOARD_ADMIN_EMAILS: {{ join "," .Values.config.adminEmails | quote }}          # always emitted
  SCOREBOARD_CLUSTERING_ENABLED: {{ .Values.config.clustering.enabled | quote }}      # always emitted
  SCOREBOARD_RECEIPT_PUBLIC_KEYS: {{ .Values.config.receiptPublicKeys | toJson | quote }}   # always, "{}" default
  SCOREBOARD_PUBLISH_WORKER_ENABLED: {{ .Values.config.publish.enabled | quote }}     # always emitted
  {{- if .Values.config.publish.enabled }}
  SCOREBOARD_GITHUB_APP_ID: {{ .Values.config.publish.githubAppId | quote }}
  SCOREBOARD_GITHUB_APP_INSTALLATION_ID: {{ .Values.config.publish.githubAppInstallationId | quote }}
  SCOREBOARD_GITHUB_REPO: {{ .Values.config.publish.githubRepo | quote }}
  SCOREBOARD_PUBLIC_BASE_URL: {{ .Values.config.publish.publicBaseUrl | quote }}
  SCOREBOARD_ARCHIVE_BACKEND: "s3"
  SCOREBOARD_ARCHIVE_S3_ENDPOINT_URL: {{ .Values.config.publish.archive.endpointUrl | quote }}
  SCOREBOARD_ARCHIVE_S3_BUCKET: {{ .Values.config.publish.archive.bucket | quote }}
  SCOREBOARD_ARCHIVE_S3_REGION: {{ .Values.config.publish.archive.region | quote }}
  {{- else }}
  SCOREBOARD_ARCHIVE_BACKEND: "none"
  {{- end }}
```

WHY the GitHub keys only when publish is on: SB-publish `create_app` refuses a partial `github_app_*` set (`SB-publish.md` §4.1). The App private key comes from the Secret and is also a `github_app_*` field. So: `scoreboard.validateE14` fails when publish is off and the inline `githubAppPrivateKey` is set, and `DEPLOYMENT.md` says "add `SCOREBOARD_GITHUB_APP_PRIVATE_KEY` to `scoreboard-e14` only in the same deploy that sets `publish.enabled: true`" (§9 item 4). The chart cannot see inside an `existingSecret`.

INVARIANT: no private value is in the ConfigMap. The five Secret keys of §4.6.1 never appear in `configmap.yaml`.

#### 4.6.4 `secret-e14.yaml`

Rendered only when `existingSecret` is empty and at least one inline value is set. `stringData` holds only the inline values that are set, under the env names of §4.6.1. Copy the header WHY of `secret-tracing.yaml` (no `lookup` reuse; `existingSecret` is the durable path; inline is dev only). The body, exactly (values through `toJson`, NOT `quote`: `quote` does not escape a newline, and YAML folds a raw newline in a double-quoted scalar into a space, so a PEM App key would be corrupted; a JSON string is a valid YAML double-quoted scalar):

```yaml
{{- if and (not .Values.e14Secret.existingSecret) (include "scoreboard.e14InlineSecret" .) }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "scoreboard.e14SecretName" . }}
  labels:
    {{- include "scoreboard.labels" . | nindent 4 }}
type: Opaque
stringData:
  {{- with .Values.e14Secret.replayGrantSigningKey }}
  SCOREBOARD_REPLAY_GRANT_SIGNING_KEY: {{ . | toJson }}
  {{- end }}
  {{- with .Values.e14Secret.replayGrantSigningKid }}
  SCOREBOARD_REPLAY_GRANT_SIGNING_KID: {{ . | toJson }}
  {{- end }}
  {{- with .Values.e14Secret.githubAppPrivateKey }}
  SCOREBOARD_GITHUB_APP_PRIVATE_KEY: {{ . | toJson }}
  {{- end }}
  {{- with .Values.e14Secret.archiveAccessKeyId }}
  SCOREBOARD_ARCHIVE_S3_ACCESS_KEY_ID: {{ . | toJson }}
  {{- end }}
  {{- with .Values.e14Secret.archiveSecretAccessKey }}
  SCOREBOARD_ARCHIVE_S3_SECRET_ACCESS_KEY: {{ . | toJson }}
  {{- end }}
{{- end }}
```

`deployment.yaml`, two changes:

1. Replace lines 19-22 (the `with .Values.podAnnotations` block) with the gateway form (`apps/aigateway/charts/aigateway/templates/deployment.yaml:30-38`), so the annotation key is always there:

```yaml
      annotations:
        # Roll the Pods when the ConfigMap changes (a flag flip must reach the Pods; envFrom is
        # read once at container start). Same guard as the aigateway chart.
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
        {{- with .Values.podAnnotations }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
```

2. Under `envFrom`, after the `configMapRef` item (line 49):

```yaml
            {{- if include "scoreboard.e14HasSecret" . }}
            # E14 key material (grant signing key and kid, GitHub App key, archive read key).
            # Not optional: a missing prod Secret must stop the Pod loudly (WIRING §9 item 2).
            - secretRef:
                name: {{ include "scoreboard.e14SecretName" . }}
            {{- end }}
```

#### 4.6.5 `networkpolicy.yaml`

Replace the `from:` build with the gateway pattern (`apps/aigateway/charts/aigateway/templates/networkpolicy.yaml:20-35`, without `allowFrom`). Copy its two INVARIANT comments (no rule without `from:` in the verified mode; one `from` element pairs the namespace and the pod selector). The template, exactly (keep lines 1-18 and the `egress` block as they are):

```yaml
{{- if .Values.networkPolicy.enabled -}}
{{- $ns := .Values.networkPolicy.clientNamespace | default .Release.Namespace -}}
{{- $peers := list -}}
{{- range .Values.networkPolicy.clientPodNames -}}
{{- $peers = append $peers (dict
      "namespaceSelector" (dict "matchLabels" (dict "kubernetes.io/metadata.name" $ns))
      "podSelector" (dict "matchLabels" (dict "app.kubernetes.io/name" .))) -}}
{{- end -}}
{{- range .Values.networkPolicy.ingressCIDRs -}}
{{- $peers = append $peers (dict "ipBlock" (dict "cidr" .)) -}}
{{- end -}}
{{- if and (not $peers) (eq .Values.config.authMode "cloudflare_headers") -}}
{{- fail "networkPolicy.enabled=true with config.authMode=cloudflare_headers but no peers — in this mode the NetworkPolicy is the authentication boundary (the app trusts X-User-Email because only these peers can send it), and a rule with no `from:` admits every source. Name the Envoy data plane in networkPolicy.clientPodNames (and networkPolicy.clientNamespace)." -}}
{{- end -}}
```

Put that block directly after line 1 (`{{- if .Values.networkPolicy.enabled -}}`, which it repeats above for context; do not add a second `if`). Keep lines 2-18 unchanged. Replace lines 19-25 (the `if .Values.networkPolicy.ingressCIDRs` block) with:

```yaml
      {{- if $peers }}
      from:
        {{- toYaml $peers | nindent 8 }}
      {{- end }}
```

When `authMode == disabled` and the list is empty, the rule has no `from:` (today's default render, unchanged). With `ingressCIDRs` only, the output is the same `ipBlock` list as today.

### 4.7 Aigateway chart

#### 4.7.1 `values.yaml` (new block under `config`)

```yaml
config:
  cacheVersions:
    # E14 kill switch (GW-capture). On: traced calls are captured, freeze and replay answer.
    # Needs the receipt signing key (a Secret) — the chart cannot mint it, because the
    # scoreboard must hold its public half.
    enabled: false                  # AIGW_CACHE_VERSIONS_ENABLED
    # C6 verifier keys: {kid: base64 of the raw 32-byte Ed25519 public key}. Public.
    replayGrantPublicKeys: {}       # AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS (JSON)
    archive:
      backend: none                 # none | s3   (AIGW_CACHE_VERSION_ARCHIVE_BACKEND); filesystem is local-runtime only
      endpointUrl: ""               # empty + bundled snapshot Garage => that Garage Service
      bucket: screamingface-cache-versions   # the objects live under cache-versions/<vid>/ (erd §3.5)
      region: garage
      # Extra NetworkPolicyPeer entries appended to the bundled Garage :3900 ingress — the
      # scoreboard reader (PB-D8). Raw peers, like networkPolicy.allowFrom. The scoreboard runs
      # in its own namespace, so ONE entry must carry BOTH selectors (ANDed), e.g.
      #   - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: scoreboard}}
      #     podSelector: {matchLabels: {app.kubernetes.io/name: scoreboard}}
      # Two separate entries would admit the whole namespace OR that label anywhere.
      readerPeers: []
    # Keys in the Secret are the env names: AIGATEWAY_RECEIPT_SIGNING_KEY,
    # AIGW_CACHE_VERSION_S3_ACCESS_KEY, AIGW_CACHE_VERSION_S3_SECRET_KEY.
    existingSecret: ""              # RECOMMENDED
    receiptSigningKey: ""           # DEV ONLY inline
    archiveAccessKey: ""            # DEV ONLY inline
    archiveSecretKey: ""            # DEV ONLY inline
```

#### 4.7.2 `values-prod.yaml`

```yaml
config:
  cacheVersions:
    enabled: true
    replayGrantPublicKeys: {}       # set at install time from `keygen --purpose replay-grant` stdout (§9 item 2)
    archive:
      backend: none                 # switch to s3 after §9 item 3 (bucket and keys exist)
    existingSecret: aigw-cache-versions   # created out of band (§9 item 2)
```

#### 4.7.3 Helpers and `configmap.yaml`

`_helpers.tpl`:
- `aigateway.validateCacheVersions`: `archive.backend` not in `none`, `s3` → fail (`filesystem` is for `screamingface up` only: a per-Pod directory is not shared across replicas). `enabled` and no key source (`existingSecret` empty and `receiptSigningKey` empty) → fail. `archive.backend == s3` and `aigateway.cacheVersionsEndpoint` empty → fail. `archive.backend == s3` and `existingSecret` empty and either inline archive key empty → fail. `archive.backend == s3` and not `enabled` → fail (an exporter with the capture off is a mistake).
- `aigateway.cacheVersionsEndpoint`: `archive.endpointUrl` if set; else, when `snapshot.enabled` and `snapshot.garage.enabled`, `http://<fullname>-garage:3900` (the `aigateway.snapshotEndpoint` form, `_helpers.tpl:139-146`); else empty.
- `aigateway.cacheVersionsSecretName`: `existingSecret` or `<fullname>-cache-versions`.
- `aigateway.cacheVersionsInlineSecret`: prints `true` when any of `receiptSigningKey`, `archiveAccessKey`, `archiveSecretKey` is set, else prints nothing (the `tracingHasSecret` form).

`configmap.yaml`: add `{{- include "aigateway.validateCacheVersions" . -}}` after line 3. New keys:

```yaml
  AIGW_CACHE_VERSIONS_ENABLED: {{ .Values.config.cacheVersions.enabled | quote }}                      # always
  AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS: {{ .Values.config.cacheVersions.replayGrantPublicKeys | toJson | quote }}   # always
  AIGW_CACHE_VERSION_ARCHIVE_BACKEND: {{ .Values.config.cacheVersions.archive.backend | quote }}        # always
  {{- if eq .Values.config.cacheVersions.archive.backend "s3" }}
  AIGW_CACHE_VERSION_S3_ENDPOINT_URL: {{ include "aigateway.cacheVersionsEndpoint" . | quote }}
  AIGW_CACHE_VERSION_S3_BUCKET: {{ .Values.config.cacheVersions.archive.bucket | quote }}
  AIGW_CACHE_VERSION_S3_REGION: {{ .Values.config.cacheVersions.archive.region | quote }}
  {{- end }}
```

#### 4.7.4 `secret-cache-versions.yaml` and `deployment.yaml`

- Secret: guard `{{- if and .Values.config.cacheVersions.enabled (not .Values.config.cacheVersions.existingSecret) (include "aigateway.cacheVersionsInlineSecret" .) }}`. Name `{{ include "aigateway.cacheVersionsSecretName" . }}`, labels `aigateway.labels`, `type: Opaque`. `stringData` holds each set inline value under its env name (§4.7.1), one `{{- with … }}KEY: {{ . | toJson }}{{- end }}` block per value, the same form as §4.6.4 (`toJson`, not `quote`). Same header WHY as `secret-tracing.yaml`. WHY `enabled` in the guard: the Deployment mounts the Secret only when `enabled`, so an unmounted chart Secret is noise.
- Deployment `envFrom`: after the snapshot `secretRef` block (`deployment.yaml:70-75`), exactly:

```yaml
            {{- if .Values.config.cacheVersions.enabled }}
            # E14 receipt signing key and the archive writer key (WIRING §4.7). Not optional:
            # validateCacheVersions guarantees a source when enabled, and a missing prod Secret
            # must stop the Pod loudly.
            - secretRef:
                name: {{ include "aigateway.cacheVersionsSecretName" . }}
            {{- end }}
```

#### 4.7.5 `garage.yaml`

In the Garage NetworkPolicy `from:` list (`garage.yaml:183-190`), after the gateway peer: `{{- with .Values.config.cacheVersions.archive.readerPeers }}{{- toYaml . | nindent 8 }}{{- end }}`. No other Garage change. The bucket and the two keys are ops (§9 item 3): Garage `--default-bucket` makes only the snapshot bucket.

### 4.8 `verify_chart_wiring.py` block, lanes, and the env/Secret table

#### 4.8.1 New constants and helpers (put them directly before the E14 checks, before `print(f"\n{checks - len(failures)}/{checks} checks passed")` at line 1496)

```python
SCOREBOARD_CHART = REPO / "apps/scoreboard/charts/scoreboard"
SCOREBOARD_RELEASE = "scoreboard"
SCOREBOARD_SETTINGS = REPO / "apps/scoreboard/src/scoreboard/config.py"
GATEWAY_SETTINGS = REPO / "apps/aigateway/src/aigateway/config.py"
# Install-time values that values-prod.yaml cannot know (the Envoy data plane). Placeholders,
# not deployment values. charts.yml and release-scoreboard.yml pass the SAME set (CH-7).
SCOREBOARD_PROD_ARGS = (
    "--values", str(SCOREBOARD_CHART / "values-prod.yaml"),
    "--set", "networkPolicy.clientPodNames[0]=ci-placeholder-envoy",
    "--set", "networkPolicy.clientNamespace=ci-placeholder-envoy-ns",
)
E14_SCOREBOARD_SECRET_KEYS = frozenset({"SCOREBOARD_REPLAY_GRANT_SIGNING_KEY", "SCOREBOARD_REPLAY_GRANT_SIGNING_KID",
    "SCOREBOARD_GITHUB_APP_PRIVATE_KEY", "SCOREBOARD_ARCHIVE_S3_ACCESS_KEY_ID", "SCOREBOARD_ARCHIVE_S3_SECRET_ACCESS_KEY"})
E14_GATEWAY_SECRET_KEYS = frozenset({"AIGATEWAY_RECEIPT_SIGNING_KEY", "AIGW_CACHE_VERSION_S3_ACCESS_KEY", "AIGW_CACHE_VERSION_S3_SECRET_KEY"})

def pydantic_env_names(path: Path, class_name: str, *, prefix: str) -> set[str]:
    """Env names of a pydantic-settings class, by ast (no import; same WHY as settings_fields).
    A field with Field(validation_alias="X") gives "X"; else prefix + NAME.upper()."""

def configmap_data(docs: list[dict]) -> dict[str, str]:     # find(docs, "ConfigMap")["data"]
def secret_refs(deployment: dict) -> list[str]:              # names of envFrom secretRef entries
```

WHY a new helper and not `settings_fields()`: that one is fixed to report-intake (`INTAKE_SETTINGS`, prefix `REPORT_INTAKE_`, `:177-197`). Do not change it.

#### 4.8.2 The checks (CH rows of §6 task group D and E)

Each check is one `check(condition, description)` call. The description states the property, in the style of the old checks.

#### 4.8.3 Lanes

- `charts.yml` (`on.push.paths` and `on.pull_request.paths`, both lists): add `apps/scoreboard/charts/**`, `apps/scoreboard/src/scoreboard/config.py`, `apps/aigateway/src/aigateway/config.py`, `.github/workflows/release-scoreboard.yml`. WHY the two `config.py` lines: the verifier reads the settings classes (the same reason as `charts.yml:21-24`).
- `charts.yml` step "Lint": add `helm lint apps/scoreboard/charts/scoreboard` and `helm lint apps/scoreboard/charts/db`.
- `charts.yml`: new step named exactly `Render the scoreboard prod values`: `helm template scoreboard apps/scoreboard/charts/scoreboard --values apps/scoreboard/charts/scoreboard/values-prod.yaml --set 'networkPolicy.clientPodNames[0]=ci-placeholder-envoy' --set networkPolicy.clientNamespace=ci-placeholder-envoy-ns > /dev/null`, with an AIDEV-NOTE that the release lane must carry the same set.
- `release-scoreboard.yml` step "Lint and render charts" (`:78-89`): add the same two `--set` flags to the `values-prod.yaml` render. Do not change the other lines.

#### 4.8.4 Every new env var and Secret key

"Where" = the chart object that carries it. "Local" = what `screamingface up` sets (§4.5, SDK-replay §4.12). Every name is read from a merged settings class in Step 0.

| Variable | Consumer unit, plan section | Where (chart) | Chart value | Local (`screamingface up`) |
|---|---|---|---|---|
| `AIGW_CACHE_VERSIONS_ENABLED` | GW-capture §4.1 | gateway ConfigMap | `config.cacheVersions.enabled` (false; prod true) | `"true"` (hook) |
| `AIGATEWAY_RECEIPT_SIGNING_KEY` | GW-freeze §4.1, §4.3 | gateway Secret | `config.cacheVersions.existingSecret` / `receiptSigningKey` | SDK-replay key file |
| `AIGW_CACHE_VERSION_ARCHIVE_BACKEND` | GW-freeze §4.1 | gateway ConfigMap | `config.cacheVersions.archive.backend` | `"filesystem"` (hook) |
| `AIGW_CACHE_VERSION_ARCHIVE_DIR` | GW-freeze §4.1 | not in the chart (local only) | — | `<data_dir>/cache-version-archive` (hook) |
| `AIGW_CACHE_VERSION_S3_ENDPOINT_URL` | GW-freeze §4.1 | gateway ConfigMap (s3 only) | `archive.endpointUrl` or bundled Garage | — |
| `AIGW_CACHE_VERSION_S3_BUCKET` | GW-freeze §4.1 | gateway ConfigMap (s3 only) | `archive.bucket` | — |
| `AIGW_CACHE_VERSION_S3_REGION` | GW-freeze §4.1 | gateway ConfigMap (s3 only) | `archive.region` | — |
| `AIGW_CACHE_VERSION_S3_ACCESS_KEY` | GW-freeze §4.1 | gateway Secret | `existingSecret` / `archiveAccessKey` | — |
| `AIGW_CACHE_VERSION_S3_SECRET_KEY` | GW-freeze §4.1 | gateway Secret | `existingSecret` / `archiveSecretKey` | — |
| `AIGW_CACHE_VERSION_MAX_ENTRIES`, `AIGW_CACHE_VERSION_MAX_ARCHIVE_BYTES`, `AIGW_CACHE_VERSION_S3_TIMEOUT_S`, `AIGW_CACHE_VERSION_EXPORT_POLL_S` | GW-freeze §4.1 | not emitted (code defaults) | — | — |
| `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS` | GW-replay §4.1 | gateway ConfigMap (JSON) | `config.cacheVersions.replayGrantPublicKeys` | SDK-replay key file |
| `AIGW_REPLAY_GRANT_CACHE_TTL_S` | GW-replay §4.1 | not emitted (60 s default) | — | — |
| `SCOREBOARD_AUTH_MODE` | existing; D5 | scoreboard ConfigMap | `config.authMode` (prod `cloudflare_headers`) | `disabled` (unchanged) |
| `SCOREBOARD_ALLOWED_NETWORKS` | existing; D5 | scoreboard ConfigMap | `config.allowedNetworks` (prod private ranges) | — |
| `FORWARDED_ALLOW_IPS` | existing; D5 (`main.py:152-176` guard) | scoreboard ConfigMap | `config.forwardedAllowIps` (prod `127.0.0.1`) | — |
| `SCOREBOARD_CLUSTERING_ENABLED` | SB-submit §4.1 | scoreboard ConfigMap | `config.clustering.enabled` (true) | `"true"` (hook) |
| `SCOREBOARD_RECEIPT_PUBLIC_KEYS` | SB-submit §4.1 | scoreboard ConfigMap (JSON) | `config.receiptPublicKeys` | SDK-replay key file |
| `SCOREBOARD_REPLAY_GRANT_SIGNING_KEY` | SB-grants §4.1 | scoreboard Secret | `e14Secret.*` | SDK-replay key file |
| `SCOREBOARD_REPLAY_GRANT_SIGNING_KID` | SB-grants §4.1 | scoreboard Secret (paired with the key, OD-W2) | `e14Secret.*` | SDK-replay key file (`local-…`) |
| `SCOREBOARD_ADMIN_EMAILS` | SB-publish §4.1, §4.10; this unit §4.1 | scoreboard ConfigMap | `config.adminEmails` | — (admin is 503 in `disabled`) |
| `SCOREBOARD_PUBLISH_WORKER_ENABLED` | SB-publish §4.1 | scoreboard ConfigMap | `config.publish.enabled` | — (code default True; publish is 503 in `disabled`) |
| `SCOREBOARD_GITHUB_APP_ID`, `SCOREBOARD_GITHUB_APP_INSTALLATION_ID`, `SCOREBOARD_GITHUB_REPO` | SB-publish §4.1 | scoreboard ConfigMap (publish on) | `config.publish.github*` | — |
| `SCOREBOARD_GITHUB_APP_PRIVATE_KEY` | SB-publish §4.1 | scoreboard Secret | `e14Secret.*` | — |
| `SCOREBOARD_GITHUB_API_URL` | SB-publish §4.1 | not emitted (default) | — | — |
| `SCOREBOARD_PUBLIC_BASE_URL` | SB-publish §4.1 | scoreboard ConfigMap (publish on) | `config.publish.publicBaseUrl` | — |
| `SCOREBOARD_ARCHIVE_BACKEND` | SB-publish §4.1 | scoreboard ConfigMap | `s3` when publish on, else `none` | `"filesystem"` (hook) |
| `SCOREBOARD_ARCHIVE_S3_ENDPOINT_URL`, `SCOREBOARD_ARCHIVE_S3_BUCKET`, `SCOREBOARD_ARCHIVE_S3_REGION` | SB-publish §4.1 | scoreboard ConfigMap (publish on) | `config.publish.archive.*` | — |
| `SCOREBOARD_ARCHIVE_S3_ACCESS_KEY_ID`, `SCOREBOARD_ARCHIVE_S3_SECRET_ACCESS_KEY` | SB-publish §4.1 | scoreboard Secret (READ-ONLY key, PB-D8) | `e14Secret.*` | — |
| `SCOREBOARD_ARCHIVE_FS_ROOT` | SB-publish §4.1 | not in the chart (local only) | — | `<data_dir>/cache-version-archive` (hook) |
| `SCOREBOARD_PUBLISH_POLL_INTERVAL_S` | SB-publish §4.1 | not emitted (30 s default) | — | — |

Secret objects: gateway `aigw-cache-versions` (prod name; keys `AIGATEWAY_RECEIPT_SIGNING_KEY`, `AIGW_CACHE_VERSION_S3_ACCESS_KEY`, `AIGW_CACHE_VERSION_S3_SECRET_KEY`) and scoreboard `scoreboard-e14` (keys `SCOREBOARD_REPLAY_GRANT_SIGNING_KEY`, `SCOREBOARD_REPLAY_GRANT_SIGNING_KID`, `SCOREBOARD_GITHUB_APP_PRIVATE_KEY`, `SCOREBOARD_ARCHIVE_S3_ACCESS_KEY_ID`, `SCOREBOARD_ARCHIVE_S3_SECRET_ACCESS_KEY`). A key that a feature does not use yet can be absent.

### 4.9 `DEPLOYMENT.md` sections

Scoreboard, section "E14 deploy wiring": the D5 posture and the §9 item 1 precondition (point to `docs/work/2026-08-03-OME-404-authenticated-leaderboard-submissions.md:94-98`); the §4.8.4 scoreboard rows; the `scoreboard-e14` Secret keys; keygen commands for both purposes and how to put the stdout JSON into `config.receiptPublicKeys` (and the gateway `replayGrantPublicKeys`); rotation (add the new kid to the verifier map, deploy the verifier, then switch the signer, then remove the old kid after the longest grant life of 12 h, D4); the admin route with a `curl` example (`-X PUT … -H 'content-type: application/json' -d '{"redistributable": true, "reason": "…"}'`, sent through the edge); the render placeholders.

Gateway, section "E14 deploy wiring": the §4.8.4 gateway rows, the `aigw-cache-versions` Secret keys, the archive backends (`none`, `s3`; `filesystem` is local only), the bundled-Garage endpoint default and `readerPeers`, the §9 item 3 bucket steps, and "the chart never mints a receipt key".

## 5. Migrations

None. SB-schema added `Benchmark.redistributable` (migration `0017`–`0019` range). If the merged model has no `redistributable`, **STOP**.

## 6. TDD order (RED first, risk order)

Step 0: the ledger, the §2 name check, the stubs: `set_benchmark_redistributable` raises `NotImplementedError` (the route exists, so a RED is a 500, not a 404 from routing); `set_redistributable` returns `None`; `apply_local_e14_environment` does nothing; `generate_key_pair` returns a pair of empty strings; `keygen.main` returns 0 and writes nothing. Each RED below fails on an assertion.

**Task group A — admin route (scoreboard). Commit after A.**

Fixtures: `tests/unit/publish/conftest.py` (SB-publish): `publish_client` (`cloudflare_headers`, `admin_emails="admin@x.org"`), `publish_untrusted_client`, `publish_disabled_client`, `as_user`, `BRUNO`, and the benchmarks `pub` (redistributable), `gated` (not redistributable), `priv`. Add no fixture to that `conftest.py`. If a test needs an empty allowlist, build the app in the test with the same settings and `admin_emails=""` (copy the fixture body; do not import a private helper). `ADMIN = as_user("admin@x.org")`.

| # | Id | Test name (`test_admin_redistributable.py`) | RED reason |
|---|---|---|---|
| 1 | WR-1 | `test_admin_sets_redistributable_and_the_row_changes` — `PUT /v1/admin/benchmarks/gated/redistributable {"redistributable": true, "reason": "license: CC-BY-4.0"}` as admin → 200 `{"benchmark_id": "gated", "redistributable": true, "changed": true}`; `(await Benchmark.get(id="gated")).redistributable is True` | 500 (`NotImplementedError`) |
| 2 | WR-2 | `test_same_value_again_is_a_noop_200` — the same call twice → second is 200 with `changed: false`; the row is still True; set `false` → 200 `changed: true`, the row is False | 500 |
| 3 | WR-3 | `test_non_admin_is_403_and_nothing_changes` — `as_user(BRUNO)` → 403 `detail.code == "admin_required"`; no header → 401 `identity_not_verified`; `publish_untrusted_client` with the admin header → 403 `UNTRUSTED_PEER_DETAIL`; an app with `admin_emails=""` → 503 `admin_unavailable`; after each, `gated` is still False | 500 for the admin baseline part (write the admin call first in the test, then the refusals) |
| 4 | WR-4 | `test_unknown_benchmark_is_404_and_no_row_is_created` — `PUT …/nope/redistributable` as admin → 404 `detail.code == "benchmark_not_found"`; `await Benchmark.filter(id="nope").exists() is False` | 500 |
| 5 | WR-5 | `test_every_attempt_is_audited_with_target_reason_change` — `caplog` at INFO on `scoreboard.routes.admin`: WR-1 call → one line that contains `admin_action actor=admin@x.org`, `benchmark_id=gated`, `reason=license: CC\-BY\-4\.0` (the `escape_markdown` form of SB-publish; assert with the function, not a hand-escaped string), `outcome=200`, `change=redistributable=true`; the Bruno call → a line with `actor=bruno@…`, `benchmark_id=gated`, `outcome=403` and no `change=` (require_admin refused before the handler); the WR-4 call → `outcome=404`, `change=redistributable=true` | the audit line has no `benchmark_id=` (KeyError on `result_id`, or `<none>`) |
| 6 | WR-6 | `test_bad_body_is_422_and_audited` — no `reason` → 422; `"redistributable": "yes"` → 422; an extra field → 422; each logs `outcome=422` | 500 |
| 7 | WR-7 | `test_disabled_mode_is_503` — `publish_disabled_client` with a forged `X-User-Email: admin@x.org` → 503 `admin_unavailable`; the row does not change. The only `disabled` test of this route (D5). | 500 |
| 8 | WR-8 | `test_seed_keeps_the_admin_decision` — after WR-1, `await ScoreStore().register_benchmark("gated", display_name="Gated")` (the seed path, `store.py:747-777`; only the two required arguments) → `gated` is still True | guard row: it can pass at once after WR-1 GREEN; show RED by running it with the WR-1 stub; write both runs in the ledger |
| 9 | WR-9 | `test_redistributable_unblocks_publish_and_withdraw_line_is_unchanged` — seed a result on `gated` for ANA with the exact steps of the SB-publish `gated` case of PB-1 (`test_publish_route.py::test_publish_private_board_or_not_redistributable_409_reason`: `POST /v1/scores` on `publish_client`, `headers=as_user(ANA)`, a `make_receipt` receipt whose `sha` is the `canonical_pair()` digest; copy the steps, do not import from that test file). Owner `POST /v1/results/{id}/publish` → 409 with `detail == {"code": "not_publishable", "reason": "not_redistributable"}` (plus any extra keys SB-publish adds: assert the two keys only); admin sets `gated` true; owner publish → 202 `{"state": "requested"}`. Then admin `POST /v1/admin/results/{id}/withdraw {"reason": "x"}` → the audit line still contains `result_id=<id>` and no `benchmark_id=` | 500 |

**Task group B — key helper (SDK). Commit after B.**

RFC 8032 §7.1 TEST 1 vector (fixed, public): seed hex `9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60` (base64 `nWGxne/9WmC6hEr0kuwsxERJxWl7MmkZcDusAxyuf2A=`), public hex `d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a` (base64 `11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=`), so `kid = "21fe31dfa154a261"` (= `sha256(public raw).hexdigest()[:16]`). It is a published test vector, not a key of this system.

| # | Id | Test name (`test_runtime_keygen.py`) | RED reason |
|---|---|---|---|
| 10 | KG-1 | `test_rfc8032_vector_gives_raw_base64_and_the_gw_freeze_kid` — `generate_key_pair("receipt", seed=<vector seed>)` → `private_key` and `public_key` equal the two base64 strings above; `kid == "21fe31dfa154a261"`; `len(b64decode(x, validate=True)) == 32` for both; no `-----BEGIN` in either | stub returns empty strings |
| 11 | KG-2 | `test_fresh_pair_verifies_and_kid_is_derived` — `generate_key_pair("replay_grant")`: sign `b"x"` with `nacl.signing.SigningKey(b64decode(private))`, verify with `nacl.signing.VerifyKey(b64decode(public))`; `kid == hashlib.sha256(b64decode(public)).hexdigest()[:16]`; two calls give two kids | stub |
| 12 | KG-3 | `test_receipt_kid_takes_no_prefix` — `generate_key_pair("receipt", kid_prefix="x-")` → `ValueError`; `generate_key_pair("replay_grant", kid_prefix="local-").kid.startswith("local-")` | no check |
| 13 | KG-4 | `test_cli_writes_a_private_env_file_and_prints_only_public_parts` — `keygen.main(["--purpose", "receipt", "--out", str(tmp_path / "r.env")])` → 0; `stat.S_IMODE(mode) == 0o600`; the file has exactly one line `AIGATEWAY_RECEIPT_SIGNING_KEY=<b64>`; `capsys` stdout has `kid=<kid>` and `SCOREBOARD_RECEIPT_PUBLIC_KEYS=` whose JSON is `{kid: public}`, and does NOT contain the private base64 | nothing written |
| 14 | KG-5 | `test_cli_replay_grant_pairs_key_and_kid` — `--purpose replay-grant` → the file has `SCOREBOARD_REPLAY_GRANT_SIGNING_KEY` and `SCOREBOARD_REPLAY_GRANT_SIGNING_KID` (no prefix); stdout has `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS={kid: public}` with the same kid | nothing written |
| 15 | KG-6 | `test_cli_refuses_to_overwrite` — an existing `--out` file → `SystemExit` with the path in the message; the old bytes are unchanged; stdout has no key | overwrite or no error |
| 15a | KG-7 | `test_cli_refuses_a_path_inside_a_git_work_tree` — `(tmp_path / "repo" / ".git").mkdir(parents=True)`; `--out tmp_path/repo/sub/r.env` (make `sub`) → `SystemExit` whose text names the path and says `inside a git work tree`; no file is created; stdout has no key. Also a `.git` FILE (a worktree marker) in `tmp_path/wt` → the same refusal | file written |

Plus: the SDK-replay RP-20 tests (`test_runtime_signing_keys.py`) stay green after the extract (run them by name in the ledger).

**Task group C — local runtime (SDK). Commit after C.**

| # | Id | Test name (`test_runtime_local_features.py`) | RED reason |
|---|---|---|---|
| 16 | LR-1 | `test_empty_env_gets_flags_and_one_private_archive_dir` — `env = {}`; `apply_local_e14_environment(env, tmp_path)` → both `LOCAL_E14_FLAGS` names are `"true"`; the two backends are `"filesystem"`; `env["AIGW_CACHE_VERSION_ARCHIVE_DIR"] == env["SCOREBOARD_ARCHIVE_FS_ROOT"] == str(tmp_path / "cache-version-archive")`; the dir exists with `S_IMODE == 0o700` | stub sets nothing |
| 17 | LR-2 | `test_operator_values_win` — preset `AIGW_CACHE_VERSIONS_ENABLED="false"` → still `"false"`; all four archive names preset (filesystem, one dir `d`) → unchanged | stub |
| 18 | LR-3 | `test_partial_archive_group_fails` — only `AIGW_CACHE_VERSION_ARCHIVE_DIR` set → `RuntimeError` whose text names the four variables | no error |
| 19 | LR-4 | `test_two_filesystem_dirs_must_be_one` — all four set, both `filesystem`, two dirs → `RuntimeError` naming C8 | no error |
| 20 | LR-5 | `test_up_sets_flags_archive_and_keys_before_the_apps_are_built` — the SDK-replay row-20 set-up (`monkeypatch.delenv` the five key names and the six E14 names; patch `server.require_runtime_extra`, `server._migrate` (async no-op), `server._build_apps` (copy `dict(os.environ)`, then raise a private `_Stop`)); `asyncio.run(server.run(RuntimeConfig(data_dir=tmp_path, runner_config=<tmp url4.toml>)))` under `pytest.raises(_Stop)`. Assert the copy has the two flags `"true"`, the four archive names, and the five key names; `kid` in the `SCOREBOARD_RECEIPT_PUBLIC_KEYS` JSON equals `sha256(b64decode(its value)).hexdigest()[:16]`; `(tmp_path / "cache-version-archive").is_dir()`; `capsys` has no private key text | `run` does not call the hook |
| 21 | LR-6 | `test_local_settings_constructors_leave_e14_fields_to_the_env` — `ast.parse` of `server.py`; in the `Settings(...)` / `GatewaySettings(...)` calls of `_build_apps` and `run_scoreboard`, no keyword is one of `cache_versions_enabled`, `clustering_enabled`, `receipt_signing_key`, `receipt_public_keys`, `replay_grant_*`, `cache_version_archive_*`, `archive_*` | guard row: passes at once; record it in the ledger |

**Task group D — scoreboard chart (write each check in `verify_chart_wiring.py` first, run `python3 .github/scripts/verify_chart_wiring.py`, see the FAIL line, then change the templates). Commit after D.**

| # | Id | Check (in the E14 block) | RED reason |
|---|---|---|---|
| 22 | CH-1 | Default render (`render(SCOREBOARD_CHART, SCOREBOARD_RELEASE)`): ConfigMap has `SCOREBOARD_CLUSTERING_ENABLED == "true"`, `SCOREBOARD_ADMIN_EMAILS == ""`, `SCOREBOARD_RECEIPT_PUBLIC_KEYS == "{}"`, `SCOREBOARD_ARCHIVE_BACKEND == "none"`, `SCOREBOARD_PUBLISH_WORKER_ENABLED == "false"`; no `SCOREBOARD_GITHUB_*` key; no Secret document; the Deployment `envFrom` has no `secretRef`; `SCOREBOARD_AUTH_MODE == "disabled"` (default unchanged) | keys missing |
| 23 | CH-2 | For the default, the prod (`SCOREBOARD_PROD_ARGS`) and the full render (publish on, inline secrets): every `SCOREBOARD_*` key in the ConfigMap and every key of the E14 Secret is in `pydantic_env_names(SCOREBOARD_SETTINGS, "Settings", prefix="SCOREBOARD_")`. WHY: a renamed field would leave the Pod on the code default. | helper missing / keys missing |
| 24 | CH-3 | Prod render: `SCOREBOARD_AUTH_MODE == "cloudflare_headers"`; `SCOREBOARD_ALLOWED_NETWORKS` non-empty; `FORWARDED_ALLOW_IPS != "*"` and `cidr_overlap(FORWARDED_ALLOW_IPS, SCOREBOARD_ALLOWED_NETWORKS) is None` (reuse `:302-331`); no `Ingress` document; the NetworkPolicy has the placeholder peer with `namespaceSelector` AND `podSelector` in ONE `from` element; the Deployment `envFrom` has `secretRef` `scoreboard-e14` | prod file still `disabled` |
| 25 | CH-4 | Refused renders. Each case is `SCOREBOARD_PROD_ARGS` plus the named overrides, so exactly one rule fails (the prod file is otherwise valid). Assert `render_fails(...)` is not None AND contains the quoted value path: (a) `--set config.allowedNetworks=` → `config.allowedNetworks`; (b) `--set config.forwardedAllowIps=*` → `config.forwardedAllowIps`; (c) `--set ingress.enabled=true` → `ingress.enabled`; (d) `--values values-prod.yaml` ALONE (no peer placeholders) → `networkPolicy.clientPodNames`; (e) `--set config.authMode=other` → `config.authMode`; (f) `--set config.authMode=disabled --set config.publish.enabled=true` → `config.publish.enabled`; (g) `--set config.publish.enabled=true --set config.publish.githubAppInstallationId=1 --set config.publish.archive.endpointUrl=http://s3.example:3900` → `config.publish.githubAppId`; (h) as (g) plus `githubAppId=1` and `--set e14Secret.existingSecret=` → `e14Secret.existingSecret`; (i) `--set e14Secret.githubAppPrivateKey=x` → `e14Secret.githubAppPrivateKey`; (j) `--set e14Secret.replayGrantSigningKey=x` → `e14Secret.replayGrantSigningKid`. Each `fail` message in §4.6.3 / §4.6.5 names its value path in that exact spelling. | renders succeed |
| 26 | CH-5 | Full render (`SCOREBOARD_PROD_ARGS`, `--set e14Secret.existingSecret=`, publish on with `githubAppId=1`, `githubAppInstallationId=2`, `archive.endpointUrl=http://s3.example:3900`, all five inline secrets set to `ci-placeholder-…` strings, `githubAppPrivateKey` set with `--set-file e14Secret.githubAppPrivateKey=<tmp>` where `<tmp>` is a `tempfile.NamedTemporaryFile` holding the two-line placeholder text `"line1\nline2"` (no key; not committed), and `--set config.receiptPublicKeys.k1=cHVi`): a Secret `scoreboard-scoreboard-e14` whose `stringData` keys == `E14_SCOREBOARD_SECRET_KEYS`, and whose `SCOREBOARD_GITHUB_APP_PRIVATE_KEY` value == `"line1\nline2"` (the newline survives, §4.6.4); `set(ConfigMap data) & E14_SCOREBOARD_SECRET_KEYS == set()`; `json.loads(SCOREBOARD_RECEIPT_PUBLIC_KEYS) == {"k1": "cHVi"}`; `SCOREBOARD_ARCHIVE_BACKEND == "s3"` with endpoint, bucket `screamingface-cache-versions` and region; the Deployment `envFrom` names that Secret | no Secret template |
| 27 | CH-6 | The scoreboard Pod template has a `checksum/config` annotation, and it changes when `config.clustering.enabled=false` | annotation missing |
| 28 | CH-7 | `cloud_render_flags("charts.yml", "render", "Render the scoreboard prod values") == cloud_render_flags("release-scoreboard.yml", "chart", "Lint and render charts")`, both non-empty, and equal to the `--set` keys of `SCOREBOARD_PROD_ARGS` | step missing |
| 29 | CH-8 | `--set-string config.adminEmails[0]=a@example.com --set-string config.adminEmails[1]=b@example.com` → `SCOREBOARD_ADMIN_EMAILS == "a@example.com,b@example.com"` (a comma list; the field is `NoDecode`, SB-publish §4.1) | key missing |

**Task group E — aigateway chart and lanes. Commit after E.**

| # | Id | Check | RED reason |
|---|---|---|---|
| 30 | CH-9 | Default gateway render: `AIGW_CACHE_VERSIONS_ENABLED == "false"`, `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS == "{}"`, `AIGW_CACHE_VERSION_ARCHIVE_BACKEND == "none"`; no `AIGW_CACHE_VERSION_S3_*` key; no `aigw-aigateway-cache-versions` Secret; no cache-versions `secretRef` | keys missing |
| 31 | CH-10 | Every E14 key the gateway renders (ConfigMap keys that start with `AIGW_CACHE_VERSION`, plus `AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS`, plus the Secret keys) is in `pydantic_env_names(GATEWAY_SETTINGS, "Settings", prefix="AIGW_")`. WHY only the E14 keys: the ConfigMap also has plugin and OTel names that are not `Settings` fields (`configmap.yaml:37, 66-75`). | helper missing |
| 32 | CH-11 | Enabled + `existingSecret=aigw-cache-versions` + `archive.backend=s3` + `archive.endpointUrl=http://s3.example:3900`: ConfigMap has the endpoint, bucket `screamingface-cache-versions`, region `garage`; `set(ConfigMap data) & E14_GATEWAY_SECRET_KEYS == set()`; the Deployment `envFrom` names `aigw-cache-versions`; no chart Secret is rendered | keys missing |
| 33 | CH-12 | Refused: enabled with no key source; `archive.backend=s3` with no endpoint and no bundled Garage; s3 with no credentials source; `archive.backend=filesystem`; s3 with `enabled=false` | renders succeed |
| 34 | CH-13 | Bundled Garage: `snapshot.enabled=true` + cacheVersions enabled + inline key + `archive.backend=s3` + inline archive keys + `config.cacheVersions.archive.readerPeers[0].podSelector.matchLabels.app\.kubernetes\.io/name=scoreboard` (in the Python argv list write the backslashes as `"\\."`: no shell runs, so Helm must get a literal backslash before each dot) → endpoint `http://aigw-aigateway-garage:3900`; the Garage NetworkPolicy `from` has the gateway peer AND the scoreboard peer; the inline Secret `aigw-aigateway-cache-versions` has exactly the three keys | endpoint empty / peer missing |
| 35 | CH-14 | Gateway prod render (`values-prod.yaml`): `AIGW_CACHE_VERSIONS_ENABLED == "true"`, `AIGW_AUTH_MODE == "cloudflare_headers"` (unchanged), `secretRef` `aigw-cache-versions`; the old check "values-prod.yaml also admits the console" still passes | prod not switched |
| 36 | CH-15 | `charts.yml` `on.push.paths` and `on.pull_request.paths` both contain `apps/scoreboard/charts/**`, `apps/scoreboard/src/scoreboard/config.py`, `apps/aigateway/src/aigateway/config.py` and `.github/workflows/release-scoreboard.yml`; the "Lint" step runs `helm lint apps/scoreboard/charts/scoreboard` | paths missing |

**Task group F — docs.** The two `DEPLOYMENT.md` sections (§4.9) and the two chart `README.md` sections. No RED (documentation). Paste the rendered prod ConfigMap of CH-3 (without values that look like keys) in the ledger.

## 7. Edge cases, what not to do, gates

### 7.1 Edge cases

- An admin sets `redistributable=false` on a board with published versions. Existing releases stay (takedown is the withdraw route). New non-owner grants for that board answer 404 (SB-grants reads the column live, RP-2); new publish requests answer 409 `not_publishable` with reason `not_redistributable` (PB-1). Say this in `DEPLOYMENT.md`.
- Two admins set opposite values at once: the last write wins; each call is audited with its outcome.
- A benchmark id with `/` or 65+ chars: the path does not match, or 422. No row is created.
- The scoreboard `disabled` fallback with a forged header: 503 (WR-7).
- `screamingface up` on a data dir from before this unit: the archive dir is created at the next start; old versions (none exist locally before E14) need nothing.
- An operator exports only `SCOREBOARD_ARCHIVE_FS_ROOT`: `RuntimeError` at `up` (LR-3), not a silent split.
- A deploy of the new `values-prod.yaml` before the Secrets exist: the Pods stay in `CreateContainerConfigError` (by design, §4.6.4). For the GATEWAY this stops the whole gateway (every model call of the platform), not only E14: `config.cacheVersions.enabled: true` mounts `aigw-cache-versions`. §9 item 2 comes first, and `DEPLOYMENT.md` says this in bold.
- `helm test` in production: the test Pod (`templates/tests/test-connection.yaml`) carries `app.kubernetes.io/name: scoreboard`, not an Envoy name, so the new NetworkPolicy refuses it and `helm test` fails. This is expected with the verified mode. Do not add the test Pod to the peers (the peers are the identity boundary). Say this in `DEPLOYMENT.md`; run `helm test` only against a dev install (`disabled`).
- A receipt verifier map with no kid yet (prod before §9 item 2): every submit with a receipt answers 422 `unknown_kid` (SB-submit §4.1). A submit without a receipt still works.
- The grant life (D4): a grant lives 12 h; a run that is longer (job deadline 57,600 s plus the queue wait) fails with the RP-14 typed error. Rotation must keep an old grant kid in the gateway map for at least 12 h.

### 7.2 What not to do

- Do not mint key material in Helm (`genPrivateKey`, `randAlphaNum`). A generated receipt key cannot reach the scoreboard, so every receipt would fail (the same reason as `snapshot-secret.yaml:12-17`).
- Do not use `lookup` to keep an inline E14 Secret (`secret-tracing.yaml` WHY: it reverts a rotation).
- Do not put a private value in a ConfigMap, `values*.yaml`, a test fixture, stdout, or a log line.
- Do not print the private key in `keygen` (stdout is public parts only). Do not overwrite a key file. Do not write a key file inside a git work tree (KG-7).
- Do not add an HTTPRoute, a SecurityPolicy, or a Cloudflare object. D5 makes the edge an ops precondition.
- Do not change `require_admin`, the withdraw route, or any SB-publish test.
- Do not change any settings class or any code default (the flags stay off in code; the chart and the local runtime turn them on).
- Do not change `_gateway_config_summary` or the `up` banner (`tests/test_runtime_cli.py:901-916`).
- Do not change the `auth_mode="disabled"` of the local runtime (D5).
- Do not set `AIGW_REQUEST_CACHE_ENABLED` in the hook.
- Do not import `apps/*` in SDK code. Do not import `screamingface` in scoreboard code.
- Do not add a second local key generator (SDK-replay §2.1).
- Do not touch `credential_blobs`, `AIGATEWAY_SECRET_KEY` or an OS keychain.

### 7.3 Gates

```bash
# repo root
uv run .claude/scripts/run_gates.py scoreboard --base "$(git merge-base HEAD e14-reproducible-submission-spec)"
uv run .claude/scripts/run_gates.py screamingface --base "$(git merge-base HEAD e14-reproducible-submission-spec)"
helm lint apps/scoreboard/charts/scoreboard && helm lint apps/scoreboard/charts/db && helm lint apps/aigateway/charts/aigateway
python3 .github/scripts/verify_chart_wiring.py
helm template scoreboard apps/scoreboard/charts/scoreboard --values apps/scoreboard/charts/scoreboard/values-prod.yaml \
  --set 'networkPolicy.clientPodNames[0]=ci-placeholder-envoy' --set networkPolicy.clientNamespace=ci-placeholder-envoy-ns > /dev/null
helm template aigw apps/aigateway/charts/aigateway --values apps/aigateway/charts/aigateway/values-prod.yaml > /dev/null
```

The `aigateway` stack has no Python change in this unit; run its gate once anyway, because `charts.yml` now watches `config.py`: `uv run .claude/scripts/run_gates.py aigateway --base "$(git merge-base HEAD e14-reproducible-submission-spec)"`.

## 8. Verification (definition of done)

1. Every §6 row is green: WR-1..9 (`uv run pytest tests/unit/publish/test_admin_redistributable.py -v` in `apps/scoreboard`), KG-1..7 and LR-1..6 (`uv run pytest tests/test_runtime_keygen.py tests/test_runtime_local_features.py tests/test_runtime_signing_keys.py -v` in `packages/screamingface`), CH-1..15 (the verifier prints `ok` for each, and `chart wiring verified`).
2. Every §7.3 command exits 0. The append-only check passes.
3. The whole old suites stay green: `uv run pytest -q` in `apps/scoreboard` and in `packages/screamingface`; the verifier's old checks all `ok`.
4. In the ledger: the §2 name table with `file:line`; a `keygen` run for both purposes into a temp dir (paste stdout only, and `ls -l` of the file showing `-rw-------`); the rendered prod ConfigMap of both charts (key names and public values only).
5. A manual local check, in the ledger: run `screamingface up`, one evaluation, and one `client.leaderboards.submit(...)` (the SDK freezes first). Then `ls <data_dir>/cache-version-archive/cache-versions/` shows one `<vid>/` with `entries.jsonl.gz` and `manifest.json` (the gateway exporter wrote them), and `stat -f %Lp <data_dir>/cache-version-archive` prints `700`.
6. `git diff --name-only "$(git merge-base HEAD e14-reproducible-submission-spec)"` lists only §3 files.
7. Design review (Opus) with this plan as the rubric, plus the `sf-code-review` security review (key handling, the admin route, the NetworkPolicy and the auth guards). Then commit on `unit/WIRING` for the integrator (D1). No PR.
8. Tell the integrator: merge `unit/WIRING` before `unit/E2E`; then run the E2E lane (E2E Step 1.2 compares its fallback with `LOCAL_E14_FLAGS` and the archive variables of this unit).

## 9. Ops checklist (not code; for `DEPLOYMENT.md` and the release owner)

Do these in order, before the new `values-prod.yaml` files are deployed. None of them is a code task for the implementer. Record each as a checkbox in `apps/scoreboard/DEPLOYMENT.md` "E14 deploy wiring".

1. - [ ] **D5 ingress precondition.** Route the production scoreboard host (`scoreboard.screamingface.ai`) through the Cloudflare Access + Envoy edge, the same chain as the gateway (see `docs/work/2026-08-03-OME-404-authenticated-leaderboard-submissions.md:94-98`). The edge must (a) remove any client `X-User-Email`, (b) inject the verified email, (c) keep anonymous `GET` reads of the public board working (an Access bypass for reads, with the header still removed). Name the Envoy data-plane Pods in `networkPolicy.clientPodNames` / `clientNamespace`, and narrow `config.allowedNetworks` to their Pod CIDR. Prove it: from outside, a `POST /v1/scores` with a forged `X-User-Email` reaches the app with the verified value only; from a non-Envoy Pod in the cluster, the connection is refused (NetworkPolicy) or answers 403 untrusted peer. Only then deploy the scoreboard `values-prod.yaml` (it turns off the Traefik Ingress).
2. - [ ] **Keys.** On an operator machine, OUTSIDE any git checkout (the helper refuses a path in a git work tree): `KEYDIR="$(mktemp -d)"; chmod 700 "$KEYDIR"`; run `keygen --purpose receipt --out "$KEYDIR/receipt.env"` and `keygen --purpose replay-grant --out "$KEYDIR/grant.env"`. Create each Secret with ONE recipe (the same recipe for every later key, items 3 and 4):
   ```bash
   # One file per key; the file name is the env name. WHY: `kubectl --from-env-file` cannot carry a
   # multi-line PEM (item 4), and kubectl refuses `--from-env-file` together with `--from-file`.
   d="$KEYDIR/scoreboard-e14"; mkdir -m 700 "$d"
   while IFS= read -r line; do printf '%s' "${line#*=}" > "$d/${line%%=*}"; done < "$KEYDIR/grant.env"
   kubectl -n <scoreboard-ns> create secret generic scoreboard-e14 --from-file="$d" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```
   Do the same for `Secret/aigw-cache-versions` in the gateway namespace from `receipt.env`. `${line#*=}` keeps the `=` padding of the base64 value. To add a key later, add its file to the same directory and run the same `create … | apply` again (it replaces the whole Secret, so keep every file). Put the two stdout JSON maps into the verifier values through `--set-json` at install time: `--set-json 'config.receiptPublicKeys=<the SCOREBOARD_RECEIPT_PUBLIC_KEYS JSON>'` (scoreboard) and `--set-json 'config.cacheVersions.replayGrantPublicKeys=<the AIGATEWAY_REPLAY_GRANT_PUBLIC_KEYS JSON>'` (gateway), or a private values file that is not in git. Then `rm -rf "$KEYDIR"` when items 3 and 4 are done (keep it only in a secure store if your process needs a copy). Deploy the gateway first, then the scoreboard.
3. - [ ] **Bucket (PB-D8, C8a).** Create the bucket `screamingface-cache-versions`, a writer key for the gateway (read and write on that bucket) and a READ-ONLY key for the scoreboard. On Garage (the key rights are per bucket, not per prefix, so the bucket holds only `cache-versions/`): `garage bucket create screamingface-cache-versions`; `garage key create aigw-cache-versions-writer`; `garage bucket allow --read --write screamingface-cache-versions --key aigw-cache-versions-writer`; `garage key create scoreboard-cache-versions-reader`; `garage bucket allow --read screamingface-cache-versions --key scoreboard-cache-versions-reader`. Check the syntax with `garage --help` of the running version first. Encryption at rest (C8a "server-side encryption is on"): Garage has no SSE-S3, so use an encrypted volume or an S3 service with SSE; record the choice. Add the writer pair to `aigw-cache-versions` (files `AIGW_CACHE_VERSION_S3_ACCESS_KEY`, `AIGW_CACHE_VERSION_S3_SECRET_KEY`) and the reader pair to `scoreboard-e14` (files `SCOREBOARD_ARCHIVE_S3_ACCESS_KEY_ID`, `SCOREBOARD_ARCHIVE_S3_SECRET_ACCESS_KEY`) with the item 2 recipe. On the bundled Garage, run the `garage` commands in the Garage Pod (`kubectl -n <gateway-ns> exec -it statefulset/<release>-aigateway-garage -- /garage …`: the bundled Garage is a StatefulSet named `<fullname>-garage`, and its binary is `/garage`, `garage.yaml:26, 67, 93`). When the scoreboard reads the gateway's bundled Garage, add its Pods to `config.cacheVersions.archive.readerPeers`. Then set gateway `archive.backend: s3` and the endpoint.
4. - [ ] **GitHub App (PB-D7).** Create a GitHub App with `contents: write` on `ScreamingFace/screamingface-cache-versions` only; install it on that one repo. Put the App id and the installation id into `config.publish.githubAppId` / `githubAppInstallationId`, the PEM into `scoreboard-e14` as `SCOREBOARD_GITHUB_APP_PRIVATE_KEY` (item 2 recipe: `cp app.pem "$KEYDIR/scoreboard-e14/SCOREBOARD_GITHUB_APP_PRIVATE_KEY"`, then the same `create … | apply`), and the §9 item 3 endpoint into `config.publish.archive.endpointUrl`. Add the PEM and set `config.publish.enabled: true` in ONE deploy: an App key without the App id is a partial `github_app_*` set, and the scoreboard refuses to start (SB-publish §4.1).
5. - [ ] **Admins.** Set `config.adminEmails` of the scoreboard at install time (`--set-string 'config.adminEmails[0]=…'`). Then set `redistributable` on each board whose licence allows it, with the admin route and a reason that names the licence.
6. - [ ] **Release order (index X-17).** Deploy the gateway, the engine (drained rollout) and the scoreboard before the SDK release that sends the new submit fields.
7. - [ ] **Smoke.** One submit with a receipt through the edge (201 and a `cache_version` in the result), one replay grant (200), one admin `PUT …/redistributable` (200, and the audit line in the scoreboard log).

## 10. Open decisions

None is open for the implementer. The user decisions that this unit applies:

- **X-12 flags off by default — Decided: D6.** The code defaults stay off. The charts emit the flags (gateway prod on; scoreboard clustering on) and `screamingface up` sets both to `true` (§4.5).
- **X-13 who writes `redistributable` — Decided: D6.** The audited admin route of §4.1.
- **X-14 deploy wiring — Decided: D6.** This unit.
- **X-11 production identity — Decided: D5.** The scoreboard `values-prod.yaml` switches to `cloudflare_headers`; the ingress is ops (§9 item 1).
- **Key form and kid — Decided: D7 X-4.** Raw base64; JSON `{kid: b64}` maps; receipt kid derived; grant kid from `SCOREBOARD_REPLAY_GRANT_SIGNING_KID`.
- **No shared package — Decided: D7 X-3.** The key helper is an SDK `_runtime` module on the SDK-replay generator.
- **Grant life — Decided: D4.** 12 h, no refresh; documented in §7.1 and the rotation text.
- **Error body — Decided: D7 X-8.** `coded_error(404, "benchmark_not_found", …)`.

Unit-local, decided (default):

- **OD-W1 — decided (default).** The scoreboard `values-prod.yaml` turns off the Traefik Ingress and requires NetworkPolicy peers, like the gateway chart (`aigateway.validateAuth`, `networkpolicy.yaml:20-35`). WHY: with `cloudflare_headers`, a direct Ingress or an open policy lets any caller forge `X-User-Email`. The public route becomes the Envoy edge (§9 item 1). Deploying this file before item 1 takes the public board offline.
- **OD-W2 — decided (default).** The grant kid is stored in the scoreboard Secret next to the key, and production kids have no prefix.
- **OD-W3 — decided (default).** Production archive `backend: none` and `publish.enabled: false` until §9 items 3 and 4. Freeze and replay work without the bucket (DR-3).
- **OD-W4 — decided (default).** The charts never mint E14 key material.
- **OD-W5 — decided (default).** The charts refuse the `filesystem` archive backend.
- **OD-W6 — decided (default).** The route is `PUT …/redistributable` with `{redistributable, reason}`; the same value again is 200 `changed: false`.
- **OD-W7 — decided (default).** `GET /v1/benchmarks` does not show `redistributable`. The admin route response carries it. A public field is a separate change (an existing test may compare the benchmark JSON exactly).
- **OD-W8 — decided (default).** The gateway's bundled snapshot Garage can serve the cache-versions bucket (endpoint default and `readerPeers`), but the bucket and keys are ops (§9 item 3).
- **OD-W9 — decided (default).** The gateway `values-prod.yaml` turns `config.cacheVersions.enabled` on (capture, freeze and replay in production). It stores prompts and answers of traced runs (a data posture, like the global cache).
- **OD-W10 — decided (default).** `keygen` refuses an `--out` path inside a git work tree (KG-7), and the §9 recipe builds each Secret from one file per key (`--from-file=<dir>`). WHY: `*.env` names other than `.env` / `.env.*` are not git-ignored, and a multi-line PEM cannot ride `--from-env-file`.
- **OD-W11 — decided (default).** Inline chart Secret values render through `toJson`, not `quote` (§4.6.4, §4.7.4), so a multi-line PEM keeps its newlines (CH-5).
