from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0025_score_regraded_from"),
    ]

    initial = False

    # FEATURE: how many of a run's Cases got a grade, stored beside `total_questions` so the
    # leaderboard can show a run that failed on some of its Cases.
    #
    # WHY nullable and NOT backfilled: no row has ever carried this count, and NULL ("not
    # reported") is a different fact from 0 or from the total. Legacy rows keep serving and
    # exporting exactly as before (every read schema excludes a null count).
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout: an in-place ADD COLUMN that old pods
    # neither read nor write.
    operations = [
        ops.AddField(
            model_name="Score",
            name="graded_questions",
            field=fields.IntField(null=True),
        ),
    ]
