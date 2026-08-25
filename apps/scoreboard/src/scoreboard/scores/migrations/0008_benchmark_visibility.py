from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0007_benchmark_focus"),
    ]

    initial = False

    # FEATURE: OME-894 — a benchmark is public or private. A private board keeps its submissions
    # from every other participant, enforced in the API on every read path, so the HealthBench
    # worst-30 entry challenge can run without publishing who scored what.
    #
    # WHY three operations and not one AddField: Tortoise's `default=` is an ORM-side creation
    # default only. A single AddField for a non-nullable column emits
    # `ALTER TABLE "benchmarks" ADD COLUMN "visibility" VARCHAR(16) NOT NULL` with NO database
    # default, which every populated database rejects — SQLite fails outright with "Cannot add a
    # NOT NULL column with default value NULL", and PostgreSQL likewise. Verified by applying it
    # to a database holding one benchmark row (found in review of PR #719). Add nullable,
    # backfill, then tighten.
    #
    # WHY "public" is the backfill value: every benchmark that predates this column was already
    # world-readable, so `public` states what was true rather than inventing a new posture. No
    # existing board changes visibility as a result of this migration.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout — old pods ignore a column they do not
    # know, and the column is populated before it is made NOT NULL. See "Breaking migrations and
    # multi-replica rollouts" in apps/scoreboard/DEPLOYMENT.md.
    #
    # Flipping a specific benchmark to private is CONFIG, not a migration: set `visibility` in the
    # chart's seedBenchmarks entry and re-run the seed job.

    operations = [
        ops.AddField(
            model_name="Benchmark",
            name="visibility",
            field=fields.CharField(max_length=16, default="public", null=True),
        ),
        ops.RunSQL(
            """UPDATE "benchmarks" SET "visibility" = 'public' WHERE "visibility" IS NULL""",
            reverse_sql=ops.RunSQL.noop,
        ),
        ops.AlterField(
            model_name="Benchmark",
            name="visibility",
            field=fields.CharField(max_length=16, default="public"),
        ),
    ]
