from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0013_score_models"),
    ]

    initial = False

    # FEATURE: OME-822 / OME-1251 D1 — why a row's `run_cost_usd` is absent, when it is.
    #
    # WHY nullable and deliberately NOT backfilled: NULL is a meaningful third state here, not a
    # gap waiting to be filled. It means the row predates this field — an imported OME-322
    # baseline, or a submission from before OME-822 — which is a DIFFERENT fact from the stored
    # value "unavailable", where a client looked and could not determine the cost.
    #
    # Backfilling existing rows to "unavailable" was considered and rejected: it would assert
    # that every legacy submitter tried and failed, when in truth nobody was ever asked. The
    # Pareto frontier already excludes any row whose amount is null (`scores/pareto.py:91`), so
    # legacy rows behave correctly without the claim.
    operations = [
        ops.AddField(
            model_name="Score",
            name="run_cost_status",
            field=fields.CharField(max_length=16, null=True),
        ),
    ]
