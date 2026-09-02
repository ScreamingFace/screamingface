from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0010_idempotency_key_scheme"),
    ]

    initial = False

    # FEATURE: OME-1056 — the number of cases a benchmark defines, so a partial run stops
    # ranking against a complete one. Fewer cases makes a perfect score easier, so before this
    # a one-case run did not merely rank, it WON.
    #
    # WHY nullable with NO backfill: NULL is meaningful here and is not a gap to be filled. It
    # means "this board declares no canonical scope", and such a board filters nothing — the
    # same rule `revision` already follows for the retained legacy entries. Inventing a count
    # for a board the Engine does not publish would assert a scope nobody verified.
    #
    # The value is filled by the seed job from the Engine catalogue, which already carries
    # `case_count` and was discarding it. So no data migration is needed: the next seed after
    # this deploy populates every Engine-published board.
    #
    # AIDEV-NOTE: no `scores` change and no backfill of existing submissions. Ranking is
    # computed at READ time from `total_questions`, which is already stored on every row, so
    # partial rows already in the table drop out of the ranking on the next request and stay
    # readable through history. Nothing is deleted.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout — old pods ignore a column they do
    # not know. See "Breaking migrations and multi-replica rollouts" in DEPLOYMENT.md.

    operations = [
        ops.AddField(
            model_name="Benchmark",
            name="case_count",
            field=fields.IntField(null=True),
        ),
    ]
