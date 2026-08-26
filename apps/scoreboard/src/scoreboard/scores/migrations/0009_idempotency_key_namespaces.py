from tortoise import migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [
        ("models", "0008_benchmark_visibility"),
    ]

    initial = False

    # INVARIANT: `sfp-` AND `sfu-` are server-owned after this migration. Legacy public mappings
    # stored every
    # client value verbatim, so a malicious value could already occupy that private namespace.
    # Those mappings expire after 24 hours and contain no score data; removing only the reserved
    # prefix makes the separation unconditional while preserving every ordinary public retry.
    # The FK points FROM this table to scores, so deleting mappings never deletes submissions.
    operations = [
        ops.RunSQL(
            """DELETE FROM "idempotency_keys" WHERE "key" LIKE 'sfp-%' OR "key" LIKE 'sfu-%'""",
            reverse_sql=ops.RunSQL.noop,
        ),
    ]
