from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("runs", "0001_initial")]

    operations = [
        ops.AddField(
            model_name="Candidate",
            name="stop_owed",
            field=fields.BooleanField(default=False, db_default=False),
        ),
    ]
