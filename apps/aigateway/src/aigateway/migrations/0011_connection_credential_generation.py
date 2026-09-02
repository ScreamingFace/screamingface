from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0010_simplify_request_cache")]

    operations = [
        # OME-1026 U2: the durable per-connection credential-generation fence.
        # db_default is required alongside default: tortoise emits a SQL DEFAULT
        # clause only for db_default, and the ADD COLUMN is NOT NULL — without it
        # the migration fails on any database with existing rows (SF-244 audit F01).
        # Existing rows backfill at 0 (their pre-fence generation); every
        # credential-publication path bumps past it atomically.
        ops.AddField(
            model_name="OAuthConnection",
            name="credential_generation",
            field=fields.IntField(default=0, db_default="0"),
        ),
    ]
