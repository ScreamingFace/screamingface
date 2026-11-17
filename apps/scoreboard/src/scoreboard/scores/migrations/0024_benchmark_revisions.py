from tortoise import fields, migrations
from tortoise.fields.base import OnDelete
from tortoise.migrations import operations as ops

# FEATURE: OME-1708 — backfill every revision a board has already seen. Neither a past
# revision's first-seen date nor its Case count was ever stored, so both are inferred from the
# results under it and marked inferred:
#   - first seen: the earliest submission under the revision;
#   - Case count: the LARGEST question count among its results. A run never covers more Cases
#     than its revision has; a partial `limit=n` run reports fewer; failed Cases stay in a run
#     (scored 0), so a full run with failures still reports the full count.
# The registered revision then takes the Engine's own count (not inferred), and a registered
# revision with no results yet is recorded too, so the selector can show it as Latest.
# AIDEV-NOTE: plain portable SQL (SQLite and Postgres); scores with no revision are skipped.
_BACKFILL_FROM_SCORES = """
INSERT INTO "benchmark_revisions"
    ("benchmark_id", "revision", "first_seen_at", "first_seen_inferred",
     "case_count", "case_count_inferred")
SELECT "benchmark_id", "benchmark_revision", MIN("submitted_at"), TRUE,
       MAX("total_questions"), TRUE
FROM "scores"
WHERE "benchmark_revision" IS NOT NULL
GROUP BY "benchmark_id", "benchmark_revision"
"""

_REGISTERED_COUNT_WINS = """
UPDATE "benchmark_revisions"
SET "case_count" = (
        SELECT "benchmarks"."case_count" FROM "benchmarks"
        WHERE "benchmarks"."id" = "benchmark_revisions"."benchmark_id"
    ),
    "case_count_inferred" = FALSE
WHERE EXISTS (
    SELECT 1 FROM "benchmarks"
    WHERE "benchmarks"."id" = "benchmark_revisions"."benchmark_id"
      AND "benchmarks"."revision" = "benchmark_revisions"."revision"
      AND "benchmarks"."case_count" IS NOT NULL
)
"""

_REGISTERED_WITHOUT_RESULTS = """
INSERT INTO "benchmark_revisions"
    ("benchmark_id", "revision", "first_seen_at", "first_seen_inferred",
     "case_count", "case_count_inferred")
SELECT "id", "revision", "created_at", TRUE, "case_count", FALSE
FROM "benchmarks"
WHERE "revision" IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM "benchmark_revisions"
      WHERE "benchmark_revisions"."benchmark_id" = "benchmarks"."id"
        AND "benchmark_revisions"."revision" = "benchmarks"."revision"
  )
"""


class Migration(migrations.Migration):
    dependencies = [("models", "0023_baseline_history")]

    initial = False

    operations = [
        ops.CreateModel(
            name="BenchmarkRevision",
            fields=[
                (
                    "id",
                    fields.IntField(generated=True, primary_key=True, unique=True, db_index=True),
                ),
                ("revision", fields.CharField(max_length=64)),
                ("first_seen_at", fields.DatetimeField(auto_now=False, auto_now_add=False)),
                ("first_seen_inferred", fields.BooleanField(default=False)),
                ("case_count", fields.IntField(null=True)),
                ("case_count_inferred", fields.BooleanField(default=False)),
                (
                    "benchmark",
                    fields.ForeignKeyField(
                        "models.Benchmark",
                        source_field="benchmark_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="revisions",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
            ],
            options={
                "table": "benchmark_revisions",
                "app": "models",
                "unique_together": (("benchmark", "revision"),),
                "pk_attr": "id",
            },
            bases=["BaseBenchmarkRevision"],
        ),
        ops.RunSQL(_BACKFILL_FROM_SCORES, reverse_sql=ops.RunSQL.noop),
        ops.RunSQL(_REGISTERED_COUNT_WINS, reverse_sql=ops.RunSQL.noop),
        ops.RunSQL(_REGISTERED_WITHOUT_RESULTS, reverse_sql=ops.RunSQL.noop),
    ]
