from uuid import uuid4

from tortoise import fields, migrations
from tortoise.fields.base import OnDelete
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0019_score_metadata"),
    ]

    initial = False

    # FEATURE: OME-1307 / E14 B4 — the cache version of a run on a score, and the table of recorded
    # replays.
    #
    # WHY nullable and NOT backfilled: no row has ever carried a cache version, and NULL means
    # "unknown" (`reproducible`) or "not sent" (the others). Legacy rows keep serving exactly what
    # they served, and the reproduce flow reads a NULL status as not reproducible.
    #
    # WHY a new table rather than a counter on `scores`: each record names its verified identity and
    # its own `run_id`, and the unique `(score_id, run_id)` is what stops a retried record counting
    # twice. The count is derived on read, so there is no lost update.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout — old pods ignore columns and tables
    # they do not know. See "Breaking migrations and multi-replica rollouts" in DEPLOYMENT.md.
    operations = [
        ops.AddField(
            model_name="Score",
            name="cache_revision",
            field=fields.CharField(null=True, max_length=32),
        ),
        ops.AddField(
            model_name="Score",
            name="reproducible",
            field=fields.CharField(null=True, max_length=16),
        ),
        ops.AddField(
            model_name="Score",
            name="answer_seed",
            field=fields.IntField(null=True),
        ),
        ops.CreateModel(
            name="ScoreReproduction",
            fields=[
                (
                    "id",
                    fields.UUIDField(primary_key=True, default=uuid4, unique=True, db_index=True),
                ),
                ("reproduced_by", fields.CharField(max_length=255)),
                ("reproduced_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ("run_id", fields.CharField(max_length=128)),
                ("cache_revision", fields.CharField(null=True, max_length=32)),
                ("client_version", fields.CharField(null=True, max_length=64)),
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
                "table": "score_reproductions",
                "app": "models",
                "unique_together": (("score", "run_id"),),
                "pk_attr": "id",
            },
            bases=["BaseScoreReproduction"],
        ),
    ]
