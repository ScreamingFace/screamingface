import functools
from json import dumps, loads
from uuid import uuid4

from tortoise import fields, migrations
from tortoise.fields.base import OnDelete
from tortoise.indexes import Index
from tortoise.migrations import operations as ops

# WHY inline SQL and not an import of `scores/models/partial_indexes.py`: a migration is frozen
# history and must not change when app code changes. INVARIANT: the two copies stay byte-equal;
# `test_sch7_partial_index_ddl_matches_the_migration` holds them equal.
_ONE_ORIGINAL_PER_SCORE_SQL = (
    'CREATE UNIQUE INDEX IF NOT EXISTS "uidx_reported_result_one_original" '
    'ON "reported_result" ("head_id") WHERE "is_original"'
)
_ONE_PUBLIC_HEAD_PER_SYSTEM_REVISION_SQL = (
    'CREATE UNIQUE INDEX IF NOT EXISTS "uidx_scores_public_head" '
    'ON "scores" ("benchmark_id", "benchmark_revision", "system_revision_id") '
    'WHERE "system_revision_id" IS NOT NULL'
)
_ADD_SYSTEM_REVISION_FK_SQL = (
    'ALTER TABLE "scores" ADD CONSTRAINT "fk_scores_system_revision" '
    'FOREIGN KEY ("system_revision_id") REFERENCES "system_revision" ("id") ON DELETE RESTRICT'
)
_DROP_SYSTEM_REVISION_FK_SQL = (
    'ALTER TABLE "scores" DROP CONSTRAINT IF EXISTS "fk_scores_system_revision"'
)


async def _add_postgres_system_revision_fk(apps, schema_editor) -> None:
    # WHY PostgreSQL only: SQLite cannot add a constraint to an existing table, and
    # `Score.system_revision_id` is a plain UUID column in the model (OD-S1).
    if schema_editor.DIALECT == "postgres":
        await schema_editor.client.execute_script(_ADD_SYSTEM_REVISION_FK_SQL)


async def _drop_postgres_system_revision_fk(apps, schema_editor) -> None:
    if schema_editor.DIALECT == "postgres":
        await schema_editor.client.execute_script(_DROP_SYSTEM_REVISION_FK_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0018_e14_score_metadata_columns"),
    ]

    initial = False

    # FEATURE: OME-1307 (E14) — system registry, reported results, metadata audit events and
    # cache-version publication state, plus the two partial unique indexes Tortoise cannot declare.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout — only new tables and indexes. The
    # `reported_result` FK columns have the Tortoise native names `head_id`,
    # `replayed_from_result_id` and `pinned_baseline_result_id` (D8); no `RunSQL` renames a column,
    # and no FK sets a custom `source_field`, so the migration state equals the models.
    operations = [
        ops.CreateModel(
            name="System",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                ("name", fields.CharField(unique=True, max_length=64)),
                ("owner", fields.CharField(max_length=255)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
            ],
            options={"table": "system", "app": "models", "pk_attr": "id"},
            bases=["BaseSystem"],
        ),
        ops.CreateModel(
            name="SystemRevision",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                ("revision", fields.IntField()),
                ("fingerprint", fields.CharField(unique=True, max_length=64)),
                ("candidate_url4", fields.TextField(unique=False)),
                ("declared_by", fields.CharField(max_length=255)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                (
                    "system",
                    fields.ForeignKeyField(
                        "models.System",
                        source_field="system_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="revisions",
                        on_delete=OnDelete.RESTRICT,
                    ),
                ),
            ],
            options={
                "table": "system_revision",
                "app": "models",
                "unique_together": (("system", "revision"),),
                "pk_attr": "id",
            },
            bases=["BaseSystemRevision"],
        ),
        ops.CreateModel(
            name="ReportedResult",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                ("is_original", fields.BooleanField()),
                ("reporter", fields.CharField(null=True, max_length=255)),
                ("run_id", fields.CharField(null=True, unique=True, max_length=255)),
                ("trace_id", fields.CharField(null=True, max_length=32)),
                ("score", fields.FloatField()),
                ("total_questions", fields.IntField()),
                ("correct_questions", fields.IntField(null=True)),
                ("run_cost_usd", fields.DecimalField(null=True, max_digits=12, decimal_places=6)),
                ("run_cost_status", fields.CharField(null=True, max_length=16)),
                (
                    "cache_saved_cost_usd",
                    fields.DecimalField(null=True, max_digits=12, decimal_places=6),
                ),
                (
                    "models",
                    fields.JSONField(
                        null=True,
                        encoder=functools.partial(dumps, separators=(",", ":")),
                        decoder=loads,
                    ),
                ),
                (
                    "ran_with_providers",
                    fields.JSONField(
                        null=True,
                        encoder=functools.partial(dumps, separators=(",", ":")),
                        decoder=loads,
                    ),
                ),
                ("answer_seed", fields.IntField(null=True)),
                ("client_name", fields.CharField(null=True, max_length=128)),
                ("client_version", fields.CharField(null=True, max_length=64)),
                ("client_platform", fields.CharField(null=True, max_length=32)),
                ("submitted_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ("cache_version_id", fields.UUIDField(null=True, unique=True)),
                ("cache_version_sha256", fields.CharField(null=True, max_length=64)),
                ("cache_entry_count", fields.IntField(null=True)),
                ("cache_call_count", fields.IntField(null=True)),
                ("cache_coverage_status", fields.CharField(null=True, max_length=16)),
                ("replay_hits", fields.IntField(null=True)),
                ("replay_misses", fields.IntField(null=True)),
                ("replay_repeated_key_collapses", fields.IntField(null=True)),
                (
                    "head",
                    fields.ForeignKeyField(
                        "models.Score",
                        source_field="head_id",
                        db_constraint=True,
                        to_field="id",
                        related_name=False,
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "replayed_from_result",
                    fields.ForeignKeyField(
                        "models.ReportedResult",
                        source_field="replayed_from_result_id",
                        null=True,
                        db_constraint=True,
                        to_field="id",
                        related_name=False,
                        on_delete=OnDelete.NO_ACTION,
                    ),
                ),
                (
                    "pinned_baseline_result",
                    fields.ForeignKeyField(
                        "models.ReportedResult",
                        source_field="pinned_baseline_result_id",
                        null=True,
                        db_constraint=True,
                        to_field="id",
                        related_name=False,
                        on_delete=OnDelete.NO_ACTION,
                    ),
                ),
            ],
            options={
                "table": "reported_result",
                "app": "models",
                "indexes": [Index(fields=["head_id", "submitted_at"])],
                "pk_attr": "id",
            },
            bases=["BaseReportedResult"],
        ),
        ops.CreateModel(
            name="ScoreMetadataEvent",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                ("actor", fields.CharField(null=True, max_length=255)),
                ("at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ("from_revision", fields.IntField()),
                ("to_revision", fields.IntField()),
                (
                    "before",
                    fields.JSONField(
                        encoder=functools.partial(dumps, separators=(",", ":")), decoder=loads
                    ),
                ),
                (
                    "after",
                    fields.JSONField(
                        encoder=functools.partial(dumps, separators=(",", ":")), decoder=loads
                    ),
                ),
                (
                    "score",
                    fields.ForeignKeyField(
                        "models.Score",
                        source_field="score_id",
                        db_constraint=True,
                        to_field="id",
                        related_name=False,
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
            ],
            options={
                "table": "score_metadata_event",
                "app": "models",
                "unique_together": (("score", "to_revision"),),
                "pk_attr": "id",
            },
            bases=["BaseScoreMetadataEvent"],
        ),
        ops.CreateModel(
            name="CacheVersionPublication",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                ("state", fields.CharField(default="private", max_length=16)),
                ("requested_by", fields.CharField(null=True, max_length=255)),
                (
                    "requested_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                ("attempts", fields.IntField(default=0)),
                (
                    "next_attempt_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                (
                    "lease_until",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                ("last_error", fields.CharField(null=True, max_length=512)),
                ("release_tag", fields.CharField(null=True, max_length=64)),
                ("release_url", fields.CharField(null=True, max_length=512)),
                (
                    "published_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                (
                    "withdrawn_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                ("withdrawn_by", fields.CharField(null=True, max_length=255)),
                ("withdrawn_reason", fields.TextField(null=True, unique=False)),
                (
                    "result",
                    fields.OneToOneField(
                        "models.ReportedResult",
                        source_field="result_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="publication",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
            ],
            options={
                "table": "cache_version_publication",
                "app": "models",
                "indexes": [Index(fields=["state", "next_attempt_at"])],
                "pk_attr": "id",
            },
            bases=["BaseCacheVersionPublication"],
        ),
        ops.RunSQL(
            _ONE_ORIGINAL_PER_SCORE_SQL,
            reverse_sql='DROP INDEX IF EXISTS "uidx_reported_result_one_original"',
        ),
        ops.RunSQL(
            _ONE_PUBLIC_HEAD_PER_SYSTEM_REVISION_SQL,
            reverse_sql='DROP INDEX IF EXISTS "uidx_scores_public_head"',
        ),
        ops.RunPython(
            _add_postgres_system_revision_fk,
            reverse_code=_drop_postgres_system_revision_fk,
        ),
    ]
