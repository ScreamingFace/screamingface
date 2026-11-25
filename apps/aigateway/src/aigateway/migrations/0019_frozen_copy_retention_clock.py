"""The start of the 30-day clock of the frozen copies that are sealed when the expiry rule is
released (OME-1947, spec ``erd.md`` section 5).

UPGRADE. One nullable datetime column ``retention_from``, no default. Then one data step: one
``UPDATE`` sets ``retention_from`` of each ``sealed`` copy to one timezone-aware UTC time that the
step computes in Python. Each other row keeps NULL. On Postgres the lock wait of the ``ADD
COLUMN`` is bounded, as in ``0018``. The ``ADD COLUMN`` and the data step run in one transaction,
so on Postgres the table lock stays until the ``UPDATE`` ends. The 3-second lock wait also applies
to the row locks of the ``UPDATE``: when a claim or a seal holds a sealed row for longer, the
migration fails. Run the migration Job again.

DOWNGRADE. One ``ALTER TABLE frozen_copies DROP COLUMN retention_from``. Roll back the code of the
expiry rule with it. When ``0019`` is applied again, it stamps the sealed copies with the new
time, so each clock starts again; no copy expires earlier. The downgrade does not bound its lock
wait.

AUTHORING NOTE. Written from the operations that ``tortoise makemigrations -n
frozen_copy_retention_clock models`` proposes, edited as ``0018`` was: the autodetector's
``AlterField`` on ``OAuthConnection.account`` is left out, and the ``AddField`` is ``_AddColumn``
(reverse = plain DROP COLUMN; Tortoise 1.1.8 ``RemoveField`` rebuilds a SQLite table and loses its
indexes). The data step passes the time as a parameter, never ``CURRENT_TIMESTAMP`` or ``now()``:
on SQLite such text has no zone and compares wrongly with ``sealed_at``.
"""

from datetime import UTC, datetime
from typing import Any

from tortoise import fields, migrations
from tortoise.migrations import operations as ops
from tortoise.migrations.schema_editor.base import BaseSchemaEditor
from tortoise.migrations.schema_generator.state import State

_TABLE = "frozen_copies"
_LOCK_TIMEOUT_MS = 3_000
_SET_LOCK_TIMEOUT_SQL = f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT_MS}ms'"


def _dialect_of(schema_editor: BaseSchemaEditor | None) -> str:
    capabilities = getattr(getattr(schema_editor, "client", None), "capabilities", None)
    return (getattr(capabilities, "dialect", "") or "").lower()


async def _bound_lock_wait(apps: Any, schema_editor: BaseSchemaEditor) -> None:
    del apps
    if _dialect_of(schema_editor) == "postgres":
        await schema_editor._run_sql(_SET_LOCK_TIMEOUT_SQL)  # noqa: SLF001


async def _stamp_sealed_copies(apps: Any, schema_editor: BaseSchemaEditor) -> None:
    del schema_editor
    model = apps.get_model("models", "FrozenCopy")
    await model.filter(status="sealed").update(retention_from=datetime.now(UTC))


class _AddColumn(ops.AddField):
    """``AddField`` whose downgrade is one ``ALTER TABLE ... DROP COLUMN`` (see AUTHORING NOTE)."""

    async def database_backward(
        self,
        app_label: str,
        old_state: State,
        new_state: State,
        state_editor: BaseSchemaEditor | None = None,
    ) -> None:
        if state_editor is not None:
            await state_editor._run_sql(  # noqa: SLF001
                f"ALTER TABLE {_TABLE} DROP COLUMN {self.name}"
            )


class Migration(migrations.Migration):
    dependencies = [("models", "0018_frozen_copy_retention")]

    initial = False

    operations = [
        ops.RunPython(code=_bound_lock_wait, reverse_code=ops.RunPython.noop),
        _AddColumn(
            model_name="FrozenCopy",
            name="retention_from",
            field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
        ops.RunPython(code=_stamp_sealed_copies, reverse_code=ops.RunPython.noop),
    ]
