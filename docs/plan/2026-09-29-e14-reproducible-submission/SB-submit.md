# SB-submit — Plan: submit with a receipt, name the system, cluster the result

- **Epic:** OME-1307 (E14).
- **Spec (the rubric):** `docs/spec/2026-09-29-e14-reproducible-submission/prd/submit-and-cluster.md`, `erd.md` §2.1, §2.2, §2.4, §2.6, `contracts.md` C3, C4, C10, C11.
- **Plan:** this file, `docs/plan/2026-09-29-e14-reproducible-submission/SB-submit.md`. **Ledger:** `docs/work/2026-09-29-e14-sb-submit.md`. Start it before the first RED.
- **Delivery (D1):** build this unit in its own temporary worktree on the branch `unit/SB-submit`, made from the HEAD of `e14-reproducible-submission-spec` (`git checkout -B unit/SB-submit e14-reproducible-submission-spec`). Do not open a PR. Do not file a Linear issue. After wave 3, the integrator merges `unit/SB-submit` into `e14-reproducible-submission-spec` and runs the gates.
- **Component:** `apps/scoreboard` only. Wave 3 (D2).
- **Implementer:** Sonnet, with the `sdlc-python` loop (ledger → RED → GREEN → gates → commit).

## Global constraints (read before you write code)

- Stack `scoreboard`, root `apps/scoreboard`. Run the commands from that directory unless the step says "repo root".
- Gates: from the repo root, `uv run .claude/scripts/run_gates.py scoreboard --base "$(git merge-base HEAD e14-reproducible-submission-spec)"`. WHY the merge base: the append-only check compares with the point where `unit/SB-submit` left the e14 branch, which can move during the wave (D1). The gate list is in `.claude/sdlc.local.md` (stack `scoreboard`): ruff check, ruff format --check, pyright, `pytest --cov=scoreboard --cov-fail-under=80`, and the named portal `node --test` files.
- ruff limits are strict (`apps/scoreboard/pyproject.toml` `[tool.ruff.lint]`): `max-complexity = 8`, `max-statements = 26`, `max-branches = 7`, **`max-returns = 3`**. Write many small functions. Do not add `# noqa`.
- pytest `asyncio_mode = "strict"`. Each async test needs `pytest.mark.asyncio` (use `pytestmark = pytest.mark.asyncio` per module, as `tests/unit/test_scores_routes.py:20` does).
- **Tests are append-only.** Do not change or delete an existing Python test. Put all new tests in NEW files. The append-only check cannot approve a Python test change (`.claude/scripts/approved_test_changes.py:48-52`).
- Keep each new file at 450 lines or less.
- Comment anchors: `WHY:`, `INVARIANT:`, `AIDEV-NOTE:`, `FEATURE:` only. No comment that repeats the code.
- Conventional commits on `unit/SB-submit`. No `Refs:` line. **No `Co-Authored-By` trailer.**
- **Identity (D5).** Production runs `SCOREBOARD_AUTH_MODE=cloudflare_headers` (`apps/scoreboard/src/scoreboard/core/auth/cloudflare_identity.py`; the peer check against `SCOREBOARD_ALLOWED_NETWORKS` comes before the `X-User-Email` read). In that mode `_resolve_submitter` (`routes/scores.py:87-118`) gives the verified email, and the route puts it into `submission.submitted_by` (`routes/scores.py:197-198`). The system owner, the reporter, the receipt `sub` check and the replay owner check all use that value. The `disabled` mode is a dev/local fallback only: keep today's behavior there (content-hash clustering, no registry call, no receipt `sub` check). Do not design around `disabled`. The main-path tests run in `cloudflare_headers` mode; each flow (submit, results list) has exactly one test for the `disabled` fallback (SC-8a, SC-17b).
- Never import from another app. Never import `screamingface` (the SDK) in the scoreboard (C11). The scoreboard may import `url4` (SB-registry adds that dependency).

## 1. Scope

**Owned test ids (from `prd/submit-and-cluster.md` §7):** SC-1, SC-2, SC-3, SC-4, SC-5, SC-6, SC-7, SC-8, SC-9, SC-10, SC-11, SC-12, SC-13, SC-14, SC-15, SC-16, SC-17, SC-22.

Supporting tests (not PRD rows, but you need them to prove the GREEN of an owned row) have the suffix `a`, `b` (for example SC-4a). They are listed in §6. SC-8a and SC-17b are the `disabled`-fallback tests (D5).

**Out of scope (do not build):**
- SC-18, SC-19, SC-20 (SDK, unit SDK-submit), SC-21 (engine, unit ENG-freeze), SC-23 (E2E).
- The registry rules themselves (SR-*, unit SB-registry). This unit only calls the registry.
- `PATCH /v1/scores/{id}` and `paper_url` validation (MD-*, unit SB-meta). This unit only copies `paper_url` onto a new head.
- `POST /v1/replay-grants` (unit SB-grants). This unit adds only the pure access rule that SB-grants reuses (§4.6).
- Publish, withdraw, the worker, GitHub, the bucket (unit SB-publish). This unit only inserts the `CacheVersionPublication` row in state `private` (SC-16).
- A `/metrics` HTTP route (Decided: D7 X-15). This unit adds counters on a per-app registry only; they stay in process.
- Chart values, Secrets, the receipt public keys in the chart, and the local runtime flags (`screamingface up`). Unit WIRING (wave 5, D6) owns them. This unit adds only the settings in `config.py`.
- Any change to the legacy `ScoreStore.submit` behavior.

## 2. Depends on

- **Merged first:** SB-registry (and so SB-schema and URL4-fp) and SB-meta. Both are in wave 2 (D2), so both are merged into the e14 branch before this wave starts. This unit uses SB-meta's `ScoreSubmission.paper_url` (SB-meta plan §4.2, stored by `_submission_to_kwargs`) and its `ScoreSchema.paper_url` / `metadata_revision`. If SB-meta is not merged when you start, STOP and ask.
- **Contracts implemented:** C3 (the receipt verifier, scoreboard side), C4 (submit), C10 (the `GET /v1/scores/{score_id}/results` part only).
- **Contracts consumed:** C3 claims as the gateway signs them (unit GW-freeze). C4 request fields as the SDK sends them (unit SDK-submit). The `RegistryService` of SB-registry (`resolve_for_submit` and `identify`; the `SystemRegistry` protocol has no `identify`, SB-registry §4.6-§4.7).
- **Consumed from SB-schema (erd §2.1, §2.2, §2.6, §6):** models `ReportedResult`, `System`, `SystemRevision`, `CacheVersionPublication`; the new `Score` columns `paper_url`, `system_revision_id`, `metadata_revision`, `metadata_updated_at`; the partial unique index I-S1 on `scores (benchmark_id, benchmark_revision, system_revision_id) WHERE system_revision_id IS NOT NULL`; unique `reported_result.run_id`; unique `reported_result.cache_version_id`; partial unique `reported_result (head_id) WHERE is_original`.

**Names from the SB-schema plan** (`SB-schema.md` §4.5-§4.8): the `ReportedResult` FK to the head is the field `head` (attribute and column `head_id`); the replay FKs are `replayed_from_result` and `pinned_baseline_result` (attributes and columns `replayed_from_result_id`, `pinned_baseline_result_id`; D8: every FK column has the native Tortoise name, no `source_field`); `CacheVersionPublication` has the one-to-one PK `result` (column `result_id`). The partial unique indexes are plain SQL in `scores/models/partial_indexes.py`; a test that builds its schema with `generate_schemas` (the `tortoise_db` fixture) must call `create_partial_unique_indexes(connection)` to get I-S1. SB-schema adds the fixture `partial_unique_indexes` to `tests/conftest.py` (`SB-schema.md` §4.10). Request that fixture in every `tests/unit/submissions/` app fixture.

**Before RED, do this check (10 minutes):** open the merged SB-schema models and migration `0018` and the merged SB-registry module. Write down in the ledger the real import paths and names. This plan uses the names below. If a merged name differs, use the merged name and change nothing else.

| This plan says | Expected source |
|---|---|
| `from scoreboard.scores.models import ReportedResult, System, SystemRevision, CacheVersionPublication` | SB-schema §4.4-§4.7 |
| `ReportedResult` FK attributes `head_id`, `replayed_from_result_id`, `pinned_baseline_result_id` (each is also the column name, D8); filter and create with these names (for example `ReportedResult.filter(head_id=...)`, `ReportedResult.create(head_id=..., replayed_from_result_id=...)`). Never pass `score_id=` to the ORM: `reported_result` has no `score_id` column. | SB-schema §4.5 |
| `from scoreboard.core.registry import Resolution, RevisionRef, SystemRef, SystemAlreadyNamed` and the errors `InvalidSystemName` (`.rule`, `.message`), `SystemNameTaken` (`.suggestion`), `NotSystemOwner`, `SystemNotFound`, `InvalidUrl4`, `Url4TooLarge`, `RegistryConflict` | SB-registry §4.2-§4.3 |
| `app.state.system_registry` is a `RegistryService` (SB-registry wires it in `main.py`) | SB-registry §3 |
| `await registry.resolve_for_submit(linked_url4, requested_name, revision_of, submitter, board_visibility, *, connection=conn)` (positional in the PRD §3.1 order, keyword-only `connection: object | None`) returns `Resolution(outcome, identity, system, revision, notice)`; `resolution.system.name` (equal to `revision.system.name`), `revision.id`; `notice` is `SystemAlreadyNamed(name, owner)` or None | SB-registry §4.2, §4.7 |
| `registry.identify(linked_url4) -> SystemIdentity` (`.fingerprint`, `.candidate_url4`; raises `InvalidUrl4`, `Url4TooLarge`) | SB-registry §4.7 |

### Integration notes (D2)

No other scoreboard unit is in wave 3. GW-replay, ENG-replay and SDK-submit change other components, so this unit shares no file with them. `apps/scoreboard/src/scoreboard/adapters/__init__.py` already exists (SB-registry, wave 2): do not create it again. Wave 4 builds on these files of this unit, so keep their names stable: `scoreboard/metrics.py` (`Metrics`, `build_metrics`), `scoreboard/routes/errors.py` (`coded_error`), `scoreboard/core/replay_access.py`, `ClusterStore.load_replay_target`, and `tests/unit/submissions/_receipts.py` (SB-grants and SB-publish import it).

Transaction rule (SB-registry §4.6): the registry methods take a keyword-only `connection` (default None) and pass it to every repository read (`.using_db(connection)`); writes open a nested `in_transaction()` SAVEPOINT. Call `resolve_for_submit` INSIDE the `async with in_transaction() as conn:` block of §4.5 step 5. Tortoise binds that transaction to the task context (`tortoise/backends/base/client.py:322-362` `TransactionContextPooled` and `tortoise/backends/sqlite/client.py:172-210` `SqliteTransactionContext` both set the context connection on enter and reset it on exit), so pass `connection=conn` and the registry adapter's queries join the submit transaction, and its own nested `in_transaction()` is a SAVEPOINT. Use `conn` (`.using_db(conn)`) for this unit's own queries in the block, as `store.py:1319-1333` does.

## 3. Files

Create (C) or modify (M). Paths are from the repo root.

| C/M | Path | What | Exemplar to imitate |
|---|---|---|---|
| M | `apps/scoreboard/pyproject.toml` | Add `"pyjwt[crypto]==2.15.0"` and `"prometheus-client>=0.26.0"` to `dependencies`. Then run `uv lock` in `apps/scoreboard` and commit `uv.lock` (the Dockerfile runs `uv sync --frozen`, `apps/scoreboard/Dockerfile:18-25`). | the pins in `packages/screamingface/pyproject.toml:71-73` |
| M | `apps/scoreboard/src/scoreboard/config.py` | New settings (§4.1). | `admin_emails`-style parsing in `apps/aigateway/src/aigateway/config.py:71-73,275-290`; `allowed_networks` here, `config.py:63-87` |
| C | `apps/scoreboard/src/scoreboard/core/submissions/__init__.py` | Empty package marker. | — |
| C | `apps/scoreboard/src/scoreboard/core/submissions/receipts.py` | Port `ReceiptVerifier`, `ReceiptClaims`, `ReceiptRejected`, `check_receipt_binding`, `receipt_columns`. Pure. No FastAPI, no Tortoise. | the pure-port style of `apps/scoreboard/src/scoreboard/core/auth/cloudflare_identity.py:1-70` |
| C | `apps/scoreboard/src/scoreboard/core/submissions/clustering.py` | Pure rules on primitive values only: `result_labels`, `publication_needed`. Stdlib only (§4.4). | same |
| C | `apps/scoreboard/src/scoreboard/scores/cluster_rules.py` | Adapter-side rules that read the pydantic `ScoreSubmission` / `ReplayClaim`: `cluster_revision`, `ResultFields`, `result_fields`, `replay_columns`, `clustered_notice`, `named_notice`. WHY not in `core/`: importing `scoreboard.scores.schemas` runs `scoreboard/scores/__init__.py`, which imports `store.py` and so Tortoise (`scores/__init__.py:3-4`). | `scores/store.py:139-153` (`_resolve_benchmark_revision`, a pure helper that lives next to its store) |
| C | `apps/scoreboard/src/scoreboard/core/replay_access.py` | Pure `replay_access(...)` (§4.6). SB-grants reuses it. | same |
| C | `apps/scoreboard/src/scoreboard/core/paging.py` | Opaque cursor encode/decode (§4.8). Create it: SB-meta's history cursor is a plain revision number (SB-meta plan §4.6) and does not fit a `(submitted_at, id)` key. | — |
| — | `apps/scoreboard/src/scoreboard/adapters/__init__.py` | Already made by SB-registry (wave 2). Do not create it. | — |
| C | `apps/scoreboard/src/scoreboard/adapters/jws_receipt_verifier.py` | `Ed25519ReceiptVerifier` (PyJWT, EdDSA). Implements `ReceiptVerifier`. | `apps/screamingface-engine/src/screamingface_engine/auth/jwt.py:25-85` (codec shape, error mapping, "never log key material") |
| C | `apps/scoreboard/src/scoreboard/scores/cluster_store.py` | `ClusterStore`: the Tortoise adapter and the transaction owner for the clustered submit (§4.4, §4.5). | `apps/scoreboard/src/scoreboard/scores/store.py:1253-1370` (`submit`: one read of visibility, lock, IntegrityError retry) |
| C2 | `apps/scoreboard/src/scoreboard/scores/cluster_types.py` | Value types, errors and two row helpers split out of `cluster_store.py` (review fix round 1, 450-line limit); `cluster_store` re-exports the public names. | `apps/scoreboard/src/scoreboard/scores/cluster_rules.py` |
| C | `apps/scoreboard/src/scoreboard/metrics.py` | `build_metrics()` with a per-app `CollectorRegistry` and the counters (§4.9). | `apps/screamingface-engine/src/screamingface_engine/metrics.py:9-40` |
| M | `apps/scoreboard/src/scoreboard/scores/store.py` | Add three public methods: `lock_visibility(benchmark_id, per_submitter, *, connection)` (calls `_revalidate_visibility(..., connection=connection, lock=True)`, `store.py:1202-1216`), `readable_by(score, *, submitted_by, identity_verified)` (returns `await self._readable_by(...)`, `store.py:906-922`) and `results_counts(score_ids, *, connection)` (§4.10). Change nothing else. | `models_for_score_ids`, `store.py:1556-1576` |
| M | `apps/scoreboard/src/scoreboard/scores/schemas.py` | New request fields and new DTOs (§4.2, §4.3). Put the new classes ABOVE `ScoreSchema` (`schemas.py:674`) so that `ScoreSchema` can refer to them. | `exclude_if` pattern at `schemas.py:702,734,752,759` |
| M | `apps/scoreboard/src/scoreboard/routes/scores.py` | Branch `submit_score` on `settings.clustering_enabled`; map the new errors (§4.7). | `routes/scores.py:177-285` |
| C | `apps/scoreboard/src/scoreboard/routes/results.py` | `GET /v1/scores/{score_id}/results` (§4.8). | `get_score` privacy pattern `routes/scores.py:287-353` |
| M | `apps/scoreboard/src/scoreboard/routes/leaderboard.py` | Fill `score_id` and `reported_results_count` for public rows (§4.10). Add the two fields to `RankedLeaderboardEntry` ONLY (`leaderboard.py:54-92`) and two keyword arguments to `_ranked_entry` (`leaderboard.py:167-172`). | `leaderboard.py:256-363` |
| C | `apps/scoreboard/src/scoreboard/routes/errors.py` | `coded_error(...)` (§4.7). Then replace the body of SB-meta's module-private `_coded` helper (SB-meta plan §4.6) with a call to `coded_error`, so one helper exists (DRY). Do not change SB-meta's error codes or tests. | SB-meta plan §4.6 `_coded` |
| M | `apps/scoreboard/src/scoreboard/main.py` | Wire `app.state.metrics`, `app.state.receipt_verifier`, `app.state.cluster_store = ClusterStore(app.state.score_store, app.state.system_registry)` (SB-registry wires `system_registry`), and `app.include_router(results.router)` BEFORE `register_portal(app, settings)` (the portal mounts `/` last, `main.py:192-194`). Build the verifier at `create_app`, so a bad key fails at startup. | `main.py:178-196` |
| C | `apps/scoreboard/portal/reported-results.js` | Pure UMD helper `reportedResultsLink(entry)` (§4.10). | `apps/scoreboard/portal/leaderboard-logic.js:1-22` |
| M | `apps/scoreboard/portal/benchmark.js` | In `renderBody` (`benchmark.js:162-209`), after the spec link, append the link from `window.SFReportedResults.reportedResultsLink(entry)` when it is not null. Use `P.link(...)` (text only, never `innerHTML`). | `benchmark.js:176` |
| M | `apps/scoreboard/portal/benchmark.html` | Add `<script src="reported-results.js" defer></script>` before `benchmark.js` (`benchmark.html:129-135`). | — |
| M | `.claude/sdlc.local.md` (Decided: D7 X-19, the edit is allowed) and `.github/workflows/scoreboard-tests.yml` | Add `tests/portal/reported-results.test.js` BY NAME to the `node --test` line in both files (`scoreboard-tests.yml:92-93`, OME-798 rule). Add `tests/unit/scores/test_cluster_race_postgres.py` BY NAME to the PostgreSQL job (`scoreboard-tests.yml:165-174`). The guard `tests/unit/guards/test_postgres_regressions_run_in_ci.py` fails if you forget it. | — |
| M | `apps/scoreboard/DEPLOYMENT.md` | Document the two environment variables (`SCOREBOARD_CLUSTERING_ENABLED`, `SCOREBOARD_RECEIPT_PUBLIC_KEYS`) and the key format (JSON `{kid: base64 of the raw 32-byte public key}`, D7 X-4). Say that the chart keys come from unit WIRING (D6). Do not edit the chart. | — |
| — | (no file) `apps/scoreboard/src/scoreboard/scores/migrations/0020_reported_result_replay_collapses.py` | Do NOT create. Cross-plan fix: SB-schema now adds `replay_repeated_key_collapses = fields.IntField(null=True)` to `BaseReportedResult`, so the column is in 0018 (`SB-schema.md` §4.5). Check the merged 0018 before RED. If the column is NOT there, STOP and ask. | — |
| C | tests (see §6) | — | — |

## 4. Signatures and data shapes

### 4.1 Settings (`config.py`, class `Settings`)

```python
clustering_enabled: bool = False
"""FEATURE: E14 — POST /v1/scores clusters by system (prd/submit-and-cluster.md).

WHY the code default is False: the legacy route tests are append-only and pin one row per
content hash (tests/unit/test_scores_routes.py:169-191). False keeps them meaningful. Unit
WIRING (D6) turns it on in the chart and in the local runtime (`screamingface up`).
"""

receipt_public_keys: dict[str, str] = Field(default_factory=dict)
"""C3 verifier keys: kid -> standard base64 of the RAW 32-byte Ed25519 public key (current
plus previous). Env SCOREBOARD_RECEIPT_PUBLIC_KEYS, a JSON object. Public keys, not a secret.
INVARIANT: the same encoding and the same kid values that the gateway publishes
(GW-freeze.md OD-F2: kid = sha256(raw public key).hexdigest()[:16]) and that the local
runtime writes (SDK-replay.md §4.12). The scoreboard does not derive the kid; it uses the
map keys as given."""
```

- `create_app` builds `Ed25519ReceiptVerifier.from_config(settings.receipt_public_keys)`. For each value: `raw = base64.b64decode(value, validate=True)`; `len(raw) != 32` or a decode error → `ValueError(f"SCOREBOARD_RECEIPT_PUBLIC_KEYS[{kid!r}] is not base64 of a 32-byte Ed25519 public key")`; else `Ed25519PublicKey.from_public_bytes(raw)` (`cryptography.hazmat.primitives.asymmetric.ed25519`). Never put the key text in the message.
- An empty map is valid. Then each receipt fails with `unknown_kid` (422).

### 4.2 Request (`ScoreSubmission`, `schemas.py:366`)

Add these optional fields (C4). Keep `extra="forbid"`.

```python
trace_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")] | None = None
revision_of: Annotated[str, Field(min_length=1, max_length=64)] | None = None
cache_version_receipt: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
replay: ReplayClaim | None = None
# paper_url: already added by SB-meta (PaperUrl | None). Do not add it again.

class ReplayClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: UUID
    cache_version_id: UUID
    hits: Annotated[int, Field(ge=0)]
    misses: Annotated[int, Field(ge=0)]
    repeated_key_collapses: Annotated[int, Field(ge=0)] = 0
    pinned_baseline_result_id: UUID | None = None
```

`trace_id` is not in the C4 field list, but C3 needs it (`tid` must equal the report `trace_id`). See spec gap G1. Do not read it from `metadata`.

### 4.3 Response DTOs (`schemas.py`, above `ScoreSchema`)

```python
CoverageStatus = Literal["complete", "partial"]
PublicationState = Literal["private", "requested", "published", "failed", "withdrawn"]

class CacheVersionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    sha256: str
    entry_count: int
    call_count: int
    coverage_status: CoverageStatus

class ReplayProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    replayed_from_result_id: UUID
    hits: int
    misses: int
    pinned_baseline_result_id: UUID | None
    reported_by: Literal["client"] = "client"   # C4 trust rule: "labelled reported by client"

class ReportedResultSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    score_id: UUID
    is_original: bool
    reporter: SubmittedBy                      # the published local-part form, schemas.py:178-243
    submitted_at: datetime
    score: float
    total_questions: int
    correct_questions: int | None
    models: list[str] | None = Field(default=None, exclude_if=lambda v: v is None)
    run_cost_usd: RunCostUsd
    run_cost_status: RunCostStatus | None = Field(default=None, exclude_if=lambda v: v is None)
    cache_saved_cost_usd: RunCostUsd = Field(default=None, exclude_if=lambda v: v is None)
    cache_version: CacheVersionSummary | None
    publication_state: PublicationState | None
    replay: ReplayProvenance | None = Field(default=None, exclude_if=lambda v: v is None)
    labels: list[str] = Field(default_factory=list)

class SubmitNotice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: Literal["system_already_named", "clustered_under"]
    name: str | None = Field(default=None, exclude_if=lambda v: v is None)
    owner: SubmittedBy = Field(default=None, exclude_if=lambda v: v is None)
    score_id: UUID | None = Field(default=None, exclude_if=lambda v: v is None)

class ReportedResultsPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[ReportedResultSchema]
    next_cursor: str | None
```

Build a `ReportedResultSchema` in ONE place, `scores/cluster_rules.py::result_schema(rr: ReportedResult, publication_state: str | None) -> ReportedResultSchema` (the submit response and the results list both call it): `score_id=rr.head_id`; `cache_version=CacheVersionSummary(id=rr.cache_version_id, sha256=rr.cache_version_sha256, entry_count=rr.cache_entry_count, call_count=rr.cache_call_count, coverage_status=rr.cache_coverage_status)` when `rr.cache_version_id is not None`, else `None`; `replay=ReplayProvenance(replayed_from_result_id=rr.replayed_from_result_id, hits=rr.replay_hits, misses=rr.replay_misses, pinned_baseline_result_id=rr.pinned_baseline_result_id)` when `rr.replayed_from_result_id is not None`, else `None`; `labels=result_labels(...)` from the same columns.

Add to `ScoreSchema` (all `default=None`, all `exclude_if=lambda v: v is None`, so `GET /v1/scores/{id}` and the private JSONL export stay byte-identical — the `OME-1181` Q2 trap, `schemas.py:686-702`):

```python
reported_result: ReportedResultSchema | None
reported_results_count: int | None
notices: list[SubmitNotice] | None
```

`paper_url` and `metadata_revision` on `ScoreSchema` belong to SB-meta. Do not add them here.

`labels` rules (pure function in `core/submissions/clustering.py`), in this order:

```python
def result_labels(*, coverage_status: str | None, entry_count: int | None,
                  call_count: int | None, replayed_from_result_id: UUID | None,
                  replay_hits: int | None, replay_misses: int | None) -> list[str]: ...
```

1. `coverage_status == "partial"` → `f"partial cache ({entry_count} of {call_count} calls)"`. The receipt has `n` (entries) and `c` (calls), not a missing count, so N = `cache_entry_count` and M = `cache_call_count`. See spec gap G6.
2. `replayed_from_result_id is not None` → `f"replay of {replayed_from_result_id} ({replay_hits}/{replay_hits + replay_misses})"`.
3. Else no label. The route builds each `ReportedResultSchema.labels` from the row columns.

### 4.4 Ports and core (pure)

`core/submissions/receipts.py`:

```python
RejectReason = Literal["malformed", "bad_alg", "unknown_kid", "bad_signature",
                       "bad_audience", "bad_issuer"]

@dataclass(frozen=True, slots=True)
class ReceiptClaims:
    sub: str
    vid: UUID
    tid: str        # 32 lowercase hex
    sha: str        # 64 lowercase hex
    n: int
    c: int
    cov: Literal["complete", "partial"]
    iat: int

class ReceiptRejected(Exception):
    def __init__(self, reason: RejectReason) -> None: ...
    reason: RejectReason

class ReceiptNotYours(Exception): ...        # -> 403 cache_version_not_yours

class ReceiptVerifier(Protocol):
    def verify(self, token: str) -> ReceiptClaims: ...   # raises ReceiptRejected

def check_receipt_binding(claims: ReceiptClaims, *, submitter: str | None,
                          trace_id: str | None, check_subject: bool) -> None:
    """Raise ReceiptNotYours when tid != trace_id, or (check_subject and sub != submitter).
    Compare sub with casefold() on both sides after strip(): the gateway lowercases
    usernames (apps/aigateway/src/aigateway/config.py:275-290)."""

def receipt_columns(claims: ReceiptClaims | None) -> dict[str, object]:
    """The five I-R1 columns: all set from the claims, or all None."""
    # cache_version_id=claims.vid, cache_version_sha256=claims.sha, cache_entry_count=claims.n,
    # cache_call_count=claims.c, cache_coverage_status=claims.cov
```

`check_subject` is `identity_is_verified(settings.auth_mode)` (`routes/scores.py:76-84`; True only for `cloudflare_headers`, the production mode, D5). C3: "in disabled mode, skip this". WHY the helper and not `!= "disabled"`: a new mode must turn verification on by name, not by default (`routes/scores.py:76-84` docstring).

`adapters/jws_receipt_verifier.py` — `Ed25519ReceiptVerifier(public_keys: Mapping[str, Ed25519PublicKey])`, with `from_config(raw: Mapping[str, str]) -> Ed25519ReceiptVerifier` (§4.1). `verify(token)` does these steps, in this order, and maps each failure to ONE reason:

1. `header = jwt.get_unverified_header(token)`; `jwt.DecodeError` (or any `jwt.InvalidTokenError`) → `malformed`.
2. `header.get("alg") != "EdDSA"` → `bad_alg`.
3. `kid = header.get("kid")`; not a `str`, or not in the map → `unknown_kid`.
4. `claims = jwt.decode(token, key, algorithms=["EdDSA"], audience="scoreboard", issuer="aigateway", leeway=60, options={"require": ["iss", "aud", "sub", "vid", "tid", "sha", "n", "c", "cov", "iat"]})`. Map: `jwt.InvalidSignatureError` → `bad_signature`; `jwt.InvalidAudienceError` → `bad_audience`; `jwt.InvalidIssuerError` → `bad_issuer`; every other `jwt.InvalidTokenError` (missing claim, immature `iat`, decode error) → `malformed`. WHY `leeway=60`: the same skew allowance as C6; the gateway clock can be ahead. The receipt has no `exp` (C3), so do not require it.
5. Shape check → `malformed` on any failure: `vid` parses as `UUID`; `tid` matches `^[0-9a-f]{32}$`; `sha` matches `^[0-9a-f]{64}$`; `n` and `c` are `int` (not `bool`) and `>= 0`; `cov in ("complete", "partial")`; `sub` is a non-empty `str`; `iat` is an `int`.
6. Return `ReceiptClaims(...)`.

INVARIANT: the reason is the only detail that leaves the adapter. Never put the token, a claim value or key material into an exception message or a log line.

`core/submissions/clustering.py` (stdlib only; no import of `scoreboard.scores`, `pydantic`, `tortoise`, `fastapi`, `jwt`):

```python
def result_labels(...) -> list[str]: ...          # §4.3
def publication_needed(receipt: Mapping[str, object]) -> bool:
    """SC-D8: True iff receipt["cache_version_id"] is not None."""
```

`scores/cluster_rules.py` (adapter side; may import `scoreboard.scores.schemas` and `scoreboard.scores.store`):

```python
def cluster_revision(submission: ScoreSubmission) -> str | None:
    """INVARIANT (SC-D4): the RESOLVED revision (store._resolve_benchmark_revision), never the
    raw metadata value when a typed value exists."""

@dataclass(frozen=True, slots=True)
class ResultFields:        # every ReportedResult column except id, head_id, is_original
    reporter: str | None
    run_id: str | None
    trace_id: str | None
    score: float
    total_questions: int
    correct_questions: int | None
    run_cost_usd: Decimal | None
    run_cost_status: str | None
    cache_saved_cost_usd: Decimal | None
    models: list[str] | None
    ran_with_providers: list[str]
    answer_seed: int | None                 # always None in this unit, see spec gap G5
    client_name: str | None
    client_version: str | None
    client_platform: str | None
    receipt: dict[str, object]              # from receipt_columns()
    replay: dict[str, object]               # from replay_columns()

def replay_columns(replay: ReplayClaim | None) -> dict[str, object]:
    """I-R2: replayed_from_result_id, replay_hits, replay_misses, pinned_baseline_result_id,
    replay_repeated_key_collapses — all set, or all None."""

def result_fields(submission: ScoreSubmission, *, run_id: str | None,
                  claims: ReceiptClaims | None) -> ResultFields: ...

def clustered_notice(score_id: UUID) -> SubmitNotice
def named_notice(notice: SystemAlreadyNamed) -> SubmitNotice   # name=notice.name, owner=notice.owner
```

`cluster_revision` returns `_resolve_benchmark_revision(submission)` (`store.py:139-153`). Import it; do not copy it.

`replay_columns` returns Tortoise keyword names (with D8 they equal the erd column names): `replayed_from_result_id`, `replay_hits`, `replay_misses`, `pinned_baseline_result_id`, `replay_repeated_key_collapses` (all set from the claim, or all `None`).

`core/replay_access.py` (§4.6).

### 4.5 `ClusterStore` (adapter, `scores/cluster_store.py`)

It owns the transaction. It depends on `ScoreStore` (for `lock_visibility`), on `RegistryService` (SB-registry; typed by the class because this unit needs `identify`, which the `SystemRegistry` protocol does not have), and on the Tortoise models.

```python
@dataclass(frozen=True, slots=True)
class ClusterOutcome:
    head: Score
    result: ReportedResult | None   # None only for a legacy-key replay of a head with no original row
    publication_state: str | None
    results_count: int
    notices: list[SubmitNotice]
    kind: Literal["new_head", "reported_result", "replay_idempotent"]

class CacheVersionAlreadyBound(Exception): ...     # -> 409 cache_version_already_bound
class InvalidReplayClaim(Exception): ...           # -> 422 invalid_replay_claim

class ClusterStore:
    def __init__(self, score_store: ScoreStore, registry: RegistryService) -> None: ...

    async def submit(self, submission: ScoreSubmission, *, idempotency_key: str | None,
                     identity_verified: bool, claims: ReceiptClaims | None,
                     ) -> ClusterOutcome: ...
    async def results_page(self, score_id: UUID, *, after: Cursor | None, limit: int
                           ) -> list[ReportedResult]: ...
    async def publication_states(self, result_ids: Sequence[UUID]) -> dict[str, str]: ...
    async def load_replay_target(self, result_id: UUID) -> ReplayTarget | None: ...
```

Put the public head lookup in its own method `_find_public_head(self, *, benchmark_id, benchmark_revision, system_revision_id, connection) -> Score | None`. SC-10a patches it. Do not add any other test seam.

WHY the benchmark row lock matters for the race: `lock_visibility` takes `SELECT … FOR UPDATE` on the benchmark row (`store.py:1176-1200`), so on PostgreSQL two submits to ONE board run their write step one after the other, and the second one sees the first head. The `IntegrityError` retry still matters for the system rows, which are global across boards (SR-D2), and for SQLite, which takes no row lock.

**`submit` algorithm.** Split it into private helpers so each stays inside the ruff limits.

1. `benchmark = await Benchmark.get_or_none(id=submission.benchmark_id)`. `per_submitter = benchmark is not None and benchmark.visibility == "private"`. If `per_submitter and not identity_verified`: raise the existing `PrivateBoardRequiresIdentity` (`store.py:526`). This is the same rule and the same single read as `store.py:1269-1274`.
2. `stored_key = _scoped_idempotency_key(idempotency_key, submission.submitted_by, per_submitter=per_submitter)` (`store.py:484`). Import the existing function. INVARIANT: the run id stored in `ReportedResult.run_id` is the SCOPED key, so a second participant on a private board cannot reach the first participant's row by reusing a key (the OME-894 rule at `store.py:1276-1282`).
3. **Idempotent replay (SC-D1).** If `stored_key` is not None:
   - `rr = await ReportedResult.get_or_none(run_id=stored_key)`. If found and the head is readable by this caller (`await score_store.readable_by(head, submitted_by=..., identity_verified=...)`, a new public wrapper of `_readable_by`, `store.py:906-922`), return `kind="replay_idempotent"`.
   - Else, if a LIVE legacy `IdempotencyKey` row (`key=stored_key`, `expires_at > now`, and `_mapping_is_ours`, `store.py:538`) points to a head that is readable, return that head with its `is_original` result (or `result=None` when the head has no original row: a head that an old pod wrote after `0019` ran), `kind="replay_idempotent"`. WHY: rows made on the legacy path have no `run_id` on their result (SC-1 stays true after the flag flips).
   - If found but NOT readable: go on as a new submission, and store the new result with `run_id=None`. WHY: the key is already taken by a row this caller may not read; the unique `run_id` would reject the insert, and the retry branch must never hand that row back (OME-894). Record this edge in the ledger.
4. **Bindings (before any write).**
   - If `claims` and `await ReportedResult.exists(cache_version_id=claims.vid)`: raise `CacheVersionAlreadyBound` (SC-E4). The same-run case already returned in step 3.
   - If `submission.replay`: validate it (§4.6 rule R). Raise `InvalidReplayClaim` on failure.
5. **Write (one transaction).** `async with in_transaction() as conn:`
   1. `await score_store.lock_visibility(submission.benchmark_id, per_submitter, connection=conn)` (raises `BenchmarkVisibilityChanged`, as `store.py:1320-1322`).
   2. Locate the head. `rev = cluster_revision(submission)`. When `rev is None`, filter with `benchmark_revision__isnull=True` (never `benchmark_revision=None` by hand-built SQL). Three branches, one helper each:
      - **public, `identity_verified` is True** (`cloudflare_headers`, the production path, D5; `submission.submitted_by` is then the verified email): `resolution = await self._registry.resolve_for_submit(submission.url4_expression, submission.spec_id, submission.revision_of, submission.submitted_by, "public", connection=conn)`. `name = resolution.system.name`. Then `head = await self._find_public_head(benchmark_id=..., benchmark_revision=rev, system_revision_id=resolution.revision.id, connection=conn)`. If `head is None`: try the legacy link (SC-D3): `await Score.filter(content_hash=<new head hash>, benchmark_id=<id>, system_revision_id__isnull=True).using_db(conn).update(system_revision_id=resolution.revision.id)`; when it updated 1 row, re-read that row by `content_hash`. The new head hash is `_content_hash(submission.model_copy(update={"spec_id": name}), per_submitter=False)` (`store.py:335`).
      - **public, `identity_verified` is False** (the `disabled` dev/local fallback only, D5; `submission.submitted_by` is free text or None, and the SDK sends none, `packages/screamingface/src/screamingface/_scoreboard/leaderboards.py:448-481`): do NOT call the registry. `head = Score.filter(content_hash=_content_hash(submission, per_submitter=False), benchmark_id=...).using_db(conn).first()`. `revision_of` is ignored. `spec_id` stays as sent, `system_revision_id = None`. WHY: an unverified name must never own a system (`System.owner` is NOT NULL and names are global, SR-D2), and this keeps today's dedup key (the content hash) while it still records the cache version. Decided: D5.
      - **private**: `fp = self._registry.identify(submission.url4_expression).fingerprint`. Read `Score.filter(benchmark_id=..., benchmark_revision=rev (or __isnull), submitted_by=submission.submitted_by, system_revision_id__isnull=True).using_db(conn).order_by("submitted_at", "id")` and return the first row where `self._registry.identify(row.url4_expression).fingerprint == fp`; skip a row whose `identify` raises `InvalidUrl4` or `Url4TooLarge`. INVARIANT: recompute from `url4_expression`; never trust `metadata.system_fingerprint` (a client can send any metadata; SR-D1). Do not call `resolve_for_submit` on a private board (I-N4, SR-D8). `revision_of` is ignored.
   3. If there is no head: insert the head with `Score.create(using_db=conn, **_submission_to_kwargs(sub, content_hash))` (`store.py:296`), where `sub` is `submission.model_copy(update={"spec_id": name})` on the named public branch and `submission` otherwise, and `system_revision_id = resolution.revision.id` (named public) or `None`. `paper_url` is already in `_submission_to_kwargs` (SB-meta). `content_hash = _content_hash(sub, per_submitter=per_submitter)`. On private, set `metadata = {**(submission.metadata or {}), "system_fingerprint": fp}` (erd §2.4). The server value overwrites a client value. `is_original = True`, `kind = "new_head"`.
   4. Else `is_original = False`, `kind = "reported_result"`, and add `clustered_notice(head.id)`.
   5. `rr = await ReportedResult.create(using_db=conn, head_id=head.id, is_original=..., **fields)` (the `ResultFields` values, with `receipt` and `replay` dicts splatted). Never update the head row (I-S2, SC-9). A later reporter's `authors` and `paper_url` are ignored (they belong to the head, PRD edit-metadata §5).
   6. If `publication_needed(fields.receipt)`: `await CacheVersionPublication.create(using_db=conn, result_id=rr.id, state="private")` (SC-D8).
   7. `results_count = await ReportedResult.filter(head_id=head.id).using_db(conn).count()`.
   8. If `resolution.notice` is not None, add `named_notice(resolution.notice)` FIRST in `notices`.
6. **Race handling (SC-D2, SR-D2).** Catch `IntegrityError` around step 5 ONE time. Then run step 5 again in a NEW transaction (the second pass finds the winner's head, or the winner's system, and appends). On a second `IntegrityError`:
   - if `stored_key` now matches a `ReportedResult.run_id` AND its head is readable by this caller (`readable_by`): return it as `replay_idempotent` (a concurrent resend of the same run);
   - elif `claims` and the version is now bound: raise `CacheVersionAlreadyBound`;
   - else raise the existing `ConcurrentScoreUpdate` (`store.py:573`, the route maps it to 409).
   INVARIANT: `IntegrityError` subclasses `OperationalError`, which the route maps to 503 (`store.py:1344-1349`). Never let it leave `submit`.

Registry errors pass through `ClusterStore.submit` without a catch. The route maps them (§4.7). A registry error raised inside the transaction rolls it back, so nothing is written (SC-E5).

### 4.6 Replay access rule (`core/replay_access.py`) and rule R

```python
Access = Literal["allow", "not_found", "withdrawn"]

def is_owner(caller: str | None, reporter: str | None, *, identity_verified: bool) -> bool:
    """identity_verified and both set and caller.strip().casefold() == reporter.strip().casefold()."""

def replay_access(*, board_visibility: str | None, redistributable: bool, reporter: str | None,
                  publication_state: str | None, caller: str | None,
                  identity_verified: bool) -> Access:
    """RP-H4, RP-E2, RP-E3 (prd/replay-pinned-run.md). In this order:
    owner -> allow; private board or not redistributable -> not_found;
    publication_state == 'withdrawn' -> withdrawn; else allow.
    INVARIANT: not_found is checked before withdrawn, so a private or gated result never
    reveals that it exists (OME-894, routes/scores.py:54-56)."""
```

`ReplayTarget` (from `ClusterStore.load_replay_target`): `result: ReportedResult`, `head: Score`, `benchmark: Benchmark`, `publication_state: str | None`.

**Rule R (SC-14, C4 trust rule).** For `submission.replay`:
1. `target = await load_replay_target(replay.result_id)`; None → `InvalidReplayClaim`.
2. `target.result.cache_version_id != replay.cache_version_id` → `InvalidReplayClaim`.
2a. `target.benchmark.id != submission.benchmark_id` → `InvalidReplayClaim` (added in review fix round 1: a claim names a result of the board it is posted on; C6/RP-E4 refuses a grant across boards with `replay_benchmark_mismatch`, so no grant could produce such a claim). Test row: SC-14 invalid-claim table, `result-of-another-benchmark`.
3. `replay_access(board_visibility=target.benchmark.visibility, redistributable=target.benchmark.redistributable, reporter=target.result.reporter, publication_state=target.publication_state, caller=submission.submitted_by, identity_verified=identity_verified) != "allow"` → `InvalidReplayClaim`.
4. `replay.pinned_baseline_result_id` is set and no `ReportedResult` has that id → `InvalidReplayClaim`.
5. Store the counts as sent (C4: "stored as reported").

### 4.7 Route changes (`routes/scores.py`)

`submit_score` keeps its first lines (`_resolve_submitter`, `routes/scores.py:197-198`) and the `exists()` 404 seam (`:209-216`). Then:

- If `not settings.clustering_enabled`: run the current code path unchanged. The new request fields are ignored.
- Else:
  1. If `submission.cache_version_receipt`: `claims = verifier.verify(...)`; then `check_receipt_binding(claims, submitter=submitted_by, trace_id=submission.trace_id, check_subject=identity_is_verified(settings.auth_mode))`. This runs BEFORE any database read of scores (SC-E2 "nothing is written").
  2. `outcome = await cluster_store.submit(submission, idempotency_key=idempotency_key, identity_verified=identity_is_verified(settings.auth_mode), claims=claims)`. `submission.submitted_by` is already the value from `_resolve_submitter` (the verified email in `cloudflare_headers`, D5).
  3. Status: `200` when `outcome.kind == "replay_idempotent"`, else `201`.
  4. Body: `ScoreSchema` of the head (`_score_to_schema`, `store.py:96`) with `reported_result`, `reported_results_count`, `notices` set; then `_submission_response(...)` (`routes/scores.py:162-174`) for the revision notice, as today.
  5. Count metrics (§4.9).

Error map. Use a coded body: `HTTPException(status, detail={"code": <code>, "message": <text>, ...extra})`, built by `def coded_error(status: int, code: str, message: str, **extra: object) -> HTTPException` in `apps/scoreboard/src/scoreboard/routes/errors.py` (C). Add `class CodedErrorDetail(BaseModel)` (`code: str`, `message: str`, `model_config = ConfigDict(extra="allow")`) and `class CodedErrorResponse(BaseModel)` (`detail: CodedErrorDetail`) to `schemas.py`, and list them in the OpenAPI `responses` of the changed routes. See spec gap G2.

| Raised | Status | code | extra |
|---|---|---|---|
| `ReceiptRejected(reason)` | 422 | `invalid_cache_version_receipt` | `reason` |
| `ReceiptNotYours` | 403 | `cache_version_not_yours` | — |
| `CacheVersionAlreadyBound` | 409 | `cache_version_already_bound` | — |
| `InvalidReplayClaim` | 422 | `invalid_replay_claim` | — |
| `NotSystemOwner` | 403 | `not_system_owner` | — |
| `SystemNotFound` | 404 | `system_not_found` | — |
| `SystemNameTaken` | 409 | `system_name_taken` | `suggestion` |
| `InvalidSystemName` | 422 | `invalid_system_name` | `rule=exc.rule`; `message=exc.message` |
| `RegistryConflict` | 409 | `registry_conflict` | — |
| `InvalidUrl4` | 422 | `invalid_url4` | — |
| `Url4TooLarge` | 422 | `url4_too_large` | — (Decided: D7 X-22) |
| `PrivateBoardRequiresIdentity`, `BenchmarkVisibilityChanged`, `ConcurrentScoreUpdate` | as today | as today (`routes/scores.py:248-272`) | — |

Size cap (D7 X-22): the client-visible cap is the existing 32,000-char `url4_expression` limit of `ScoreSubmission` (`schemas.py:378`). A longer text gets the standard FastAPI 422 before the route body runs. `Url4TooLarge` from the registry also maps to 422 (not 413), so the client sees one status for "too large". Do not add a 256 KiB check or a 413.

All the new `except` clauses go INSIDE the outer `try … except OperationalError` and BEFORE it, as `routes/scores.py:256-264` explains.

### 4.8 Results list (`routes/results.py`, C10)

```
GET /v1/scores/{score_id}/results?cursor=<opaque>&limit=<1..200, default 50>
200 ReportedResultsPage
404 {"detail": "score not found"}   (SCORE_NOT_FOUND_DETAIL, byte-identical, routes/scores.py:56)
422 invalid limit (FastAPI Query(ge=1, le=200)) | {"detail": {"code": "invalid_cursor", ...}}
```

- Read identity with `ReadIdentity` (`routes/dependencies.py:40`).
- Privacy: copy the exact `get_score` rules (`routes/scores.py:295-351`): 404 for a missing head; on a private board, `PRIVATE_CACHE_HEADERS` and 404 unless `identity == head.submitted_by`; the `turned_private` re-check before a public answer (SC-D9).
- Order `(submitted_at DESC, id DESC)`. Cursor = urlsafe base64 (no padding) of `json.dumps({"t": <submitted_at isoformat>, "i": <id str>}, separators=(",", ":"))`. The page query is `head_id = X AND (submitted_at < t OR (submitted_at = t AND id < i))`, `LIMIT limit + 1`. `next_cursor` is set only when there are `limit + 1` rows.
- A cursor that does not decode, or has other keys → 422 `invalid_cursor`.
- `publication_state` comes from one `CacheVersionPublication.filter(result_id__in=...)` read per page.

### 4.9 Metrics (`metrics.py`)

```python
@dataclass(frozen=True)
class Metrics:
    registry: CollectorRegistry
    submits: Counter              # scoreboard_submits_total{kind}
    receipt_rejections: Counter   # scoreboard_receipt_rejections_total{reason}

def build_metrics() -> Metrics: ...
```

`kind ∈ {new_head, reported_result, replay_idempotent}`. `reason ∈ RejectReason ∪ {not_yours, already_bound}`. Use a per-app `CollectorRegistry` (engine `metrics.py:18-40` explains why). SB-grants and SB-publish add their counters to this dataclass. The counters stay in process: no exporter and no `/metrics` route (Decided: D7 X-15).

### 4.10 Leaderboard count and portal (SC-22)

- ONLY `RankedLeaderboardEntry` (`routes/leaderboard.py:54`) gets the two fields:
  `score_id: str | None = Field(default=None, exclude_if=lambda v: v is None)` and
  `reported_results_count: int | None = Field(default=None, exclude_if=lambda v: v is None)`.
  Do NOT add them to `LeaderboardEntry` (`schemas.py:763`). WHY: two append-only guards iterate `LeaderboardEntry.model_fields` and compare each one to a `Score` column (`tests/unit/scores/test_store.py:1939-1968`, `tests/unit/test_multiple_authors.py:225-250`). `Score` has no `score_id` column, so those tests would fail. `_ranked_entry` splats a `LeaderboardEntry` into `RankedLeaderboardEntry`; extra optional fields on the ranked class are safe.
- `_ranked_entry(rank, entry, *, on_pareto_frontier, score_id: str | None = None, reported_results_count: int | None = None)` passes the two new values to the constructor.
- In `get_leaderboard` (public path only, `leaderboard.py:256-363`), inside the same `async with store.read_snapshot() as snapshot:` block, call `counts = await store.results_counts([row.source_id for row in rows], connection=snapshot)`. For each row with a count of 2 or more, pass `score_id=row.source_id` and the count to `_ranked_entry`. A count of 0 or 1 passes `None` for both, so every legacy payload stays byte-identical. INVARIANT: `turned_private` stays the last await before the response (`leaderboard.py:286-289`).
- `ScoreStore.results_counts(score_ids, *, connection) -> dict[str, int]`: for each chunk of `_MODELS_READ_CHUNK` ids (`store.py:53`): `ReportedResult.filter(head_id__in=chunk).using_db(connection).annotate(n=Count("id")).group_by("head_id").values("head_id", "n")`. Key the result by `str(row["head_id"])`.
- `portal/reported-results.js` exports `reportedResultsLink(entry)`:
  - returns `null` if `entry.reported_results_count` is not an integer ≥ 2, or `entry.score_id` is not a string;
  - else `{ text: n + " reported results", href: "/v1/scores/" + encodeURIComponent(entry.score_id) + "/results" }`.
  - Browser global `window.SFReportedResults`; `module.exports` in Node (same UMD as `leaderboard-logic.js:17-22`).
- The link target is the JSON endpoint (OD-4, decided (default)). Follow the `screamingface-design` skill for the link class (use the existing `mono` link style).

## 5. Migrations

- Current highest on `main`: `0016_score_enriched_at.py`. SB-schema adds `0017`, `0018`, `0019` (erd §6).
- This unit adds NO migration. The column `reported_result.replay_repeated_key_collapses` is in SB-schema 0018 (cross-plan fix). If the merged 0018 does not have it, STOP and ask.
- Background: C4 sends `repeated_key_collapses` and RP-D5 needs it stored, but erd §2.2 has no column for it (spec gap G3). The cross-plan check moved the column into SB-schema, so only the schema-foundation unit adds migrations.
- The index for SC-17: SB-schema adds `reported_result (head_id, submitted_at)` (`SB-schema.md` §4.5). That is enough for the `(submitted_at DESC, id DESC)` page (the `id` tie-break is on few rows). Do not add another index.
- Expand-only: a nullable column. No data change. Apply it by hand on a fresh SQLite (`uv run python -m tortoise -c scoreboard.db.TORTOISE_CONFIG migrate`) and record the output in the ledger (CI runs migrations only in `test_migration_*` tests; see the OME-1325 plan, Step 3).

## 6. TDD order (RED first, risk order)

New test directory `apps/scoreboard/tests/unit/submissions/` with `__init__.py` and `conftest.py`.

`conftest.py` fixtures (imitate `tests/unit/test_scores_routes.py:22-121`):
- `receipt_key` → `(kid="gw-test-1", private_key: Ed25519PrivateKey, public_b64: str)`; generate with `Ed25519PrivateKey.generate()`; `public_b64 = base64.b64encode(private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()`.
- Put `receipt_key`'s helpers and `make_receipt` in a plain module `tests/unit/submissions/_receipts.py` (functions, not fixtures), and wrap them as fixtures in `conftest.py`. SB-grants and SB-publish import `tests.unit.submissions._receipts` (`tests/__init__.py` and `tests/unit/__init__.py` exist; the precedent is `from tests.unit.test_seed_engine_catalog import ...`, `tests/unit/test_seed_case_count.py:20`).
- url4 constants in `_receipts.py`: `URL4_A = "(https://model.test/cand-a)!'answer'"`, `URL4_B = "(https://model.test/cand-b)!'answer'"`. WHY: the route now runs the real `Url4Fingerprinter` (SB-registry), and a text such as `url4://bench/cand-a` does not parse (`render(build("url4://bench/cand-a"))` raises `url4.RenderError`, checked on `origin/main`). Record in the ledger that both constants give two different fingerprints with the merged `url4.fingerprint`.
- Identity constants in `_receipts.py` (D5): `ANA = "ana@x.org"`, `BRUNO = "bruno@y.org"`, `def as_user(email: str) -> dict[str, str]: return {"X-User-Email": email}`. SB-grants and SB-publish import them too.
- `make_receipt(**overrides) -> str`: signs the default claims `{"iss": "aigateway", "aud": "scoreboard", "sub": ANA, "vid": <uuid4>, "tid": "4bf92f3577b34da6a3ce929d0e0e4736", "sha": "a"*64, "n": 412, "c": 420, "cov": "complete", "iat": <now>}` with `jwt.encode(..., algorithm="EdDSA", headers={"kid": kid})`.
- `clustered_cf_app` / `clustered_cf_client` — **the main path (D5)**: `Settings.model_validate({"database_url": "sqlite://:memory:", "cors_origins": [], "auth_mode": "cloudflare_headers", "allowed_networks": "127.0.0.1/32", "clustering_enabled": True, "receipt_public_keys": {kid: public_b64}})` and `monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")`. Copy the existing `cloudflare_headers` fixtures `app_with_cloudflare_auth` and `cloudflare_score_client` (`tests/unit/test_scores_routes.py:65-107`) and their WHY comments (ASGITransport reports the peer `127.0.0.1`; `FORWARDED_ALLOW_IPS` must be disjoint from `allowed_networks`, or `create_app` refuses to start). Also copy `untrusted_peer_score_client` (`:110-120`) as `clustered_untrusted_client`. Every call sends `headers=as_user(...)`. It creates benchmarks `pub` (public, `redistributable=True`), `gated` (public, `redistributable=False`) and `priv` (private).
- `clustered_app` / `clustered_client` — **the `disabled` fallback only**: `Settings(database_url="sqlite://:memory:", cors_origins=[], clustering_enabled=True, receipt_public_keys={kid: public_b64})`, the same benchmarks. Only SC-1, SC-2 (CHAR rows of today's `disabled` behavior), SC-8a and SC-17b use it.
- Unless a row says otherwise, a route test uses `clustered_cf_client` and sends `as_user(ANA)`.
- `payload(**overrides)`: like `_valid_payload` (`test_scores_routes.py:23-40`, which sets `submitted_by="tester"`) with `benchmark_id="pub"`, `spec_id="kevins-best"`, `url4_expression=URL4_A`, `trace_id="4bf92f3577b34da6a3ce929d0e0e4736"`.

Before RED: create the empty modules, the stub route `GET /v1/scores/{score_id}/results` that returns 501, and the `clustering_enabled` setting with the branch that raises `NotImplementedError`. Then each RED fails on an assertion, not on an import.

| # | Test id | File | Test name | RED reason (what fails before GREEN) |
|---|---|---|---|---|
| 1 | SC-1 (CHAR) | `test_submit_char.py` | `test_same_run_id_returns_existing_row_200` — parametrize `clustering_enabled` over `[False, True]` | `False` passes at once (CHAR). `True`: the branch raises, so the status is 500, not 200. |
| 2 | SC-2 (CHAR) | `test_submit_char.py` | `test_private_board_refuses_unverified_write` — parametrize the flag | `False` passes (CHAR). `True`: 500 instead of 403 with the detail at `routes/scores.py:265-272`. |
| 3 | SC-3 | `test_submit_idempotency.py` | `test_retried_submit_same_run_id_one_reported_result` — two POSTs, same `Idempotency-Key`: 201 then 200; same `id` and same `reported_result.id`; `ReportedResult.filter(head_id=...).count() == 1` | no `reported_result` in the body. |
| 4 | SC-3a | `test_submit_idempotency.py` | `test_private_run_id_is_stored_scoped_not_raw` — on `priv` as `ANA`, `ReportedResult.run_id` starts with `sfp-` | run_id is raw or absent. |
| 5 | SC-4 | `test_receipts.py` | `test_receipt_bad_signature_422_nothing_written` — table: signed by another key; unknown kid; `alg=HS256`; not a JWS; `aud="x"`. Assert 422, `detail.code == "invalid_cache_version_receipt"`, the `reason`, and `Score`, `ReportedResult`, `System` counts are 0 | 201 today (the receipt is ignored). |
| 6 | SC-4a | `test_receipt_verifier.py` | `test_verifier_maps_each_pyjwt_error_to_a_reason` (unit on `Ed25519ReceiptVerifier`) and `test_verifier_rejects_claims_with_wrong_shapes` (tid not hex, cov="x", n="1") | module has no behavior yet. |
| 7 | SC-4b | `test_receipt_verifier.py` | `test_create_app_refuses_a_non_ed25519_receipt_key` (an RSA PEM → `ValueError`, the message has the kid and no PEM text) | no startup check. |
| 8 | SC-5 | `test_receipts.py` | `test_receipt_sub_or_tid_mismatch_403` — (a) `sub="other@x.org"` with `as_user(ANA)`; (b) `tid` ≠ payload `trace_id`; (c) `sub="ANA@X.org "` with `as_user(ANA)` is accepted (201, casefold and strip). Assert 403 `cache_version_not_yours` and nothing written for (a)(b). (The `disabled` case, where `sub` is not checked, is in SC-8a.) | 201 for (a)(b). |
| 9 | SC-6 | `test_receipts.py` | `test_receipt_vid_bound_to_other_run_409` — submit run A with receipt V; submit run B (other key, other score) with a receipt for V → 409 `cache_version_already_bound`; run A again → 200 | 201 for run B. |
| 10 | SC-7 | `test_clustering.py` | `test_first_submit_creates_head_and_original_result_with_version` — 201; `reported_result.is_original is True`; `cache_version` equals the claims; `publication_state == "private"`; `reported_results_count == 1`; `spec_id == "kevins-best"`; head `system_revision_id` set | no fields. |
| 11 | SC-8 | `test_clustering.py` | `test_same_system_second_reporter_appends_result_no_new_head` — `as_user(ANA)` then `as_user(BRUNO)` (each with a receipt whose `sub` is that caller), same url4, other score → second is 201, same `id`, `is_original is False`, `reported_result.reporter == "bruno"` (published form), notices has `{"code": "clustered_under", "score_id": <head>}`, `Score.all().count() == 1`, the `System.owner` is `ANA` | a second head. |
| 12 | SC-9 | `test_clustering.py` | `test_later_result_never_changes_head_ranked_columns` — after the SC-8 steps, assert the second response has `reported_result.score` = Bruno's score, and `GET /v1/scores/{head}` and `GET /v1/leaderboard/pub` still show Ana's `score`, `total_questions`, `correct_questions`, `run_cost_usd` | before GREEN the body has no `reported_result`, so the first assertion fails. |
| 13 | SC-10 | `tests/unit/scores/test_cluster_race_postgres.py` | `test_concurrent_new_cluster_one_head_loser_becomes_result` — PostgreSQL only. Build the schema with `Tortoise.generate_schemas()` and then `create_partial_unique_indexes(...)` (SB-schema), so the I-S1 partial index and the unique `run_id` exist. Run two `ClusterStore.submit` calls (Ana and Bruno, same url4, other scores, other keys) with `asyncio.gather`. Assert: one head, two results, exactly one `is_original`, both outcomes have the same head id, one `System` row. | Skipped without `SCOREBOARD_TEST_DATABASE_URL`. With it, before GREEN the store has no behavior. Imitate the skip, the own connection, and the cleanup of `tests/unit/scores/test_idempotency_postgres.py:25-95`. |
| 14 | SC-10a | `test_cluster_race.py` | `test_head_insert_integrity_error_retries_once_as_reported_result` — SQLite. First submit run A (creates head H). Then patch `ClusterStore._find_public_head` so that its FIRST call returns `None` and later calls run the real method. Submit run B with the SAME url4, spec and score (so the new head hash collides with H on the unique `content_hash`) and another key. Assert: 201, response `id == H`, `is_original is False`, `Score.all().count() == 1`, 2 results. | Without the retry the `IntegrityError` leaves as 503. |
| 15 | SC-11 | `test_clustering.py` | `test_legacy_head_same_url4_links_and_clusters` — create a legacy head with `await ScoreStore().submit(ScoreSubmission(**payload(submitted_by=ANA)), identity_verified=True)` (the legacy path, same database, `spec_id="kevins-best"`), then POST the same payload through `clustered_cf_client` with `as_user(ANA)` → the legacy head gets `system_revision_id`; response `id` = legacy id; `is_original is False`; `Score.all().count() == 1` | a new head, or an IntegrityError. |
| 16 | SC-12 | `test_cluster_rules.py` | `test_cluster_key_uses_resolved_revision_not_client_metadata` — `scores.cluster_rules.cluster_revision(ScoreSubmission(benchmark_revision="r2", metadata={"benchmark_revision": "r1"}, ...)) == "r2"`, and metadata-only gives `"r1"`; plus a route check: two submits with typed `r2` and metadata `r1`/`r3` cluster under ONE head whose `benchmark_revision == "r2"` | the stub returns None. |
| 17 | SC-13 | `test_clustering.py` | `test_private_board_cluster_per_submitter_no_registry` — on `priv`: `ANA` twice (other scores) → 1 head, 2 results; Bruno same url4 → a second head; `System.all().count() == 0`; head `metadata["system_fingerprint"]` is set; a client `metadata.system_fingerprint` value is overwritten | clusters absent. |
| 18 | SC-14 | `test_clustering.py` | `test_replay_run_stores_provenance_and_label` — (a) valid claim → row has the four columns plus collapses; the results list item has `replay.reported_by == "client"` and a label that starts with `"replay of "`; (b) table of invalid claims (unknown result; wrong version id; a private result of another user; unknown baseline) → 422 `invalid_replay_claim` and nothing written | columns empty / 201. |
| 19 | SC-14a | `test_replay_access.py` | `test_replay_access_order_owner_private_gated_withdrawn` (unit, 6 rows: owner on private → allow; non-owner private → not_found; non-owner not redistributable → not_found; non-owner withdrawn → withdrawn; non-owner private and withdrawn → not_found; unverified identity equal to reporter → not_found on private) | stub returns "allow". |
| 20 | SC-15 | `test_cluster_rules.py` | `test_partial_receipt_stored_as_partial` — `receipt_columns(ReceiptClaims(cov="partial", n=412, c=420, ...))["cache_coverage_status"] == "partial"`; `result_labels(coverage_status="partial", entry_count=412, call_count=420, replayed_from_result_id=None, replay_hits=None, replay_misses=None) == ["partial cache (412 of 420 calls)"]` | stub. |
| 21 | SC-16 | `test_cluster_rules.py` | `test_new_versioned_result_gets_private_publication_row` — `publication_needed(receipt_columns(claims))` is True, `publication_needed(receipt_columns(None))` is False; plus a route check: no receipt → no `CacheVersionPublication` row | stub. |
| 22 | SC-17 | `test_results_list.py` | `test_results_list_cursor_paged_newest_first` — seed 5 results with set `submitted_at` values (two equal, to prove the `id DESC` tie-break); `limit=2` gives 3 pages, newest first, `next_cursor` null on the last; bad cursor → 422 `invalid_cursor`; `limit=201` → 422; private head: 404 for `as_user(BRUNO)` and for no header, 200 for `as_user(ANA)`, with `Cache-Control: private, no-store` | stub returns 501. |
| 22b | SC-17b (disabled fallback, results list) | `test_results_list.py` | `test_disabled_fallback_results_list_public_ok_private_404` — `clustered_client`: a public head's list is 200 with no header; a private head is 404 for every caller, also with a forged `X-User-Email` (`ReadIdentity` ignores it in `disabled` mode, `core/auth/cloudflare_identity.py:92-96`). The only `disabled` test of this flow. Seed the private head directly with the models (a private write needs a verified identity). | stub returns 501. |
| 23 | SC-22 | `apps/scoreboard/tests/portal/reported-results.test.js` | `test("reportedResultsLink: shows count and link only from two results")` — 1 → null; 2 → text `"2 reported results"`, href `/v1/scores/<id>/results`; a score id with `/` is encoded; missing id → null | file missing (node exits 1). |
| 24 | SC-22a | `test_leaderboard_counts.py` | `test_leaderboard_row_carries_count_only_from_two_results` — 1 result: `score_id` and `reported_results_count` absent from the JSON; after SC-8: `reported_results_count == 2` and `score_id` = head | fields missing. |
| 25 | SC-22b | `test_leaderboard_counts.py` | `test_score_json_unchanged_when_no_e14_fields` — `GET /v1/scores/{id}` of a legacy row has none of `reported_result`, `reported_results_count`, `notices` keys | keys present with null. |
| 26 | metrics | `test_clustering.py` | `test_submit_counts_kind_and_receipt_rejections` — `app.state.metrics.registry.get_sample_value("scoreboard_submits_total", {"kind": "new_head"}) == 1.0`, etc. | counters missing. |

| 27 | SC-8a (disabled fallback, submit) | `test_clustering.py` | `test_disabled_fallback_clusters_by_content_hash_no_registry_no_sub_check` — `clustered_client`: (a) payload without `submitted_by`, and (b) payload with `submitted_by="kevin"` (free text): for each, two POSTs with the same content and different `Idempotency-Key` → one head, 2 results; `System.all().count() == 0`; head `system_revision_id is None`; `spec_id` as sent; (c) a receipt with `sub="someone-else"` is accepted (201; C3 skips the `sub` check in `disabled`) and the five cache columns are set. The only `disabled` test of the submit flow. | the stub raises: 500. |
| 29 | SC-E-size | `test_clustering.py` | `test_url4_over_cap_is_422_not_413` — a `url4_expression` of 32,001 chars → 422 (the existing `schemas.py:378` cap); a registry `Url4TooLarge` (monkeypatch `RegistryService.resolve_for_submit` to raise it) → 422 `url4_too_large`. Nothing written. (D7 X-22) | the 32,001-char half passes at once (CHAR of `schemas.py:378`); the registry half fails: the stub raises (500). |
| 28 | SC-17a | `tests/unit/scores/test_cluster_race_postgres.py` | `test_results_page_p99_under_200ms_at_10000_results` — PostgreSQL only (test-plan §5 "Results list"). Seed one head and 10,000 results with `ReportedResult.bulk_create` (batch 1,000). Time 100 `ClusterStore.results_page(limit=50)` calls with `time.perf_counter`, walking cursors from the first page; assert the 99th value of the sorted times ≤ 0.200 s. | Skipped without the database; with it, the stub page read raises. |

Registry error mapping (SC-E5): add `test_registry_errors_map_to_http` in `test_clustering.py` (supporting SC-8; `clustered_cf_client`, `as_user(ANA)`; the name owner is `BRUNO`): `revision_of="unknown"` → 404 `system_not_found`; another owner's name with a new fingerprint → 409 `system_name_taken` with `suggestion`; `spec_id="Bad/Name"` → 422 `invalid_system_name`.

## 7. Edge cases, what not to do, gates

Edge cases:
- A receipt without `trace_id` in the payload → 403 `cache_version_not_yours` (tid cannot match None).
- A receipt on a legacy-path deploy (`clustering_enabled=False`) → ignored, no error. Log at INFO `e14_fields_ignored` with the field names only.
- `revision_of` on a private board → ignored (no registry on private boards, I-N4). Record this in a `WHY:` comment.
- The same submitter resubmits the same system on a public board → another reported result (erd §2.2: "each later run"). This is intended.
- A NULL `benchmark_revision` escapes I-S1 (SB-schema OD-S4): two concurrent first submits on a board with no registered revision can make two heads. Accepted; record it.
- A new head whose content hash equals a head that is ALREADY linked to another revision → second IntegrityError → 409 `ConcurrentScoreUpdate`. Record it as a known limit in the ledger.
- Two concurrent first submits on a private board can make two heads (no unique key is possible there). Accepted; record it.
- `sub` comparison is casefold on both sides, after strip.
- `cloudflare_headers` with no `X-User-Email`: `_resolve_submitter` answers 401 before any receipt or database work (today's behavior). An untrusted peer: 403.
- The `disabled` fallback with a body `submitted_by` on a public board: content-hash clustering, no system is made (D5). A later switch to `cloudflare_headers` links such a head only through the legacy link rule (SC-D3) when a verified owner submits the same content.

What not to do:
- Do not change `ScoreStore.submit`, `_content_hash`, `_replay_updates`, or any existing test.
- Do not trust any client value about versions, fingerprints or systems (SR-D1, C4 security). Only the receipt sets the five cache columns.
- Do not import `jwt` outside `adapters/`. The core defines the port; the adapter implements it (C11 style, hexagonal).
- Do not import from `apps/aigateway` or from `screamingface`. Do not log a receipt, a key, or author emails (log counts).
- Do not update a `ReportedResult` row after insert (I-R3).
- Do not store AIGateway credentials anywhere; this unit touches none. No OS keychain.
- Do not add a `/metrics` route.

Gates: from the repo root, `uv run .claude/scripts/run_gates.py scoreboard --base "$(git merge-base HEAD e14-reproducible-submission-spec)"`. Then the PostgreSQL module: start `postgres:17-alpine` (see `scoreboard-tests.yml:131-160`) and run `SCOREBOARD_TEST_DATABASE_URL=postgres://scoreboard:scoreboard@localhost:5432/scoreboard_test uv run pytest tests/unit/scores/test_cluster_race_postgres.py -v` in `apps/scoreboard`.

## 8. Verification (definition of done)

1. `uv run .claude/scripts/run_gates.py scoreboard --base "$(git merge-base HEAD e14-reproducible-submission-spec)"` exits 0. The append-only check passes (all new test files).
2. `uv run pytest tests/unit/submissions tests/unit/scores/test_cluster_race_postgres.py -v` shows every row of §6 green; the PostgreSQL row is green with the database set, and skipped without it.
3. `node --test tests/portal/leaderboard-logic.test.js tests/portal/pareto-chart.test.js tests/portal/pareto-chart-review.test.js tests/portal/reported-results.test.js` passes.
4. The full old suite is green with no edit: `uv run pytest -q`.
5. `uv lock --check` passes in `apps/scoreboard` (lock file matches the new dependencies).
6. The PostgreSQL CI job lists the new module, and `tests/unit/guards/test_postgres_regressions_run_in_ci.py` is green.
7. No migration file is in the diff (`git diff --name-only "$(git merge-base HEAD e14-reproducible-submission-spec)" | grep migrations/` is empty).
8. No chart file is in the diff (`git diff --name-only "$(git merge-base HEAD e14-reproducible-submission-spec)" -- apps/scoreboard/charts` is empty; D6).
9. Design review (Opus) with this plan as the rubric. Then commit on `unit/SB-submit` for the integrator (D1). No PR.

## 9. Open decisions and spec gaps

- **G4 (open).** SB-schema's backfill `0019` sets `run_id` from raw `metadata.run_id`. For private boards the key must be the scoped `sfp-` token, or a pre-E14 private resend creates a duplicate result. No decision covers it. This unit does not change `0019`.

## 10. Decided

- **OD-1 — Decided: D6.** The flag `SCOREBOARD_CLUSTERING_ENABLED` stays (code default False). Unit WIRING sets it in the chart and in `screamingface up`.
- **OD-2 — Decided: D5.** Production runs `cloudflare_headers`. The receipt `sub` check runs there, and the owner and reporter are the verified email. The `disabled` mode is a dev/local fallback that skips the `sub` check (C3).
- **OD-3 — Decided: D7 X-15.** Counters stay in process. No `/metrics` route.
- **OD-4 — decided (default).** The portal link goes to the JSON endpoint. No portal results page in this unit.
- **OD-5 — Decided: D5.** The registry runs only with a verified identity. The `disabled` fallback clusters by content hash, keeps `spec_id` as sent, ignores `revision_of`, and still records the receipt (§4.5 step 5.2, SC-8a).
- **G1 — resolved (cross-plan fix 4).** SDK-submit sends `trace_id` with the receipt. This unit refuses a receipt whose `tid` differs.
- **G2 — Decided: D7 X-8.** `{"detail": {"code", "message", ...}}`.
- **G3 — resolved (cross-plan fix 2).** SB-schema 0018 has `replay_repeated_key_collapses`.
- **G5 — decided (default).** `ReportedResult.answer_seed` is stored as NULL.
- **G6 — decided (default).** The partial label shows `n of c` (entries of calls).
- **G7 — resolved by SB-schema §4.5.** The head FK is CASCADE, so the delete, purge and retire CLIs keep working. NO ACTION on the replay FKs is SB-schema OD-S2 (D8): the delete of a head removes its in-cluster replays, and a replay in another cluster blocks the delete of its original.
- **G8 — Decided: D7 X-3.** PyJWT EdDSA behind the `ReceiptVerifier` port. No shared package.
- **Size cap — Decided: D7 X-22.** The 32,000-char cap with 422; `Url4TooLarge` maps to 422.
