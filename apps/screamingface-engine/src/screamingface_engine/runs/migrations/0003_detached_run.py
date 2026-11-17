from tortoise import fields, migrations
from tortoise.indexes import Index
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("runs", "0002_candidate_stop_owed")]

    operations = [
        ops.AddField(
            model_name="Run",
            name="detached",
            field=fields.BooleanField(default=False, db_default=False),
        ),
        ops.AddField(
            model_name="Run",
            name="deadline_at",
            field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
        ops.AddField(
            model_name="Run",
            name="stopped_by",
            field=fields.CharField(null=True, max_length=16),
        ),
        ops.AddField(
            model_name="Run",
            name="sealed_owner_email",
            field=fields.TextField(null=True),
        ),
        ops.AddField(
            model_name="Run",
            name="driver_lease_until",
            field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
        ops.AddField(
            model_name="Run",
            name="context_sha256",
            field=fields.CharField(null=True, max_length=64),
        ),
        ops.AddField(
            model_name="Run",
            name="context_bytes",
            field=fields.IntField(null=True),
        ),
        ops.AddField(model_name="Candidate", name="start", field=fields.JSONField(null=True)),
        # The driver's tick reads the stops still owed every 15 s (E5 P2 spec R9).
        ops.AddIndex(model_name="Candidate", index=Index(fields=["stop_owed"])),
        ops.AddField(model_name="Candidate", name="record", field=fields.JSONField(null=True)),
        ops.AddField(
            model_name="Candidate",
            name="trace_id",
            field=fields.CharField(null=True, max_length=32),
        ),
        # E5 P2 spec R12: a Run's `canceled` state reads `stopped_by`, so every Run P1 canceled
        # keeps reading `canceled`. WHY `WHERE canceled`: true on Postgres's boolean and on
        # SQLite's integer alike.
        ops.RunSQL(
            "UPDATE runs SET stopped_by = 'canceled' WHERE canceled AND stopped_by IS NULL",
            reverse_sql="SELECT 1",
        ),
    ]
