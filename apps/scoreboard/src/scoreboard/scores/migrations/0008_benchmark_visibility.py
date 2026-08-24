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
    # WHY a default of "public" and NOT nullable: an unknown visibility must not resolve to
    # private by accident (the challenge becomes unreadable by anyone) or to public by accident
    # (the challenge leaks). The default supplies the current behaviour for every existing row,
    # so no backfill is required and no existing board changes.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout — a new column with a default leaves
    # every query the old pods are running valid, and old pods simply ignore the column. Same
    # shape as 0007, unlike 0005/0006. See "Breaking migrations and multi-replica rollouts" in
    # apps/scoreboard/DEPLOYMENT.md.
    #
    # Flipping a specific benchmark to private is CONFIG, not a migration: set `visibility` in
    # the chart's seedBenchmarks entry and re-run the seed job.

    operations = [
        ops.AddField(
            model_name="Benchmark",
            name="visibility",
            field=fields.CharField(max_length=16, default="public"),
        ),
    ]
