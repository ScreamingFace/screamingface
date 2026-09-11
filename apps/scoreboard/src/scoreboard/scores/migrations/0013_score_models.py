from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0012_score_authors"),
    ]

    initial = False

    # FEATURE: OME-1181 — the candidate's declared model routes.
    #
    # WHY nullable and deliberately NOT backfilled: the routes cannot be reconstructed from
    # `ran_with_providers`, because the Client's truncation to a provider prefix is lossy —
    # ["openrouter"] could have been any models at all. NULL therefore means "not declared",
    # and the openness statistic excludes such a row from its numerator AND denominator rather
    # than counting it closed (OME-1179 contract).
    #
    # Rows fill in as submitters re-run once OME-1180 ships: a same-owner replay may enrich a
    # null value (OME-1179 Q3, owner 2026-09-11). Backfilling the existing rows from
    # `url4_expression` was considered and left out of scope.
    operations = [
        ops.AddField(
            model_name="Score",
            name="models",
            field=fields.JSONField(null=True),
        ),
    ]
