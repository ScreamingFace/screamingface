from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0018_benchmark_provenance"),
    ]

    initial = False

    # FEATURE: OME-1307 / E14 A1 — a paper link on a score, the time its credit last changed, and
    # the edit log of both `authors` and `paper_url`.
    #
    # WHY nullable and NOT backfilled: no row has ever carried a paper link, and NULL means "no
    # paper" / "never edited". Legacy rows keep serving exactly what they served.
    #
    # WHY a new table rather than a JSON column on `scores`: the log is read by one owner-only
    # route and grows with each edit, and the FK cascade removes it when a score is deleted.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout — old pods ignore columns and tables
    # they do not know. See "Breaking migrations and multi-replica rollouts" in DEPLOYMENT.md.
    operations = [
        ops.AddField(
            model_name="Score",
            name="paper_url",
            field=fields.TextField(null=True, unique=False),
        ),
        ops.AddField(
            model_name="Score",
            name="metadata_updated_at",
            field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
    ]
