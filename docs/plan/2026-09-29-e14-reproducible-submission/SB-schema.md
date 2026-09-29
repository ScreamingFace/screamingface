# SB-schema — scoreboard schema foundation for E14 (OME-1307) — implementation plan

Epic: [OME-1307](https://linear.app/openmined/issue/OME-1307) · Component: `apps/scoreboard` ·
Wave: 1 · Stack card: `scoreboard` (skill `sdlc-python`, companion `tortoise-dev`).

Spec (the rubric): `docs/spec/2026-09-29-e14-reproducible-submission/erd.md` §2, §6 (read in
full), `contracts.md` C11, `test-plan.md` §1 and §7.

Delivery (D1): build this unit in its own temporary worktree on the branch `unit/SB-schema`,
made from the HEAD of `e14-reproducible-submission-spec`
(`git checkout -B unit/SB-schema e14-reproducible-submission-spec`). Do not open a PR. Do not
file a Linear issue. After wave 1, the integrator merges `unit/SB-schema` into
`e14-reproducible-submission-spec` and runs the gates. The plan is this file,
`docs/plan/2026-09-29-e14-reproducible-submission/SB-schema.md`. Start the ledger at
`docs/work/2026-09-29-e14-sb-schema.md` before the first RED.

One SDLC unit, one stack (`scoreboard`), backend only. RED before GREEN at every step.
This unit adds tables, columns, indexes and a data backfill. It adds **no** behavior. No
route, store method or portal file reads the new data yet.

## 1. Scope

### 1.1 In scope

The unit map gives this unit "migrations 0017-0019 (erd §6) + models; backfill idempotency
test; no behavior". No PRD TDD table owns these rows, so this plan names its own ids (`SCH-`).

| Id | Test | What it proves |
|---|---|---|
| SCH-1 | `test_sch1_migrations_apply_to_a_populated_sqlite_database` | 0017-0019 apply after 0016 on a database that already has benchmarks and scores |
| SCH-2 | `test_sch2_backfill_creates_one_original_result_per_score` | 0019 writes one `ReportedResult(is_original=true)` per `Score`, with the copied numbers |
| SCH-3 | `test_sch3_backfill_is_idempotent_and_skips_a_head_with_an_original` | a head that already has an original gets no second one; a back-and-forward rerun adds nothing |
| SCH-4 | `test_sch4_backfill_run_id_rules` | `run_id` comes from `metadata.run_id`; a duplicate, a non-string, a blank or an over-128-char value becomes `NULL` |
| SCH-5 | `test_sch5_one_original_result_per_score_is_enforced` | the partial unique index rejects a second `is_original=true` row for one score |
| SCH-6 | `test_sch6_one_public_head_per_system_revision_is_enforced` | the partial unique index rejects a second head for one `(benchmark_id, benchmark_revision, system_revision_id)` |
| SCH-7 | `test_sch7_partial_index_ddl_matches_the_migration` | the DDL constant that tests use is byte-equal to the SQL in migration 0018 |
| SCH-8 | `test_sch8_new_models_round_trip_and_enforce_unique_columns` | the five new models write and read; `System.name`, `SystemRevision.fingerprint`, `(system, revision)`, `ReportedResult.run_id`, `ReportedResult.cache_version_id` are unique |
| SCH-9 | `test_sch9_an_insert_from_old_code_gets_database_defaults` | a raw `INSERT` that omits the new columns (what an old pod sends during a rollout) stores `metadata_revision = 1` and `redistributable = false` |
| SCH-10 | `test_sch10_deleting_a_score_cascades_its_results_and_events` | `delete_scores` and `purge_private_benchmark` keep working: the new child rows go with the score |
| SCH-11 | `test_sch11_score_schema_output_is_unchanged_for_a_legacy_row` | `ScoreSchema` JSON and the private-export bytes of a legacy row do not change |
| SCH-12 | `test_sch12_migrations_apply_on_postgres` | the same chain applies on PostgreSQL, the PostgreSQL-only foreign key exists, the partial indexes exist |
| SCH-13 | `test_sch13_partial_index_fixture_creates_the_indexes` | the new test fixture adds the two partial indexes to a `generate_schemas` database |

CHAR (must stay green, do not edit):
`tests/unit/test_leaderboard_routes.py::test_every_score_field_reaches_at_least_one_read_dto`.

### 1.2 Out of scope

- Every PRD test id (MD-, SR-, SC-, RP-, PB-). Other units own them.
- Any route, store method, SDK change, portal change, or seed change.
- Reading or writing `paper_url`, `metadata_revision`, `system_revision_id` from the API.
- The `backfill-systems` command (SB-registry owns it).
- The `packages/url4` dependency (SB-registry owns it).
- Gateway tables (GW-capture owns them).

## 2. Depends on

- Units that must merge first: **none** (wave 1).
- Integration notes (D2): no other scoreboard unit is in wave 1. URL4-fp and GW-capture
  change other components, so this unit shares no file with them.
- Contracts: none implemented. This unit makes the storage that C4, C5, C6 and C10 need.
- C11: this unit adds no import. It must not import `url4` or `screamingface`.
- Later units that build on this unit: SB-meta, SB-registry, SB-submit, SB-grants, SB-publish.
  Tell them: new Score columns are `paper_url`, `metadata_revision`, `metadata_updated_at`,
  `system_revision_id` (a plain UUID column with no index of its own, see §4.2 and OD-S1).
  `ReportedResult` attributes are `head_id`, `replayed_from_id`, `pinned_baseline_id`; their
  columns are `score_id`, `replayed_from_result_id`, `pinned_baseline_result_id` (erd.md §2.2).

## 3. Files

| Path | Change | Exemplar to imitate |
|---|---|---|
| `apps/scoreboard/src/scoreboard/scores/models/score.py` | change: four new fields on `BaseScore` | the field-plus-anchor style at `score.py:41-49` |
| `apps/scoreboard/src/scoreboard/scores/models/benchmark.py` | change: `redistributable` on `BaseBenchmark` | `benchmark.py:39-51` |
| `apps/scoreboard/src/scoreboard/scores/models/system.py` | create: `BaseSystem`, `System`, `BaseSystemRevision`, `SystemRevision` | `scores/models/idempotency_key.py:8-34` (abstract base plus concrete class with the FK) |
| `apps/scoreboard/src/scoreboard/scores/models/reported_result.py` | create: `BaseReportedResult`, `ReportedResult` | `scores/models/idempotency_key.py:8-34`, fields as `score.py:10-156` |
| `apps/scoreboard/src/scoreboard/scores/models/score_metadata_event.py` | create: `BaseScoreMetadataEvent`, `ScoreMetadataEvent` | `scores/models/idempotency_key.py:8-34` |
| `apps/scoreboard/src/scoreboard/scores/models/cache_version_publication.py` | create: `BaseCacheVersionPublication`, `CacheVersionPublication` | `scores/models/idempotency_key.py:8-34` |
| `apps/scoreboard/src/scoreboard/scores/models/partial_indexes.py` | create: `PARTIAL_UNIQUE_INDEX_SQL`, `create_partial_unique_indexes()` | module-level constant style at `scores/store.py:520-527` |
| `apps/scoreboard/src/scoreboard/scores/models/__init__.py` | change: export the new classes, extend `__all__` | `models/__init__.py:1-19` |
| `apps/scoreboard/src/scoreboard/scores/migrations/0017_e14_score_metadata_columns.py` | create | `migrations/0016_score_enriched_at.py:1-23`, `0008_benchmark_visibility.py:43-53` |
| `apps/scoreboard/src/scoreboard/scores/migrations/0018_e14_registry_and_results_tables.py` | create | `migrations/0001_initial.py:14-116` (`CreateModel`), `0008_benchmark_visibility.py:49-52` (`RunSQL`) |
| `apps/scoreboard/src/scoreboard/scores/migrations/0019_e14_backfill_original_results.py` | create | `migrations/0009_idempotency_key_namespaces.py` (data migration) |
| `apps/scoreboard/src/scoreboard/scores/schemas.py` | change: four inert fields on `ScoreSchema` | `schemas.py:688-745` (`exclude_if` pattern) |
| `apps/scoreboard/src/scoreboard/scores/store.py` | change: project the four fields in `_score_to_schema` | `store.py:96-136` |
| `apps/scoreboard/tests/conftest.py` | change: **append** one new fixture function at the end (do not touch existing bodies) | `tests/conftest.py:73-84` |
| `apps/scoreboard/tests/unit/test_migration_e14_schema.py` | create: SCH-1 to SCH-7, SCH-9 | `tests/unit/test_migration_0009_idempotency_namespaces.py:1-77` |
| `apps/scoreboard/tests/unit/scores/test_e14_models.py` | create: SCH-8, SCH-10, SCH-11, SCH-13 | `tests/unit/scores/test_models.py` |
| `apps/scoreboard/tests/unit/test_migration_e14_postgres.py` | create: SCH-12 | `tests/unit/test_delete_scores_postgres.py:1-80`, `tests/conftest.py:42-70` |
| `.github/workflows/scoreboard-tests.yml` | change: name `tests/unit/test_migration_e14_postgres.py` in the `postgres` job | `scoreboard-tests.yml:166-174` |
| `apps/scoreboard/DEPLOYMENT.md` | change: one paragraph under "Breaking migrations and multi-replica rollouts" that says 0017-0019 are expand-only and safe for a rolling rollout | `DEPLOYMENT.md:276-283` |

Do **not** edit any existing test function body. The append-only gate
(`.claude/scripts/run_gates.py:381`) fails on it.

## 4. Signatures and data shapes

### 4.1 Common rules

- Every model file has an abstract `Base<Name>(BaseScoreboardModel)` with `class Meta: abstract
  = True`, and a concrete `<Name>(Base<Name>)` with `class Meta: table = "<table>"`. FK fields
  go on the concrete class (the repo rule, `idempotency_key.py:26-34`).
- Every UUID primary key is `fields.UUIDField(primary_key=True, default=uuid.uuid4)`.
- Every FK that points **to `Score`** uses `related_name=False`. WHY: the CHAR guard
  `test_every_score_field_reaches_at_least_one_read_dto` reads `Score._meta.fields_map`, and a
  reverse relation adds a key there. The guard is append-only, so we cannot allowlist the key.
  Tortoise supports `related_name=False` (`tortoise/fields/relational.py:319`,
  `tortoise/apps.py:206`).
- Put a one-line `FEATURE: OME-1307 (E14) — …` anchor on each new model, and a `WHY` or
  `INVARIANT` anchor where the table in erd.md states a rule.

### 4.2 `Score` (table `scores`) — new fields on `BaseScore`

```python
# FEATURE: OME-1307 (E14a) — editable citation link. Owner-editable; http(s) only (SB-meta).
paper_url = fields.CharField(max_length=2048, null=True)
# INVARIANT (E14a): the optimistic-concurrency token for metadata edits. Starts at 1.
# WHY db_default: an old pod that does not know this column omits it on INSERT during a
# rolling rollout; the database default keeps the NOT NULL column valid (DEPLOYMENT.md).
metadata_revision = fields.IntField(default=1, db_default=1)
metadata_updated_at = fields.DatetimeField(null=True)
# FEATURE: OME-1307 (E14) — the system revision this head clusters under. NULL on legacy and
# private-board rows (erd.md §2.4).
# WHY a plain UUID column and not a ForeignKeyField: see OD-S1. PostgreSQL gets a real FK
# constraint from migration 0018; SQLite (tests, local runtime) does not.
# WHY no db_index: Tortoise 1.1.8 `AddField` does not create the index of a `db_index=True`
# field (`tortoise/migrations/schema_editor/base.py:501-555` has no index step), so the model
# state would claim an index the database lacks. The I-S1 partial unique index (§4.8) already
# covers the lookup `(benchmark_id, benchmark_revision, system_revision_id)`.
system_revision_id = fields.UUIDField(null=True)
```

### 4.3 `Benchmark` (table `benchmarks`) — new field on `BaseBenchmark`

```python
# INVARIANT (E14): fail-closed. Only `true` lets a public board publish to GitHub or serve
# replay to a non-owner (erd.md §2.7).
redistributable = fields.BooleanField(default=False, db_default=False)
```

### 4.4 `System` (table `system`) and `SystemRevision` (table `system_revision`)

```python
class BaseSystem(BaseScoreboardModel):
    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    name = fields.CharField(max_length=64, unique=True)       # normalized, erd.md §2.3.1
    owner = fields.CharField(max_length=255)
    created_at = fields.DatetimeField(auto_now_add=True)

class BaseSystemRevision(BaseScoreboardModel):
    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    revision = fields.IntField()
    fingerprint = fields.CharField(max_length=64, unique=True)
    candidate_url4 = fields.TextField()
    declared_by = fields.CharField(max_length=255)
    created_at = fields.DatetimeField(auto_now_add=True)

class SystemRevision(BaseSystemRevision):
    class Meta:
        table = "system_revision"
        unique_together = (("system", "revision"),)
    system = fields.ForeignKeyField(
        "models.System", related_name="revisions", on_delete=fields.OnDelete.RESTRICT
    )
```

### 4.5 `ReportedResult` (table `reported_result`)

The FK to `Score` cannot be named `score`: erd.md §2.2 also names the result number `score`.
Name the FK attribute `head` and pin its column with `source_field="score_id"`.

```python
class BaseReportedResult(BaseScoreboardModel):
    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    is_original = fields.BooleanField()
    reporter = fields.CharField(max_length=255, null=True)
    run_id = fields.CharField(max_length=128, null=True, unique=True)
    trace_id = fields.CharField(max_length=32, null=True)
    score = fields.FloatField()
    total_questions = fields.IntField()
    correct_questions = fields.IntField(null=True)
    run_cost_usd = fields.DecimalField(max_digits=12, decimal_places=6, null=True)
    run_cost_status = fields.CharField(max_length=16, null=True)
    cache_saved_cost_usd = fields.DecimalField(max_digits=12, decimal_places=6, null=True)
    models = fields.JSONField(null=True)
    ran_with_providers = fields.JSONField(null=True)
    answer_seed = fields.IntField(null=True)
    client_name = fields.CharField(max_length=128, null=True)
    client_version = fields.CharField(max_length=64, null=True)
    client_platform = fields.CharField(max_length=32, null=True)
    submitted_at = fields.DatetimeField(auto_now_add=True)
    cache_version_id = fields.UUIDField(null=True, unique=True)   # I-R4
    cache_version_sha256 = fields.CharField(max_length=64, null=True)
    cache_entry_count = fields.IntField(null=True)
    cache_call_count = fields.IntField(null=True)
    cache_coverage_status = fields.CharField(max_length=16, null=True)
    replay_hits = fields.IntField(null=True)
    replay_misses = fields.IntField(null=True)
    replay_repeated_key_collapses = fields.IntField(null=True)   # C4 replay.repeated_key_collapses (RP-D5); cross-plan fix, SB-submit G3

class ReportedResult(BaseReportedResult):
    class Meta:
        table = "reported_result"
        indexes = (("head_id", "submitted_at"),)
    head = fields.ForeignKeyField(
        "models.Score", source_field="score_id", related_name=False,
        on_delete=fields.OnDelete.CASCADE,
    )
    replayed_from = fields.ForeignKeyField(
        "models.ReportedResult", source_field="replayed_from_result_id", related_name=False,
        null=True, on_delete=fields.OnDelete.RESTRICT,
    )
    pinned_baseline = fields.ForeignKeyField(
        "models.ReportedResult", source_field="pinned_baseline_result_id", related_name=False,
        null=True, on_delete=fields.OnDelete.RESTRICT,
    )
```

- `head` CASCADE: WHY — `delete_scores`, `purge_private_benchmark` and `retire_benchmark`
  delete `Score` rows with the ORM (`delete_scores.py:150`, `purge_private_benchmark.py:120`),
  and 0019 gives every score a child row. RESTRICT would break all three tools on deploy.
  This matches `IdempotencyKey.score` (`idempotency_key.py:30-34`).
- `replayed_from` / `pinned_baseline` RESTRICT: see OD-S2.
- Column names follow erd.md §2.2 exactly: `score_id`, `replayed_from_result_id`,
  `pinned_baseline_result_id`. The Python attributes stay `head_id`, `replayed_from_id` and
  `pinned_baseline_id` (Tortoise names the key attribute `<field>_id` and uses `source_field`
  only as the column, `tortoise/apps.py:190-205`). SB-submit uses these attribute names.
- Write the index as `indexes = (("head_id", "submitted_at"),)`, with the key attribute
  `head_id`, **not** `head`. WHY: the index resolver uses `field.source_field or name`
  (`tortoise/migrations/schema_editor/base.py:412-417`); for the key attribute `head_id` the
  source field is the column `score_id`, but for the relation `head` Tortoise overwrites
  `source_field` with the attribute name `head_id` (`tortoise/apps.py:205`), which is not a
  column. SCH-8 asserts that an index on the **column** `score_id` exists.
- The I-R1 and I-R2 "all set or all null" rules are not database constraints in this unit.
  SB-submit enforces them in code.

### 4.6 `ScoreMetadataEvent` (table `score_metadata_event`)

```python
class BaseScoreMetadataEvent(BaseScoreboardModel):
    id = fields.UUIDField(primary_key=True, default=uuid.uuid4)
    # INVARIANT (D5): production (cloudflare_headers) always stores the verified X-User-Email.
    # NULL only in the auth_mode=disabled dev/local fallback, where no verified identity exists.
    actor = fields.CharField(max_length=255, null=True)
    at = fields.DatetimeField(auto_now_add=True)
    from_revision = fields.IntField()
    to_revision = fields.IntField()
    before = fields.JSONField()   # {"authors": list[str] | None, "paper_url": str | None}
    after = fields.JSONField()    # same shape

class ScoreMetadataEvent(BaseScoreMetadataEvent):
    class Meta:
        table = "score_metadata_event"
        unique_together = (("score", "to_revision"),)
    score = fields.ForeignKeyField(
        "models.Score", related_name=False, on_delete=fields.OnDelete.CASCADE
    )
```

INVARIANT anchor: append-only; no code updates or deletes a row (erd.md §2.5). The only
delete is the cascade from its score.

### 4.7 `CacheVersionPublication` (table `cache_version_publication`)

```python
class BaseCacheVersionPublication(BaseScoreboardModel):
    state = fields.CharField(max_length=16, default="private")
    requested_by = fields.CharField(max_length=255, null=True)
    requested_at = fields.DatetimeField(null=True)
    attempts = fields.IntField(default=0)
    next_attempt_at = fields.DatetimeField(null=True)
    lease_until = fields.DatetimeField(null=True)
    last_error = fields.CharField(max_length=512, null=True)
    release_tag = fields.CharField(max_length=64, null=True)
    release_url = fields.CharField(max_length=512, null=True)
    published_at = fields.DatetimeField(null=True)
    withdrawn_at = fields.DatetimeField(null=True)
    withdrawn_by = fields.CharField(max_length=255, null=True)
    withdrawn_reason = fields.TextField(null=True)

class CacheVersionPublication(BaseCacheVersionPublication):
    class Meta:
        table = "cache_version_publication"
        indexes = (("state", "next_attempt_at"),)
    result = fields.OneToOneField(
        "models.ReportedResult", primary_key=True, related_name="publication",
        on_delete=fields.OnDelete.CASCADE,
    )
```

Tortoise accepts a `OneToOneField` as the primary key (`tortoise/models.py:703-710`, column
`result_id`). If SCH-8 shows it does not work, fall back to `id` UUID PK plus
`result = fields.OneToOneField("models.ReportedResult", related_name="publication",
on_delete=CASCADE)` (a one-to-one is unique). Record the fallback in the ledger.

### 4.8 Partial unique indexes — `scores/models/partial_indexes.py`

Tortoise cannot make these two indexes portably: `AddConstraint` with a `condition` raises on
SQLite (`tortoise/migrations/schema_editor/sqlite.py:150-153`), and `generate_schemas` ignores
`Meta.constraints`. Plain SQL works on both SQLite and PostgreSQL.

```python
"""Partial unique indexes that Tortoise cannot declare (E14, OME-1307).

INVARIANT: byte-equal to the RunSQL in migration 0018. SCH-7 asserts it. Tests that build
their schema with `generate_schemas` apply these through `create_partial_unique_indexes`.
"""
from tortoise import BaseDBAsyncClient

ONE_ORIGINAL_PER_SCORE_SQL = (
    'CREATE UNIQUE INDEX IF NOT EXISTS "uidx_reported_result_one_original" '
    'ON "reported_result" ("score_id") WHERE "is_original"'
)
ONE_PUBLIC_HEAD_PER_SYSTEM_REVISION_SQL = (
    'CREATE UNIQUE INDEX IF NOT EXISTS "uidx_scores_public_head" '
    'ON "scores" ("benchmark_id", "benchmark_revision", "system_revision_id") '
    'WHERE "system_revision_id" IS NOT NULL'
)
PARTIAL_UNIQUE_INDEX_SQL: tuple[str, ...] = (
    ONE_ORIGINAL_PER_SCORE_SQL,
    ONE_PUBLIC_HEAD_PER_SYSTEM_REVISION_SQL,
)

async def create_partial_unique_indexes(connection: BaseDBAsyncClient) -> None:
    for statement in PARTIAL_UNIQUE_INDEX_SQL:
        await connection.execute_script(statement)
```

AIDEV-NOTE on `uidx_scores_public_head`: a NULL `benchmark_revision` is not unique-checked
(both engines treat NULLs as distinct). SB-submit must know this (OD-S4).

### 4.9 `ScoreSchema` — four inert fields (keeps the CHAR guard green)

Add after `cache_saved_cost_usd` (`schemas.py:731`). Each one is excluded at its default, so
no response and no private export changes for a legacy row (SCH-11). This is the same trap
`OME-1181` Q2 records at `schemas.py:689-702`.

```python
paper_url: str | None = Field(default=None, exclude_if=lambda value: value is None)
# AIDEV-NOTE: excluded at 1 in this unit only. SB-meta makes it always present in API
# responses and moves the "drop at 1" rule into the private export (see SB-meta plan).
metadata_revision: int = Field(default=1, exclude_if=lambda value: value == 1)
metadata_updated_at: datetime | None = Field(default=None, exclude_if=lambda value: value is None)
system_revision_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)
```

In `_score_to_schema` (`store.py:96-136`) add `paper_url=model.paper_url`,
`metadata_revision=model.metadata_revision`, `metadata_updated_at=model.metadata_updated_at`,
`system_revision_id=model.system_revision_id`.

### 4.10 Test fixture — append to `tests/conftest.py`

```python
@pytest_asyncio.fixture
async def partial_unique_indexes(tortoise_db: None) -> None:
    """The two E14 partial unique indexes, which `generate_schemas` cannot create."""
    from tortoise import Tortoise
    from scoreboard.scores.models.partial_indexes import create_partial_unique_indexes
    await create_partial_unique_indexes(Tortoise.get_connection("default"))
```

Later units (SB-submit, SC-10) request this fixture.

### 4.11 Ports and adapters

None. This unit adds storage only. The `scores/models` package is the Tortoise adapter layer
that later ports (`SystemRepository` in SB-registry) use.

### 4.12 Ed25519 JWS

None in this unit. (Receipt verify is SB-submit; grant sign is SB-grants. Both use PyJWT
EdDSA behind a scoreboard-local port. Decided: D7 X-3, no shared package.)

## 5. Migrations

Current head: `apps/scoreboard/src/scoreboard/scores/migrations/0016_score_enriched_at.py`.
All three migrations are **expand-only**: they add columns with a default or `NULL`, add
tables and indexes, and add rows. They rename nothing and drop nothing, so old pods keep
working during a rolling rollout (`DEPLOYMENT.md:262-283`).

Generate the model part with `uv run tortoise makemigrations --name <name>` (Tortoise built-in,
never Aerich), then edit each file to the exact content below. Run `uv run tortoise migrate`
twice from an empty database: the second run must be a no-op. Then run `makemigrations` once
more: it must write **no** new file (the migration state matches the models). If it writes
one, fix the migration, not the model. Fix any `ruff` finding in the generated file; never relax
a gate.

### 5.1 `0017_e14_score_metadata_columns.py`

- `dependencies = [("models", "0016_score_enriched_at")]`.
- Operations, in this order:
  1. `AddField("Score", "paper_url", CharField(max_length=2048, null=True))`
  2. `AddField("Score", "metadata_revision", IntField(default=1, db_default=1))`
  3. `AddField("Score", "metadata_updated_at", DatetimeField(null=True))`
  4. `AddField("Score", "system_revision_id", UUIDField(null=True))`
  5. `AddField("Benchmark", "redistributable", BooleanField(default=False, db_default=False))`
- WHY `db_default` and not the 0008 pattern (nullable plus backfill): Tortoise 1.1.8 emits
  `ADD COLUMN … NOT NULL DEFAULT 1` when `db_default` is set
  (`tortoise/migrations/schema_editor/base.py:542-548`). SQLite and PostgreSQL both accept a
  NOT NULL column with a constant default on a populated table. So no nullable phase is needed.
  SCH-1 and SCH-12 prove it on both engines.

### 5.2 `0018_e14_registry_and_results_tables.py`

- `dependencies = [("models", "0017_e14_score_metadata_columns")]`.
- Operations, in this order:
  1. `CreateModel` `System`, then `SystemRevision`, then `ReportedResult`, then
     `ScoreMetadataEvent`, then `CacheVersionPublication` (the generated form, as in
     `0001_initial.py:15-115`).
  2. `RunSQL(ONE_ORIGINAL_PER_SCORE_SQL-text, reverse_sql='DROP INDEX IF EXISTS "uidx_reported_result_one_original"')`
  3. `RunSQL(ONE_PUBLIC_HEAD_PER_SYSTEM_REVISION_SQL-text, reverse_sql='DROP INDEX IF EXISTS "uidx_scores_public_head"')`
  4. `RunPython(_add_postgres_system_revision_fk, reverse_code=_drop_postgres_system_revision_fk)`.
- Write the SQL text **inline** as string literals in the migration. Do not import
  `partial_indexes.py`: a migration is frozen history and must not change when app code
  changes. SCH-7 holds the two copies equal.
- `_add_postgres_system_revision_fk(apps, schema_editor)`: when
  `schema_editor.DIALECT == "postgres"`, run
  `ALTER TABLE "scores" ADD CONSTRAINT "fk_scores_system_revision" FOREIGN KEY ("system_revision_id") REFERENCES "system_revision" ("id") ON DELETE RESTRICT`
  through `await schema_editor.client.execute_script(sql)`. On any other dialect do nothing.
  WHY: SQLite cannot add a constraint to an existing table. The reverse drops the constraint
  on PostgreSQL (`ALTER TABLE "scores" DROP CONSTRAINT IF EXISTS "fk_scores_system_revision"`).

### 5.3 `0019_e14_backfill_original_results.py`

- `dependencies = [("models", "0018_e14_registry_and_results_tables")]`.
- One operation: `RunPython(_backfill, reverse_code=_noop)`. `_noop` is an `async def` that
  does nothing (the rows are harmless after a schema rollback of this step).
- `_backfill(apps, schema_editor)`, with `client = schema_editor.client`:
  1. Run this portable SQL (the same text on SQLite and PostgreSQL):

     ```sql
     INSERT INTO "reported_result" (
       "id", "score_id", "is_original", "reporter", "run_id", "trace_id",
       "score", "total_questions", "correct_questions",
       "run_cost_usd", "run_cost_status", "cache_saved_cost_usd",
       "models", "ran_with_providers", "answer_seed",
       "client_name", "client_version", "client_platform", "submitted_at")
     SELECT s."id", s."id", TRUE, s."submitted_by", NULL, NULL,
       s."score", s."total_questions", s."correct_questions",
       s."run_cost_usd", s."run_cost_status", s."cache_saved_cost_usd",
       s."models", s."ran_with_providers", NULL,
       s."client_name", s."client_version", s."client_platform", s."submitted_at"
     FROM "scores" s
     WHERE NOT EXISTS (
       SELECT 1 FROM "reported_result" r WHERE r."score_id" = s."id" AND r."is_original")
     ```

     WHY `id = score id`: the backfill must be deterministic and must need no UUID function
     (SQLite has none). A later uuid4 cannot collide in practice. WHY `NOT EXISTS`: this is
     the idempotency rule of erd.md §6.3 ("skips a head that already has an original").
  2. Fill `run_id` in Python:
     - `rows = await client.execute_query_dict('SELECT "id", "metadata", "submitted_at" FROM "scores" ORDER BY "submitted_at", "id"')`.
     - Decode `metadata` with `json.loads` when it is a `str` (SQLite returns text; asyncpg
       can return text for JSONB). Take `metadata.get("run_id")`.
     - Keep it only when it is a `str`, `value.strip() == value`, `0 < len(value) <= 128`.
     - Keep only the **first** score (by `submitted_at`, then `id`) for each value. Every
       later duplicate stays `NULL`. WHY: `run_id` is `UNIQUE`, and a duplicate would fail the
       whole migration on deploy.
     - Also skip a value that some `reported_result` row already holds (a rerun).
     - For each kept pair, run
       `UPDATE "reported_result" SET "run_id" = <p1> WHERE "id" = <p2> AND "is_original" AND "run_id" IS NULL`
       with `<p1>, <p2>` = `?, ?` when `schema_editor.DIALECT == "sqlite"`, else `$1, $2`.
       Pass the `id` value exactly as `execute_query_dict` returned it.
- Keep `_backfill` under the complexity caps (`pyproject.toml:33-40`): split into small
  helpers (`_insert_originals`, `_run_id_pairs`, `_apply_run_ids`).

## 6. TDD order (RED first, in risk order)

Before any RED: create the five model files with the classes and **no** fields except `id`,
register them in `models/__init__.py`, create `partial_indexes.py` with empty strings, and
append the `partial_unique_indexes` fixture of §4.10 to `tests/conftest.py`. So each RED below
fails on an assertion, not on an import error.

1. **SCH-9** (R11 legacy board changes on deploy; rollout safety) —
   `tests/unit/test_migration_e14_schema.py::test_sch9_an_insert_from_old_code_gets_database_defaults`.
   Migrate a file SQLite database to head with the `_migrate` subprocess helper (copy
   `test_migration_0009_idempotency_namespaces.py:13-28`). With `sqlite3`, insert a benchmark
   and a score with **only** the 0016 columns. First assert
   `{"metadata_revision", "paper_url", "metadata_updated_at", "system_revision_id"} <= columns`
   from `PRAGMA table_info("scores")` and `"redistributable"` in `PRAGMA table_info("benchmarks")`;
   then assert `metadata_revision == 1` and `redistributable == 0` on the inserted rows. RED
   reason: the column-set assertion fails, because 0017 does not exist yet.
2. **SCH-1** — `test_sch1_migrations_apply_to_a_populated_sqlite_database`: migrate to `0016`,
   seed two benchmarks and three scores with `sqlite3`, migrate to head. Assert return code 0,
   the five new tables exist (`sqlite_master`), and every legacy score has
   `metadata_revision = 1` and `paper_url IS NULL`. RED: the tables do not exist.
3. **SCH-2** — `test_sch2_backfill_creates_one_original_result_per_score`: same seed. Assert
   one `reported_result` row per score, `id == score_id`, `is_original = 1`,
   `reporter == submitted_by`, and `score`, `total_questions`, `run_cost_usd`,
   `submitted_at` equal the score's. RED: no rows (0019 is empty).
4. **SCH-3** — `test_sch3_backfill_is_idempotent_and_skips_a_head_with_an_original`: migrate
   to `0018`; insert a `reported_result` original (a uuid4 id, not the score id) for score A;
   migrate to head. Assert A has exactly one original and its id is the uuid4 one; B and C have
   one each. Then migrate back to `0018` (`_migrate(url, "0018_e14_registry_and_results_tables")`)
   and forward to head again. Assert the row count and ids are unchanged. RED: before step 1 of
   §5.3 has `NOT EXISTS`, A gets two originals and the partial index raises.
5. **SCH-4** — `test_sch4_backfill_run_id_rules`: seed scores whose `metadata` holds
   `{"run_id": "r-1"}`, `{"run_id": "r-1"}` (later), `{"run_id": 7}`, `{"run_id": " "}`,
   `{"run_id": "x" * 129}`, `{}`, and `NULL`. Assert only the first `r-1` row carries a
   `run_id`. RED: `run_id` is always NULL.
6. **SCH-5** — `test_sch5_one_original_result_per_score_is_enforced`: on the migrated SQLite
   file, a second `is_original = 1` row for one score raises `sqlite3.IntegrityError`; a row
   with `is_original = 0` for the same score succeeds. RED: no index yet.
7. **SCH-6** — `test_sch6_one_public_head_per_system_revision_is_enforced`: insert a
   `system` and `system_revision`, then two scores with the same `benchmark_id`,
   `benchmark_revision = 'r1'` and `system_revision_id`. The second raises. Two scores with
   `system_revision_id IS NULL` both succeed. RED: no index yet.
8. **SCH-7** — `test_sch7_partial_index_ddl_matches_the_migration`: import the migration with
   `importlib.import_module("scoreboard.scores.migrations.0018_e14_registry_and_results_tables")`,
   collect `op.sql` of every `RunSQL` op, and assert it equals
   `list(PARTIAL_UNIQUE_INDEX_SQL)`. RED: the constant holds empty strings.
9. **SCH-8** — `tests/unit/scores/test_e14_models.py::test_sch8_new_models_round_trip_and_enforce_unique_columns`
   (`tortoise_db` fixture): create one of each model and read it back. Then assert
   `IntegrityError` for a duplicate `System.name`, a duplicate `SystemRevision.fingerprint`, a
   duplicate `(system, revision)`, a duplicate `ReportedResult.run_id` and a duplicate
   `ReportedResult.cache_version_id`. Also assert that the `reported_result` table has an index
   on `score_id` (read the index list from the connection). RED: the fields do not exist yet.
10. **SCH-13** — `test_sch13_partial_index_fixture_creates_the_indexes`: request the new
    `partial_unique_indexes` fixture; assert a second original for one score raises
    `IntegrityError`. Append the fixture of §4.10 to `tests/conftest.py` in the pre-RED stub
    step (it calls `create_partial_unique_indexes`, which runs the constants). RED: the
    constants are still empty strings, so no index exists and `pytest.raises(IntegrityError)`
    fails with "DID NOT RAISE". In the stub, make `create_partial_unique_indexes` skip an
    empty statement.
11. **SCH-10** — `test_sch10_deleting_a_score_cascades_its_results_and_events`: create a
    score, a `ReportedResult` and a `ScoreMetadataEvent` for it, then
    `await Score.filter(id=score.id).delete()`. Assert both child tables are empty. Also delete a
    second seeded score the operator way: `reviewed = await delete_scores(benchmark_id,
    score_ids=[id], expected=1)`, then `await delete_scores(benchmark_id, score_ids=[id],
    expected=1, confirmed=True, expected_sha256=reviewed.sha256())` (the `_confirm` helper at
    `tests/unit/test_delete_scores.py:70-88`), and assert the score and its child rows are gone. RED: with RESTRICT, the delete
    raises.
12. **SCH-11** — `test_sch11_score_schema_output_is_unchanged_for_a_legacy_row`: store a
    score through `ScoreStore.submit`; assert `ScoreSchema.model_dump(mode="json")` has none
    of the keys `paper_url`, `metadata_updated_at`, `system_revision_id`; assert that the
    parsed line of `format_jsonl_bytes([row])` has none of the four keys `paper_url`,
    `metadata_revision`, `metadata_updated_at`, `system_revision_id`. WHY `metadata_revision`
    is not asserted on `model_dump`: SB-meta makes it always present in API JSON (C4 shows
    `"metadata_revision": 1`) and keeps it out of the export at 1; this append-only test must
    stay green after SB-meta. This is a guard: it is green when §4.9 is right. Write it before
    §4.9 and see it pass on the old code, then keep it green through §4.9.
13. **SCH-12** — `tests/unit/test_migration_e14_postgres.py::test_sch12_migrations_apply_on_postgres`.
    `pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), …)` like
    `test_delete_scores_postgres.py:70`. Use the `postgres_schema_database_url` fixture
    (`tests/conftest.py:42-70`) as a **sync** test (it calls `asyncio.run`). Run the
    `_migrate` subprocess helper with that URL to `0016`, seed one benchmark and one score
    with `asyncpg`, migrate to head. Assert with `asyncpg`: `metadata_revision = 1`; the
    constraint `fk_scores_system_revision` exists in `pg_constraint`; the two partial
    indexes exist in `pg_indexes` (filter `schemaname = <schema>`); one original result
    exists. The fixture URL carries `?schema=<name>`, which Tortoise reads
    (`tortoise/backends/base_postgres/client.py:81`) but asyncpg does not: for every
    `asyncpg.connect`, parse the URL with `urllib.parse`, drop the `schema` query key, and pass
    `server_settings={"search_path": <schema>}`. Pass the full URL (with `?schema=`) to
    `_migrate`. Add the module to the
    `postgres` job in `.github/workflows/scoreboard-tests.yml` (the guard
    `tests/unit/guards/test_postgres_regressions_run_in_ci.py` fails otherwise). RED: the
    migrations do not exist.
14. CHAR: run `tests/unit/test_leaderboard_routes.py::test_every_score_field_reaches_at_least_one_read_dto`
    after step 9. It goes red when the four Score fields exist and §4.9 does not. §4.9 makes it
    green. Do not edit it.

## 7. Edge cases, what not to do, gates

### 7.1 Edge cases

- A populated `scores` table on both engines (SCH-1, SCH-12).
- An old pod writing during the rollout (SCH-9).
- A score whose `metadata` is `NULL`, `{}` or malformed JSON text: the `run_id` pass must
  skip it. Catch only `json.JSONDecodeError` and `TypeError` and skip; log nothing (this is a
  migration).
- Two legacy scores with the same `metadata.run_id` (SCH-4).
- `submitted_at` ties: order by `id` as the second key, so the result is deterministic.
- A private-board score also gets an original result. That is correct: every head has one.

### 7.2 What not to do

- Do not rename or drop any column. Do not change `content_hash`.
- Do not add a `ForeignKeyField` for `Score.system_revision` (OD-S1).
- Do not give any FK that points to `Score` a reverse relation (§4.1).
- Do not edit an existing test function, fixture body or module-level assignment. Append only.
- Do not import `url4` or `screamingface` anywhere in `apps/scoreboard` (C11).
- Do not use `AddConstraint(… condition=…)`: it raises on SQLite.
- Do not use Aerich. Do not use `Tortoise.generate_schemas` in a migration.
- Do not store or log `AIGATEWAY_SECRET_KEY` (not used here; repo rule). No OS keychain.

### 7.3 Gates

From the repo root:

```sh
uv run .claude/scripts/run_gates.py scoreboard --base "$(git merge-base HEAD e14-reproducible-submission-spec)"
```

WHY the merge base: the append-only check compares with the point where `unit/SB-schema`
left the e14 branch. The e14 branch can move while the wave runs (D1).

This runs, with cwd `apps/scoreboard`: `uv run ruff check`, `uv run ruff format --check`,
`uv run pyright`, `uv run pytest --cov=scoreboard --cov-fail-under=80 -q`, and the portal
`node --test …` list, after the append-only check.

## 8. Verification and "done"

```sh
cd apps/scoreboard
uv run pytest tests/unit/test_migration_e14_schema.py tests/unit/scores/test_e14_models.py -v
uv run pytest tests/unit/test_leaderboard_routes.py::test_every_score_field_reaches_at_least_one_read_dto -v
SCOREBOARD_TEST_DATABASE_URL=postgres://scoreboard:scoreboard@localhost:5432/scoreboard_test \
  uv run pytest tests/unit/test_migration_e14_postgres.py -v
rm -f /tmp/e14.sqlite3
SCOREBOARD_DATABASE_URL=sqlite:///tmp/e14.sqlite3 uv run tortoise migrate
SCOREBOARD_DATABASE_URL=sqlite:///tmp/e14.sqlite3 uv run tortoise migrate   # no-op
SCOREBOARD_DATABASE_URL=sqlite:///tmp/e14.sqlite3 uv run tortoise makemigrations --name check  # must write nothing
cd ../.. && uv run .claude/scripts/run_gates.py scoreboard --base "$(git merge-base HEAD e14-reproducible-submission-spec)"
```

Done when:

- SCH-1 to SCH-13 are green. SCH-12 is green against the local PostgreSQL of §8 (there is
  no per-unit CI gate, D1; the `postgres` job entry is for the integrator and for later CI).
- The CHAR guard is green and unchanged.
- The whole scoreboard suite is green, coverage ≥ 80%, append-only check green.
- `makemigrations` writes no new file after the three migrations.
- `git diff "$(git merge-base HEAD e14-reproducible-submission-spec)" -- apps/scoreboard/src/scoreboard/routes`
  is empty (no behavior).
- The ledger Outcome is filled. The work is committed on `unit/SB-schema` (conventional
  commits, no `Refs:` line, no `Co-Authored-By`), ready for the integrator (D1).

## 9. Decisions

No open decision is left in this unit.

- **OD-S1 — decided (default).** `Score.system_revision_id` is a plain UUID column, not a
  Tortoise FK. A `ForeignKeyField` adds the key `system_revision` to
  `Score._meta.fields_map`, and the append-only CHAR guard at
  `tests/unit/test_leaderboard_routes.py:504-530` then fails. PostgreSQL gets a real FK
  constraint (migration 0018 RunPython); SQLite gets none. Do not edit the guard.
- **OD-S2 — decided (default).** `ReportedResult.replayed_from` and `pinned_baseline` use
  RESTRICT (it keeps I-R2). `delete_scores` then fails loudly for a score whose result another
  run replayed. Record this limit in the ledger.
- **OD-S3 — Decided: D5.** `ScoreMetadataEvent.actor` is nullable. In production the
  scoreboard runs `SCOREBOARD_AUTH_MODE=cloudflare_headers`, and every event stores the
  verified `X-User-Email` identity (SB-meta). `NULL` occurs only in the `disabled` dev/local
  fallback, where no verified identity exists. Keep the column comment of §4.6.
- **OD-S4 — decided (default).** A NULL `benchmark_revision` escapes I-S1 (both engines treat
  NULLs as distinct; SQLite has no `NULLS NOT DISTINCT`). Accept it. SB-submit filters with
  `benchmark_revision__isnull=True`, and its IntegrityError retry does not cover this case;
  SB-submit records it as a known limit.
- **OD-S5 — decided (default).** Table names are singular (`system`, `reported_result`, …),
  as erd.md §6 names them.
