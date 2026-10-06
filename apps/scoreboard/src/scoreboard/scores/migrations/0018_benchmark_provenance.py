from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0017_score_cache_saved_cost_archive"),
    ]

    initial = False

    # FEATURE: OME-1455 — where each Benchmark comes from (paper, authors, citation,
    # inspect porters, links, licence, human baseline, frontier score, notebook) and the derived
    # saturation verdict, copied from the Engine catalogue at seed time.
    #
    # WHY two nullable columns with NO backfill: both are Engine-owned, exactly like
    # `case_count` (0011). NULL means "the Engine published none", and the API serves null so
    # a page omits the strip. The values are filled by the seed job from the catalogue, so the
    # next seed after this deploy populates every Engine-published board; nothing is invented.
    #
    # WHY one JSON column for the block (spec §4.1): this board is a copy, not an authority;
    # nothing queries a paper link; a field the Engine adds later needs no migration here. The
    # verdict gets its own column because it is the one value a catalogue page will sort on.
    #
    # AIDEV-NOTE: SAFE for a rolling multi-replica rollout — old pods ignore columns they do
    # not know. See "Breaking migrations and multi-replica rollouts" in DEPLOYMENT.md.

    operations = [
        ops.AddField(
            model_name="Benchmark",
            name="provenance",
            field=fields.JSONField(null=True),
        ),
        ops.AddField(
            model_name="Benchmark",
            name="saturation",
            field=fields.CharField(max_length=16, null=True),
        ),
    ]
