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
    # WHY nullable-add plus a backfill, and NOT a tightening to NOT NULL:
    #
    # A single AddField for a NON-nullable column emits
    # `ALTER TABLE "benchmarks" ADD COLUMN "visibility" VARCHAR(16) NOT NULL` with no database
    # default, which every populated database rejects — SQLite fails with "Cannot add a NOT NULL
    # column with default value NULL", PostgreSQL likewise. So the column is added nullable.
    #
    # Tightening it afterwards with AlterField is worse. SQLite has no native way to add a
    # constraint, so Tortoise rebuilds the table and DROPs the old one; with a foreign key
    # pointing at `benchmarks`, that DROP fails with "FOREIGN KEY constraint failed" on any board
    # holding a score or baseline. Reproduced against a populated database in review of PR #719.
    #
    # The constraint bought nothing anyway: the model `default` supplies a value on every write,
    # and a NULL on a pre-migration row reads as public, which is what the backfill asserts.
    # `benchmark_to_schema` coerces, so no reader sees None.
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
    ]
