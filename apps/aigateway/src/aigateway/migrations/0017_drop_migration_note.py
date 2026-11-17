"""Drop ``provider_credential_slots.migration_note`` (OME-1138 close-out, L4c-2).

UPGRADE. Refuses first, with nothing changed, while any marker row is ``quarantined`` or still
carries a note: from L4a on neither is a state the gateway knows, and the operator settles them as
``DEPLOYMENT.md`` says ("Before an image that includes L4a"). Then one
``ALTER TABLE … DROP COLUMN`` on both dialects. No other column, index or constraint moves, so the
``(account_id, provider)`` uniqueness (D1) and both foreign keys stay as ``0012`` created them. On
Postgres the drop holds a lock that makes every reader of the table wait, so the lock wait is
bounded, as in ``0013``. The column left the migration state in ``0016`` (gateway 1.0.1). An
environment still on an image before ``0016`` runs both in one pre-upgrade Job; until its new Pod
is ready, an old Pod's Connection write can fail: the queries that lock or insert a marker row
name every field its model declares.
The owner accepts that window (2026-11-16; spec §4.3).

DOWNGRADE. Re-adds ``migration_note`` as a nullable ``VARCHAR(255)``, empty. Every image before
L4c-1 (``0016``) declares the field and names the column in the marker queries that load or create
a row, so rolling back below L4c-1 runs this downgrade first.

AUTHORING NOTE. Hand-written: after ``0016`` the projected state already matches the model, and
``tortoise makemigrations`` proposes only the autodetector's ``AlterField`` on
``OAuthConnection.account`` (the pre-existing drift ``0012`` describes), which is left out. The
drop is a plain ``RunSQL``, not ``RemoveField``: on SQLite, Tortoise 1.1.8's ``RemoveField``
rebuilds the table and loses ``unique_together`` and the foreign-key indexes (spec §4.3), while
SQLite 3.35 and later drop a plain column in place and keep every index and constraint.
"""

from typing import Any

from tortoise import migrations
from tortoise.migrations import operations as ops
from tortoise.migrations.schema_editor.base import BaseSchemaEditor

_TABLE = "provider_credential_slots"
_COLUMN = "migration_note"
_LOCK_TIMEOUT_MS = 3_000
_SET_LOCK_TIMEOUT_SQL = f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT_MS}ms'"
_COUNT_UNSETTLED_SQL = (
    "SELECT count(CASE WHEN migration_state = 'quarantined' THEN 1 END) AS quarantined,"
    f" count({_COLUMN}) AS noted FROM {_TABLE}"
)


def _dialect_of(schema_editor: BaseSchemaEditor | None) -> str:
    capabilities = getattr(getattr(schema_editor, "client", None), "capabilities", None)
    return (getattr(capabilities, "dialect", "") or "").lower()


async def _bound_lock_wait(apps: Any, schema_editor: BaseSchemaEditor) -> None:
    del apps
    if _dialect_of(schema_editor) == "postgres":
        await schema_editor._run_sql(_SET_LOCK_TIMEOUT_SQL)  # noqa: SLF001


async def _refuse_unsettled_markers(apps: Any, schema_editor: BaseSchemaEditor) -> None:
    # INVARIANT: the drop never erases a note or a retired state the operator has not settled.
    del apps
    [counts] = await schema_editor.client.execute_query_dict(_COUNT_UNSETTLED_SQL)
    quarantined, noted = int(counts["quarantined"]), int(counts["noted"])
    if quarantined or noted:
        raise RuntimeError(
            f"0017 refuses to drop {_TABLE}.{_COLUMN}: {quarantined} quarantined and {noted} noted"
            " marker rows remain. Settle them first: DEPLOYMENT.md, 'Before an image that"
            " includes L4a'."
        )


class Migration(migrations.Migration):
    dependencies = [("models", "0016_forget_migration_note")]

    initial = False

    operations = [
        ops.RunPython(code=_bound_lock_wait, reverse_code=ops.RunPython.noop),
        ops.RunPython(code=_refuse_unsettled_markers, reverse_code=ops.RunPython.noop),
        ops.RunSQL(
            sql=f"ALTER TABLE {_TABLE} DROP COLUMN {_COLUMN}",
            reverse_sql=f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} VARCHAR(255)",
        ),
    ]
