from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0014_score_run_cost_status"),
    ]

    initial = False

    # FEATURE: OME-1325 / OME-1251 D5 — what a run's cache hits would have cost.
    #
    # WHY nullable and deliberately NOT backfilled: no row has ever carried this figure, and
    # nothing can recover it after the fact — the gateway only began recording what a cache hit
    # avoided in PR #930. NULL here means "not reported", which is a DIFFERENT fact from the
    # stored value 0, where a client looked and the run genuinely saved nothing.
    #
    # Backfilling to 0 was considered and rejected: it would assert that every legacy run had no
    # cache benefit, which is false for exactly the rows OME-1143 is about. The Pareto frontier
    # does not read this column at all yet (that is gated on OME-1287), so legacy rows behave
    # correctly without any claim being made about them.
    operations = [
        ops.AddField(
            model_name="Score",
            name="cache_saved_cost_usd",
            field=fields.DecimalField(max_digits=12, decimal_places=6, null=True),
        ),
    ]
