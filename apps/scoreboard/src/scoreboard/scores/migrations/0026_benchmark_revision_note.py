from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0025_score_regraded_from"),
    ]

    initial = False

    # FEATURE: OME-2001 — each revision's note: one line saying what changed and whether scores
    # still compare, shown under the leaderboard's revision selector.
    #
    # WHY nullable and deliberately NOT backfilled: no revision recorded before this column has a
    # written reason, and NULL means "no note", which the page shows as nothing. A backfill would
    # put words nobody wrote in front of readers.
    #
    # WHY 500 characters: a safety bound on stored text. The author's target is about 120, and
    # that is guidance, so the column must hold a note that runs longer.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout: an in-place ADD COLUMN on SQLite and
    # PostgreSQL, old pods ignore the new column, and every existing value is NULL.
    operations = [
        ops.AddField(
            model_name="BenchmarkRevision",
            name="note",
            field=fields.CharField(null=True, max_length=500),
        ),
    ]
