# Plan — GW-capture: the gateway call capture and the five E14 tables (OME-1307, E14b)

- **Spec (rubric):** `docs/spec/2026-09-29-e14-reproducible-submission/` — `prd/cache-version-store.md`
  §3.1 (CV-H1), §3.3 (CV-D1, CV-D5, CV-D8, CV-D11, CV-D13), §4, §7; `erd.md` §3.1–§3.4, §5, §6
  (Gateway); `contracts.md` C9 (capture part), C11.
- **Component:** `apps/aigateway` only.
- **Delivery (D1):** all E14 units land on the one branch `e14-reproducible-submission-spec`.
  There is no per-unit PR, no Linear issue and no per-unit CI merge gate. Build this unit in a
  temporary worktree on branch `unit/GW-capture`, made from the HEAD of the e14 branch:
  `git worktree add .claude/worktrees/unit-GW-capture e14-reproducible-submission-spec` and then,
  in that worktree, `git checkout -B unit/GW-capture e14-reproducible-submission-spec`. Commit on
  `unit/GW-capture` only. After wave 1, the integrator merges the unit branches into the e14
  branch in sequence and runs the gates.
- **Plan:** `docs/plan/2026-09-29-e14-reproducible-submission/GW-capture.md` (this file).
- **Ledger:** `docs/work/2026-09-29-e14-gw-capture.md` (copy `docs/work/TEMPLATE.md`, `ticket: unfiled`).
- **Loop:** `sdlc-python` (ledger → RED → GREEN → gates → commit). Companion skill `tortoise-dev`
  is mandatory for the models and the migration (`.claude/sdlc.local.md`).
- **Wave:** 1 (with SB-schema and URL4-fp). **Size:** 3–4 d.
- **Language:** ASD-STE100.

## 0. Integration notes (D2)

- Shared files with other wave-1 units: none. SB-schema changes `apps/scoreboard` only. URL4-fp
  changes `packages/url4` and one line of `apps/screamingface-engine/uv.lock`.
- Files that later units of this track change after this unit: `core/cache_versions/ports.py`,
  `__init__.py`, `stats.py`, `tests/unit/cache_versions/conftest.py` (GW-freeze appends, then
  GW-replay appends), `config.py`, `main.py`, `routes/chat.py`, `DEPLOYMENT.md`. They are in later
  waves, so they build on the merged result of this unit.
- WIRING (wave 5) owns the aigateway chart. This unit does not change a chart file (D6).

## 1. Scope

### 1.1 Test ids this unit owns

| Id | Test name (exact) | Level |
|---|---|---|
| CV-1 | CHAR `test_the_mvp_has_no_variant_dimension` (it exists; keep it green, do not edit it) | unit |
| CV-2 | CHAR `test_cache_hit_returns_before_credential_resolution` | route (TestClient) |
| CV-3 | `test_capture_failure_does_not_change_chat_response` | route (TestClient) |
| CV-4 | `test_capture_writes_one_row_per_traced_call_with_outcome` | route (TestClient) |
| CV-5 | `test_capture_index_row_is_thin_body_inline_only_for_unstored_and_bypass` | unit |
| CV-6 | `test_untraced_call_writes_no_capture_row` | route (TestClient) |
| CV-24 | `test_prompt_stored_once_per_key_concurrent_first_writes_one_row` | integration (Postgres) |
| CV-26 | `test_streaming_call_captured_as_bypass_without_body` | route (TestClient) |
| CV-28 | `test_operator_prune_keeps_prompts_referenced_by_run_index` | unit (SQLite) + doc check |
| NFR | `test_capture_overhead_p99_is_at_most_5_ms` (capture NFR bench, `prd/cache-version-store.md` §4, `test-plan.md` §5) | integration (Postgres) |

Support tests (no PRD id; they guard the design, they own no PRD row):
`test_migration_0013_cache_versions.py` (the schema), `test_capture_key.py` (key parity),
`test_cache_versions_import_boundary.py` (C11).

### 1.2 Out of scope

- The freeze, the receipt, the archive, the exporter, `POST /v1/cache-versions` (GW-freeze).
- The replay stage, the grant verifier, the version lookup, the `version_hit` write path (GW-replay).
  This unit defines the `version_hit` outcome word only.
- Any change to `request_cache_entries` or to the global cache key (`erd.md` §6 Gateway 2).
- Engine, SDK and scoreboard code.
- Chart, Secret and Garage changes. The `AIGW_CACHE_VERSIONS_ENABLED` chart value, the
  configmap line and the `charts.yml` / `verify_chart_wiring.py` coverage belong to WIRING
  (wave 5, D6). See `WIRING.md`.
- A metrics exporter. The gateway has no metrics stack today (no `prometheus`/OTel metric use
  under `apps/aigateway/src`). This unit counts in process only (§4.6; Decided: D7, X-15).

## 2. Depends on

- **Units:** none (wave 1).
- **Contracts implemented:** C9 capture half (the gateway reads the existing `traceparent`; no new
  request field), C11 row 4 (the chat route reaches capture only through the `CaptureSink` port; no
  provider plugin imports `core.cache_versions`).
- **Contracts consumed:** A1 — the engine forwards `traceparent`
  (`apps/screamingface-engine/src/screamingface_engine/world/connector.py:1061-1078`).
- **Contracts that later units consume from this unit:** the five tables and their models
  (GW-freeze, GW-replay); `CaptureOutcome`, `CaptureSink`, `CaptureKey`, `build_capture_key`
  (GW-replay uses the same key for the replay lookup).

## 3. Files

All paths are relative to the repo root. "Imitate" names the exemplar to copy the shape from.

### 3.1 New files

| Path | Purpose | Imitate |
|---|---|---|
| `apps/aigateway/src/aigateway/core/cache_versions/__init__.py` | Re-export the port names only (`CaptureSink`, `CaptureRecord`, `CaptureOutcome`, `CaptureKey`, `CaptureStats`, `build_capture_key`, `capture_record`). No adapter, no model. | `apps/aigateway/src/aigateway/core/request_cache/__init__.py:1-19` |
| `apps/aigateway/src/aigateway/core/cache_versions/ports.py` | The port Protocols and value types (§4.2). A leaf: it imports no Tortoise and nothing from `plugins`. | `apps/aigateway/src/aigateway/core/cache_ports.py:1-100` (leaf rule), `core/request_cache/store.py:85-94` (Protocol) |
| `apps/aigateway/src/aigateway/core/cache_versions/capture_key.py` | Pure `build_capture_key` (§4.3). | `apps/aigateway/src/aigateway/core/request_cache/global_plan.py:54-142` |
| `apps/aigateway/src/aigateway/core/cache_versions/capture.py` | Pure `capture_record` mapper (§4.4). | `core/request_cache/global_plan.py` (pure, total) |
| `apps/aigateway/src/aigateway/core/cache_versions/capture_store.py` | Adapter `TortoiseCaptureSink` (§4.5). | `apps/aigateway/src/aigateway/core/request_cache/store.py:103-288` |
| `apps/aigateway/src/aigateway/core/cache_versions/stats.py` | `CaptureStats` in-process counters (§4.6). | none (a plain dataclass) |
| `apps/aigateway/src/aigateway/core/cache_versions/maintenance.py` | `PRUNE_ORPHAN_PROMPTS_SQL` and `prune_orphan_prompts()` (§4.7). | `core/request_cache/store.py:138-141` (`delete_expired`) |
| `apps/aigateway/src/aigateway/core/cache_versions/models/__init__.py` | `__models__` list of the five models. | `apps/aigateway/src/aigateway/core/secrets/models/__init__.py` |
| `apps/aigateway/src/aigateway/core/cache_versions/models/capture.py` | `RequestCachePrompt`, `CacheCaptureEntry`. | `core/request_cache/models/request_cache_entry.py:1-39` |
| `apps/aigateway/src/aigateway/core/cache_versions/models/version.py` | `CacheVersion`, `CacheVersionBlob`, `CacheVersionEntry`. | same |
| `apps/aigateway/src/aigateway/migrations/0013_cache_versions.py` | One migration, five `CreateModel` (§5). | `apps/aigateway/src/aigateway/migrations/0012_provider_credential_slots.py:1-87` |
| `apps/aigateway/src/aigateway/routes/chat_capture_stage.py` | Route-facing helpers `begin_capture`, `record_capture` (§4.8). Never raises. | `apps/aigateway/src/aigateway/routes/chat_cache_stage.py:263-373` |
| `apps/aigateway/tests/unit/cache_versions/__init__.py` | empty | `tests/unit/huggingface/__init__.py` |
| `apps/aigateway/tests/unit/cache_versions/conftest.py` | fixtures `_versions_env`, `capture_client`, helper `traceparent(trace_id)` | `tests/unit/test_chat_global_cache_route.py:113-127` |
| `apps/aigateway/tests/unit/cache_versions/test_capture_char.py` | CV-2 | `tests/unit/huggingface/test_huggingface_route_global_cache.py:162-200` |
| `apps/aigateway/tests/unit/cache_versions/test_capture_route.py` | CV-3, CV-4, CV-6, CV-26 | `tests/unit/test_chat_global_cache_route.py:34-127, 317-331` |
| `apps/aigateway/tests/unit/cache_versions/test_capture_record.py` | CV-5 | plain pytest parametrize |
| `apps/aigateway/tests/unit/cache_versions/test_capture_key.py` | support: key parity | `tests/unit/test_global_cache_plan.py` |
| `apps/aigateway/tests/unit/cache_versions/test_prompt_prune.py` | CV-28 | `tests/unit/test_chat_global_cache_route.py` (SQLite via `client`) |
| `apps/aigateway/tests/unit/cache_versions/test_cache_versions_import_boundary.py` | support: C11 | `tests/unit/core/provider_access/test_provider_access_import_boundary.py:1-80` |
| `apps/aigateway/tests/unit/test_migration_0013_cache_versions.py` | support: migration | `tests/unit/test_migration_0012_provider_credential_slots.py` |
| `apps/aigateway/tests/integration/test_cache_capture_postgres.py` | CV-24 | `tests/integration/test_global_cache_store_postgres.py:143-150` (skip gate + container) |
| `apps/aigateway/tests/integration/test_capture_overhead_postgres.py` | NFR bench | same |

### 3.2 Changed files

| Path | Change |
|---|---|
| `apps/aigateway/src/aigateway/config.py` | Add `cache_versions_enabled` (§4.1) after `request_cache_max_response_bytes` (line 141-143). |
| `apps/aigateway/src/aigateway/db.py` | Add `"aigateway.core.cache_versions.models"` to `TORTOISE_CONFIG["apps"]["models"]["models"]` (line 19-26), in alphabetical order. |
| `apps/aigateway/src/aigateway/main.py` | In `create_app`, after `app.state.tavily_retrieval_cache_store = …` (line 428): `app.state.capture_sink = TortoiseCaptureSink()` and `app.state.capture_stats = CaptureStats()`. Import the adapter from `core.cache_versions.capture_store` (main is the composition root; it may import adapters). |
| `apps/aigateway/src/aigateway/routes/chat.py` | Insert the capture hooks (§4.9). No other change. |
| `apps/aigateway/charts/aigateway/*` | No change in this unit. WIRING (D6) adds `config.cacheVersions.enabled` and the `AIGW_CACHE_VERSIONS_ENABLED` configmap line. |
| `apps/aigateway/DEPLOYMENT.md` | Add a "Cache versions: capture" section after the prune text (line 313-339): what capture stores, that it is kept forever, the `PRUNE_ORPHAN_PROMPTS_SQL` statement (verbatim), and that a cache prune must run it. |
| `apps/aigateway/CHANGELOG.md` | Do not edit. release-please owns it. |

## 4. Signatures and data shapes

### 4.1 Settings (`config.py`)

```python
cache_versions_enabled: bool = Field(default=False, validation_alias="AIGW_CACHE_VERSIONS_ENABLED")
```
Docstring: "E14 kill switch. On: the chat route captures traced calls, and (from GW-freeze) the
freeze route answers. Off: no capture row, no prompt row; `POST /v1/cache-versions` answers
`503 capture_disabled`." Default `False` for the same data-posture reason as
`request_cache_enabled` (`config.py:125-134`). Decided (default): OD-1. WIRING (D6) turns the
flag on in the charts and in the local runtime `screamingface up`.

### 4.2 Ports and value types (`core/cache_versions/ports.py`)

```python
CaptureOutcome = Literal["hit", "stored", "unstored", "bypass", "version_hit", "error"]
CAPTURE_OUTCOMES: Final[frozenset[str]] = frozenset(get_args(CaptureOutcome))
INLINE_OUTCOMES: Final[frozenset[str]] = frozenset({"unstored", "bypass", "version_hit"})

@dataclass(frozen=True, slots=True)
class CaptureKey:
    key_hash: str       # 64 lowercase hex; equals the global cache key for the same body
    material: str       # the canonical key material (prompt text). Never logged. Never in a repr.
    def __repr__(self) -> str: ...  # returns f"CaptureKey(key_hash={self.key_hash[:12]}…)"

@dataclass(frozen=True, slots=True)
class CaptureRecord:
    account_id: str
    trace_id: str                   # 32 lowercase hex
    outcome: CaptureOutcome
    key_hash: str | None            # None only when the call has no capture key (see §4.3)
    request_material: str | None    # None exactly when key_hash is None
    response_json: str | None       # compact JSON text; set only for INLINE_OUTCOMES with a key

class CaptureSink(Protocol):
    async def record(self, record: CaptureRecord) -> None: ...
    # May raise. The route helper (§4.8) owns the never-raise rule.
```

### 4.3 Capture key (`core/cache_versions/capture_key.py`) — pure, total

```python
def build_capture_key(*, body: dict[str, Any], plugin: ProviderPluginBase) -> CaptureKey | None
```
Steps, in this order:
1. `plan = build_global_cache_plan(body=body, plugin=plugin, controls=GlobalCacheControls(participate=True), cache_enabled=True)`
   (`core/request_cache/global_plan.py:54`). This reuses every eligibility gate of the live cache,
   but ignores the operator switch and the caller opt-out. WHY: an opted-out call (`use-cache: false`)
   must still have a key (CV-H1 puts its prompt in `RequestCachePrompt`), and capture must work when
   the live cache is off (local mode).
2. If `plan` is a `CacheBypass`, return `None`.
3. Fetch `rules = tuple(plugin.chat_parameter_rules(model=str(body["model"]), auth_type=None))` and
   `modes = tuple(plugin.available_auth_modes())` again (the plan does not return them), then
   `dto = build_global_cache_key_dto(provider=plugin.custom_llm_provider, body=body, rules=rules,
   projection=plugin.global_cache_projection, provider_auth_modes=modes)`
   (`core/request_cache/global_keys.py:218`). Wrap steps 3–4 in `try/except Exception: return None`.
4. `material = canonical_key_material(dto)` (`global_keys.py:198`). NOTE: the docstrings of
   `canonical_key_material` (`global_keys.py:198-203`) and `canonical_material` (`canonical.py:87-92`) say
   "never persisted". E14 persists this material in `request_cache_prompt` on purpose (`erd.md` §3.1). Do NOT
   edit those two files. State the exception in the `capture_key.py` module docstring, with the `erd.md` §3.1
   reference.
5. If `hashlib.sha256(material.encode("utf-8")).hexdigest() != plan.key_hash`: log a warning with the
   12-char key prefix only and return `None` (defence: the key and the prompt must describe one call).
6. Return `CaptureKey(key_hash=plan.key_hash, material=material)`.

It never raises. It performs no I/O. It reads no account, profile or credential.

Consequence (state it in the module docstring): a provider without a global-cache projection
(the base default is `CacheBypass`, `core/plugin_base/_provider.py:206-276`: gemini, codex,
antigravity, ollama today), a streaming body (`BYPASS_STREAM`), and every other unkeyable body get
no capture key. Such a call still gets a capture row with `key_hash = NULL`, and GW-freeze counts it
as missing. See OD-2 and spec gap SG-1.

### 4.4 Record mapper (`core/cache_versions/capture.py`) — pure

```python
def capture_record(
    *, account_id: str, trace_id: str, outcome: CaptureOutcome,
    key: CaptureKey | None, response: object | None,
) -> CaptureRecord
```
Rules:
- `key_hash`, `request_material` = `key.key_hash`, `key.material` when `key` is not `None`, else `None`.
- `response_json` = `json.dumps(response, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`
  ONLY when `outcome in INLINE_OUTCOMES` AND `key is not None` AND `isinstance(response, dict)`.
  In every other case `None`. A `TypeError`/`ValueError` from `json.dumps` propagates (the route
  helper counts it as a capture failure).
- `outcome` not in `CAPTURE_OUTCOMES` raises `ValueError` (a programming error; tests pin it).

### 4.5 Adapter `TortoiseCaptureSink` (`core/cache_versions/capture_store.py`)

```python
class TortoiseCaptureSink:
    async def record(self, record: CaptureRecord) -> None:
        if record.key_hash is not None and record.request_material is not None:
            await RequestCachePrompt.bulk_create(
                [RequestCachePrompt(key_hash=record.key_hash, request_json=record.request_material)],
                ignore_conflicts=True,
            )
        await CacheCaptureEntry.create(
            account_id=record.account_id, trace_id=record.trace_id, key_hash=record.key_hash,
            outcome=record.outcome, response_json=record.response_json,
        )
```
- No `in_transaction()` around the two statements. WHY: same reason as the route note at
  `routes/chat.py:347-349` — a failed statement inside a transaction poisons it on Postgres. Two
  autocommit statements are safe: a prompt row without a capture row is harmless (I-P1).
- `ignore_conflicts=True` renders `ON CONFLICT DO NOTHING` (Postgres) and `INSERT OR IGNORE`
  (SQLite). First, read `tortoise/queryset.py` `BulkCreateQuery` in the installed Tortoise 1.1.8 and
  confirm the flag exists. If it does not exist, STOP and ask; do not write raw SQL on your own.

### 4.6 Stats (`core/cache_versions/stats.py`)

```python
@dataclass
class CaptureStats:
    rows: collections.Counter[str] = field(default_factory=collections.Counter)  # by outcome
    failures: int = 0
```
Names map to the PRD metrics `aigw_capture_rows_total{outcome}` and `aigw_capture_failures_total`.
The counters stay in process. No exporter, no route (Decided: D7, X-15).

### 4.7 Prune (`core/cache_versions/maintenance.py`)

```python
PRUNE_ORPHAN_PROMPTS_SQL: Final = (
    "DELETE FROM request_cache_prompt "
    "WHERE NOT EXISTS (SELECT 1 FROM cache_capture_entry c WHERE c.key_hash = request_cache_prompt.key_hash) "
    "AND NOT EXISTS (SELECT 1 FROM request_cache_entries e WHERE e.key_hash = request_cache_prompt.key_hash)"
)
async def prune_orphan_prompts() -> int  # runs the statement on the "default" connection; returns rows deleted
```
Use `tortoise.connections.get("default").execute_query(PRUNE_ORPHAN_PROMPTS_SQL)`; return the row count
from the result tuple. The SQL must run unchanged on SQLite and Postgres. DEPLOYMENT.md shows the same
string. Note in the docstring: capture writes a prompt only together with a capture row, so in normal
operation this deletes nothing; it exists so a manual cleanup cannot delete a prompt that a later freeze
needs (CV-D13).

### 4.8 Route helper (`routes/chat_capture_stage.py`)

```python
@dataclass(frozen=True, slots=True)
class CaptureContext:
    account_id: str
    trace_id: str
    key: CaptureKey | None

def begin_capture(request: Request, *, account_id: str, body: dict[str, Any], plugin: ProviderPluginBase) -> CaptureContext | None
async def record_capture(request: Request, ctx: CaptureContext | None, outcome: CaptureOutcome, *, response: object | None = None) -> None
```
- `begin_capture`: return `None` when `request.app.state.settings.cache_versions_enabled` is false, or
  when `parse_trace_id(request.headers.get("traceparent"))` (`w3c_trace.py:41-53`) is `None`.
  INVARIANT: use the INBOUND header only. Do NOT use `request.state.trace_id`: the call-id middleware
  MINTS a trace id for an untraced call (`middleware/call_id.py:82-83`), and capture must not record an
  untraced call (CV-D5). Wrap `build_capture_key` in `try/except Exception` → key `None` (defence).
- `record_capture`: `ctx is None` → return. Else build the record with `capture_record(...)` and
  `await request.app.state.capture_sink.record(rec)`. Catch `Exception`: log
  `"cache capture failed (%s) trace=%s…"` with the exception TYPE NAME and the first 8 chars of the
  trace id only, increment `capture_stats.failures`, return. On success increment
  `capture_stats.rows[outcome]`. It never raises. It never logs the prompt, the response or the key
  material.

### 4.9 Chat route hooks (`routes/chat.py`)

Exact insertion points (line numbers at plan time; the e14 branch has the same `routes/chat.py`
as `origin/main`. Find each anchor by its text if a line moved):
1. After `accounting = (...)` (line 322-326): compute
   `capture = begin_capture(request, account_id=str(current.id), body=body, plugin=plugin)`. Use
   `str(current.id)` here. Do NOT move the existing `account_id = str(current.id)` line (line 345). Place it
   directly before the `STAGE 1` banner (line 328). `body` here is the hardened body that the live key
   also uses (line 343-344 invariant).
2. Wrap everything from `STAGE 1` (line 350) to the end of the function in
   `try: … except Exception: await record_capture(request, capture, "error"); raise`.
   WHY `Exception` and not only `HTTPException`: the route can also raise
   `CredentialBlobMutationConflict` (it has its own handler, `main.py:376`). Every failed call must get an
   `error` row. Do not catch `BaseException` (a cancellation must not write a row).
   Put the body of the `try` in a new private coroutine `_serve_after_capture_start(...)` if the
   function passes the ruff complexity limits otherwise (`pyproject.toml` `max-statements = 76`,
   `max-branches = 24`). Keep the statement order unchanged.
3. Hit return (line 365-380): before `return attach_hit_metadata(...)`, call
   `await record_capture(request, capture, "hit")`.
4. Streaming return (line 463-474): before `return StreamingResponse(...)`, call
   `await record_capture(request, capture, "bypass")` (no response; CV-D8). The key is `None` here
   anyway, because `stream: true` is a key bypass.
5. After STAGE 3 (line 498-503), before the `if not isinstance(result, dict)` line:
   - `write_status == "stored"` → outcome `"stored"`, no response;
   - `write_status in ("race_lost", "not_stored")` → outcome `"unstored"`, `response=result`;
     WHY `race_lost` is `unstored`: the live row then holds the OTHER caller's answer, not this call's;
   - `cache_outcome.status == "bypass"` (so `write_status is None`) → outcome `"bypass"`, `response=result`.
   Pass `result` BEFORE `attach_success_metadata` (the provider-compatible form that the cache stores).
6. Do NOT move any existing statement. Do NOT add a credential read, a Profile read or an
   `in_transaction()`. The hit path must stay credential-free (CV-2).

## 5. Migrations

- The highest migration today is `apps/aigateway/src/aigateway/migrations/0012_provider_credential_slots.py`.
- This unit adds exactly one: **`apps/aigateway/src/aigateway/migrations/0013_cache_versions.py`**,
  `dependencies = [("models", "0012_provider_credential_slots")]`. Expand-only: five `CreateModel`, no
  change to any existing table. GW-freeze and GW-replay add no migration (this is the gateway
  schema-foundation unit).
- Generate it with `uv run python -m tortoise -c aigateway.db.TORTOISE_CONFIG makemigrations -n cache_versions models`,
  then edit it to the shape below, like 0012 did (`bases=["Model"]`; drop any unrelated autodetector
  proposal, for example the known `OAuthConnection.account` `AlterField` drift, 0012 docstring).
- Module docstring: UPGRADE (five `CREATE TABLE`, no existing table touched), DOWNGRADE (drop exactly
  the five tables, reverse dependency order), ROLLBACK note, WHY TEXT and not JSONB (OD-3), WHY the
  capture PK is a BIGINT (OD-4).

Tables (column order = model field order):

| Table / model | Columns | Keys and indexes |
|---|---|---|
| `request_cache_prompt` / `RequestCachePrompt` | `key_hash CHAR(64)`, `request_json TEXT NOT NULL`, `created_at TIMESTAMPTZ auto_now_add` | PK `key_hash` (`fields.CharField(max_length=64, primary_key=True)`) |
| `cache_capture_entry` / `CacheCaptureEntry` | `ordinal BIGINT` (generated), `account_id VARCHAR(64)`, `trace_id VARCHAR(32)`, `key_hash VARCHAR(64) NULL`, `outcome VARCHAR(16)`, `response_json TEXT NULL`, `created_at` | PK `ordinal` (`fields.BigIntField(primary_key=True)`); index `("account_id", "trace_id", "ordinal")`; index `("key_hash",)` (for the prune anti-join) |
| `cache_version` / `CacheVersion` | `id UUID`, `owner_account_id VARCHAR(64)`, `trace_id VARCHAR(32)`, `status VARCHAR(16) default "frozen"`, `entry_count INT`, `call_count INT`, `missing_count INT`, `coverage_status VARCHAR(16)`, `archive_sha256 VARCHAR(64)`, `archive_key VARCHAR(256)`, `created_at` | PK `id`; `unique_together (("owner_account_id", "trace_id"),)`; index `("status", "created_at")` (exporter outbox) |
| `cache_version_blob` / `CacheVersionBlob` | `sha256 VARCHAR(64)`, `request_json TEXT`, `response_json TEXT`, `metadata_json TEXT NULL`, `size_bytes INT` | PK `sha256` |
| `cache_version_entry` / `CacheVersionEntry` | `id UUID`, `version_id UUID` FK → `cache_version.id` (`on_delete=RESTRICT`), `key_hash VARCHAR(64)`, `blob_sha256 VARCHAR(64)` FK → `cache_version_blob.sha256` (`on_delete=RESTRICT`), `first_ordinal BIGINT` | PK `id`; `unique_together (("version_id", "key_hash", "blob_sha256"),)` (this index also serves the replay lookup by `(version_id, key_hash)`) |

Model names in code: `version = fields.ForeignKeyField("models.CacheVersion", source_field="version_id", related_name="entries", on_delete=fields.RESTRICT)`,
`blob = fields.ForeignKeyField("models.CacheVersionBlob", source_field="blob_sha256", to_field="sha256", related_name="entries", on_delete=fields.RESTRICT)`.
Attribute names (Tortoise names an FK attribute `<field>_id`; `source_field` sets only the DB column): the
Python attributes are `version_id` and `blob_id`; the DB columns are `version_id` and `blob_sha256`. Create an
entry with `CacheVersionEntry(version_id=…, blob_id=<sha>, …)` and order or filter by `blob_id` in Python code.
Deviations from `erd.md` §3 (each is a decided default in §9, and the migration docstring states it):
TEXT instead of JSONB (OD-3); `CacheCaptureEntry` has a BIGINT `ordinal` PK instead of a UUID `id`
plus `ordinal` (OD-4); `key_hash` is NULL for an unkeyable call (OD-2); `CacheVersionEntry` has a UUID
surrogate PK plus a unique index, because Tortoise 1.1.8 has no composite PK (0012 docstring).

Verify by hand (CI does not run migrations on SQLite for every test; see the OME-1325 plan step 3):
apply 0013 to a fresh SQLite file and to the Postgres testcontainer (the migration test does both).

## 6. TDD order (RED first, risk order)

Scaffold first so that each RED fails on an assertion, not on an import: create the empty package,
the five models, the migration, `CaptureStats`, and stubs — `build_capture_key` returns `None`,
`capture_record` raises `NotImplementedError`, `TortoiseCaptureSink.record` does nothing,
`begin_capture` returns `None`, `record_capture` does nothing, `prune_orphan_prompts` returns `0`.
Wire `app.state.capture_sink` / `capture_stats` in `main.py`. Commit the scaffold with the ledger.

Shared arrangement in `tests/unit/cache_versions/conftest.py`: fixture `_versions_env(monkeypatch)`
sets `AIGW_CACHE_VERSIONS_ENABLED=true` and `AIGW_REQUEST_CACHE_ENABLED=true`; fixture
`capture_client(_versions_env, client)` logs in as admin (copy `test_chat_global_cache_route.py:113-127`).
The env fixture MUST come before `client` in the parameter list (the app reads Settings when `client`
builds it). Import `_arrange_account`, `_chat_body`, `_DispatchCounter`, `_PATCH_TARGET` from
`tests.unit.test_chat_global_cache_route` (precedent: `tests/unit/test_cache_hit_contract_fixture.py:34-39`).
`traceparent(t) -> str` returns `f"00-{t}-{'a'*16}-01"`. A sync TestClient test reads or writes the
models through `client.portal.call(...)` (precedent: `tests/unit/test_chat_global_cache_route.py:62-64`);
never call an ORM coroutine directly from a sync test.

| Step | Id | File :: test | RED reason (the assertion that fails before GREEN) | GREEN |
|---|---|---|---|---|
| 0 | CV-1 | `tests/unit/test_global_cache_key.py::test_the_mvp_has_no_variant_dimension` | CHAR: it passes now and must pass after every step. | none |
| 1 | CV-2 | `test_capture_char.py::test_cache_hit_returns_before_credential_resolution` | CHAR: passes now. Arrange: account with an Anthropic connection; traced miss fills the row; then a traced identical request with `ORMStore.read` recorded (`huggingface/test_huggingface_route_global_cache.py:171-200` pattern). Assert: `X-AIGW-Cache: hit`, dispatch count 1, no `aigateway:anthropic:*` read on the hit, and a control that the miss did read one. | none; it must stay green after step 6 |
| 2 | support | `tests/unit/test_migration_0013_cache_versions.py` (tests: `test_0013_creates_the_five_tables_on_a_populated_database`, `test_0013_capture_key_hash_is_nullable`, `test_0013_version_is_unique_per_owner_and_trace`, `test_0013_downgrade_drops_only_the_five_tables`, `test_autodetector_proposes_no_cache_version_change`) | Before the migration file is final, the table/column/nullable/unique assertions fail. | finish 0013 |
| 3 | CV-3 | `test_capture_route.py::test_capture_failure_does_not_change_chat_response` | Set `capture_client.app.state.capture_sink = _RaisingSink()` (its `record` raises `RuntimeError`). One traced miss with `_DispatchCounter` patched at `_PATCH_TARGET`. Assert: status 200; `body["choices"][0]["message"]["content"] == "PLAINTEXT-ANSWER-42"` (the dispatched answer); headers `X-AIGW-Cache: miss` and `X-AIGW-Cache-Write: stored` (the same as without capture); `app.state.capture_stats.failures == 1`; zero `CacheCaptureEntry` rows. Fails on `failures == 1` (0: the route calls no sink yet). | §4.8 `record_capture` try/except + §4.9 step 5 |
| 4 | CV-6 | `test_capture_route.py::test_untraced_call_writes_no_capture_row` (parametrize: header absent, `"garbage"`, all-zero trace id, uppercase hex, version `01`) | Positive control inside the test: the same request with a VALID traceparent makes `CacheCaptureEntry.filter(trace_id=T).count() == 1`. Fails on the control (0 rows). The negative cases must give 0 rows. | §4.8 `begin_capture` |
| 5 | CV-5 | `test_capture_record.py::test_capture_index_row_is_thin_body_inline_only_for_unstored_and_bypass` (parametrize over the six outcomes × key present/absent) | `capture_record` raises `NotImplementedError`. Parametrize over the FIVE outcomes `hit`, `stored`, `unstored`, `bypass`, `error` (do NOT include `version_hit`: it is in `INLINE_OUTCOMES` by OD-7, and GW-replay asserts it). Oracle: body only for `unstored` and `bypass` with a key; no field ever holds prompt text except `request_material`; `response_json` is compact JSON. Also `test_capture_record_rejects_an_unknown_outcome`. | §4.4 |
| 6 | support | `test_capture_key.py` (`test_capture_key_equals_the_global_cache_key`, `test_an_opted_out_body_still_has_a_capture_key`, `test_a_non_participating_provider_has_no_capture_key`, `test_a_streaming_body_has_no_capture_key`, `test_capture_key_repr_hides_the_material`). Use `aigateway.plugins.anthropic_provider.plugin.PLUGIN` (a participating provider, projection at `plugin.py:190`), `aigateway.plugins.gemini_provider.plugin.PLUGIN` (no projection) and a plain body. | The stub returns `None`, so the key-equality and opt-out tests fail on `is not None`. (The two `None` tests pass at once; that is accepted, because the paired positive tests were red.) | §4.3 |
| 7 | CV-4 | `test_capture_route.py::test_capture_writes_one_row_per_traced_call_with_outcome` | Arrange: an UNTRACED call fills body H in the live cache. Then, with trace T: H (hit), S (miss → stored), B with `{"cache": {"use-cache": false}}` (bypass). Assert 3 rows ordered by `ordinal` with outcomes `["hit", "stored", "bypass"]`; only the `bypass` row has `response_json` (equal to the dispatched answer); 3 `RequestCachePrompt` rows, one per distinct `key_hash`; each prompt `request_json` hashes (sha256) to its `key_hash`; the `hit` and `stored` rows' `key_hash[:12]` equals the response header `X-AIGW-Cache-Key`. Fails: 0 rows (sink stub). | §4.5, §4.9 steps 1–5 |
| 8 | CV-26 | `test_capture_route.py::test_streaming_call_captured_as_bypass_without_body` | Patch `aigateway.routes.chat._stream` to an async generator that yields one SSE chunk; send `stream: true` with trace T. Assert one row: outcome `bypass`, `key_hash is None`, `response_json is None`; no `RequestCachePrompt` row. Fails before §4.9 step 4 (0 rows). | §4.9 step 4 |
| 9 | CV-28 | `test_prompt_prune.py::test_operator_prune_keeps_prompts_referenced_by_run_index` | Seed prompt P1 (referenced by a capture row, no live row), P2 (no capture row, no live row), P3 (no capture row, has a live row). Run `prune_orphan_prompts()`. Assert P1 and P3 stay, P2 is gone, return value 1. Fails: stub returns 0 and deletes nothing. Second test `test_deployment_doc_shows_the_prune_statement_verbatim`: `PRUNE_ORPHAN_PROMPTS_SQL in DEPLOYMENT.md text`. | §4.7 + DEPLOYMENT.md |
| 10 | CV-24 | `tests/integration/test_cache_capture_postgres.py::test_prompt_stored_once_per_key_concurrent_first_writes_one_row` | Postgres container, `migrate` to head (copy `_migrate` from `test_global_cache_store_postgres.py`). `asyncio.gather` of 10 `TortoiseCaptureSink().record(...)` with one `key_hash`. Assert 1 prompt row, 10 capture rows, no exception. RED: run it against the step-0 scaffold sink (0 rows) — record the red run in the ledger. | §4.5 |
| 11 | support | `test_cache_versions_import_boundary.py::test_no_plugin_imports_cache_versions`, `::test_only_the_composition_root_imports_cache_version_adapters` | AST walk of `src/aigateway/` through a helper `_violations(root: Path) -> list[str]`. Rule 1: no file under `plugins/` imports `aigateway.core.cache_versions` (absolute or relative). Rule 2: outside `core/cache_versions/` and `main.py`, a module may import only `aigateway.core.cache_versions` (the package) or `aigateway.core.cache_versions.ports`; never `.models`, `.capture_store`, `.maintenance`, or a later adapter module. Rule 3: no file under `core/cache_versions/` imports `aigateway.plugins` or `aigateway.routes`. RED proof: a third test `test_the_boundary_check_finds_a_planted_violation` runs `_violations` on a `tmp_path` tree that holds one banned import and asserts one violation. Write it first; it fails while `_violations` returns `[]`. | `_violations` |
| 12 | NFR | `tests/integration/test_capture_overhead_postgres.py::test_capture_overhead_p99_is_at_most_5_ms` | On Postgres: time 1,000 `record_capture` calls (keyed, half with inline bodies of 4 KB) and 1,000 no-op calls (`ctx=None`). `record_capture` reads only `request.app.state`, so pass `types.SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(capture_sink=TortoiseCaptureSink(), capture_stats=CaptureStats())))` as the request. Mark the module `pytestmark = pytest.mark.needs_postgres` and skip unless `AIGW_TEST_PG=1` (exemplar `test_global_cache_store_postgres.py:47,146-147`). Assert `p99(with) - p99(without) <= 5 ms`. RED: none possible for a budget test; record the measured numbers in the ledger. | none, or tune §4.5 |

## 7. Edge cases, what not to do, gates

### 7.1 Edge cases

- `use-cache: false`: key exists (§4.3), outcome `bypass`, body inline (CV-H1).
- Live cache off (`AIGW_REQUEST_CACHE_ENABLED=false`): every call is `bypass` with an inline body.
- Live cache read failure (`cache_unavailable`): outcome `bypass`, body inline.
- `race_lost` and `not_stored`: outcome `unstored`, body inline (§4.9 step 5).
- A call that fails with `HTTPException` after `begin_capture`: outcome `error`, no body. This includes
  a credential refusal (404/409/401) and a dispatch failure.
- A request that fails BEFORE `begin_capture` (bad JSON, no provider prefix, unknown provider): no row.
  That is correct: such a call has no provider answer to replay.
- Identity (D5). In production the gateway runs `AIGW_AUTH_MODE=cloudflare_headers`
  (`charts/aigateway/values-prod.yaml:18`). The account is the one that the verified
  `X-User-Email` gives (`core/auth/cloudflare_identity.py`, username = the lowercased email), so each
  verified user has a separate capture scope. `current.id` in §4.9 step 1 is that account. The
  capture code reads no identity header itself; it uses `current` only.
- `auth_mode=disabled` is a dev/local fallback only: every caller is the anonymous account
  `00000000-…` (`core/auth/middleware.py:19`), so all traces share one account scope. Keep that
  behaviour. State it in DEPLOYMENT.md. Do not design for it as a production path.
- Two identical calls in one run: two rows, one prompt (CV-D11).
- A prompt larger than any bound: no cap in v1 (the live cache caps the response only). Note it in the
  ledger; do not invent a cap.

### 7.2 What not to do

- Do not change `request_cache_entries`, `GlobalCacheKeyResult`, `build_global_cache_plan`,
  `global_keys.py` or the reason vocabulary. The key has no version dimension (DR-1, CV-1).
- Do not edit any existing test file (the append-only gate fails). Only add new test files.
- Do not import `aigateway.core.cache_versions` from any file under `plugins/`. The core never imports
  plugins; `core/cache_versions/` imports nothing from `aigateway.plugins`.
- Do not log a prompt, a response, the key material or a full key hash. A 12-char prefix only.
- Do not use `request.state.trace_id` (it can be minted). Parse the inbound `traceparent`.
- Do not wrap capture in `in_transaction()`. Do not let a capture failure change the response.
- Do not touch `credential_blobs`, `ORMStore`, `AIGATEWAY_SECRET_KEY`, or any OS keychain API.
- Do not import across apps (no `screamingface_engine`, no `scoreboard`, no `url4`; `w3c_trace.py:8-12`
  records that aigateway does not depend on `url4`).
- Do not add a metrics library.

### 7.3 Gates (from `.claude/sdlc.local.md`, stack `aigateway`)

```bash
cd apps/aigateway
uv run ruff check
uv run ruff format --check
uv run pyright
uv run python scripts/check_no_enterprise.py
uv run pytest --cov=aigateway --cov-fail-under=80 -q -m "not live and not needs_postgres"
AIGW_TEST_PG=1 uv run pytest -m needs_postgres -v
cd ../.. && uv run .claude/scripts/run_gates.py aigateway --base e14-reproducible-submission-spec
```

The `--base` is the e14 branch, not `origin/main` (D1): the append-only check must see only
this unit's change.

## 8. Verification and "done"

Done means all of these are true:
1. Every row of §1.1 is green; CV-1 and CV-2 were never red.
2. The append-only check passes (no existing test file changed).
3. `AIGW_TEST_PG=1 uv run pytest -m needs_postgres` is green, and it includes the 0013 upgrade and
   downgrade on Postgres (add `test_0013_upgrades_and_downgrades_on_postgres` to
   `tests/integration/test_cache_capture_postgres.py`, imitating
   `tests/integration/test_tortoise_migration_smoke.py`).
4. `run_gates.py aigateway --base e14-reproducible-submission-spec` is green.
5. No chart file is in the diff (`git diff e14-reproducible-submission-spec...HEAD --stat -- apps/aigateway/charts`
   prints nothing). WIRING (D6) owns the chart.
6. The ledger records: the RED run of each test, the NFR numbers, and the hand check of 0013 on SQLite.
7. Conventional commits (`feat(aigateway): …`, `test(aigateway): …`) on `unit/GW-capture`, no
   `Co-Authored-By`. No PR and no Linear issue for this unit (D1). The integrator merges the branch.

## 9. Open decisions

None is open. The items below are closed:

- **OD-1 — decided (default).** `AIGW_CACHE_VERSIONS_ENABLED` is `False` in code. This unit does not
  change the chart. WIRING (D6) sets the chart value and turns the flag on in the local runtime
  `screamingface up`.
- **OD-2 — decided (default).** `CacheCaptureEntry.key_hash` is NULL for an unkeyable call (stream,
  provider with no projection, unknown parameter). `erd.md` §3.2 says NOT NULL, but CV-D8 needs a row
  for a streaming call and a stream has no key. The freeze counts such a row as missing.
- **OD-3 — decided (default).** TEXT (canonical/compact JSON string), not JSONB, for `request_json`,
  `response_json`, `metadata_json`. Reason: the live cache uses TEXT (`request_cache_entry.py:18,34`);
  JSONB rewrites number and key forms, which can break the reproducible `archive_sha256` (erd §3.5).
- **OD-4 — decided (default).** `cache_capture_entry.ordinal` is a DB-generated BIGINT PK (no UUID `id`).
  Reason: exact arrival order across gateway replicas without a clock or a lock.
- **OD-5 — decided (default).** `race_lost` maps to `unstored` with the caller's own body inline
  (after a lost race the live row holds a different answer).
- **OD-6 — Decided: D7 (X-15).** The `CaptureStats` counters stay in process. No exporter.
- **OD-7 — decided (default).** `version_hit` is in `INLINE_OUTCOMES`: a version-hit row keeps the
  served body inline. GW-replay asserts it (step 5 above excludes it from CV-5).
- **Identity — Decided: D5.** Production uses `cloudflare_headers` (§7.1). `disabled` is a dev/local
  fallback only.
