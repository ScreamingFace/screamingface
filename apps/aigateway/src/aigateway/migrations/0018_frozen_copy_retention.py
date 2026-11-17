"""Retention columns and index of ``frozen_copies`` (OME-1947, spec ``erd.md`` section 5).

UPGRADE. Three nullable datetime columns, no default, no data change (each existing row keeps
NULL): ``claimed_at`` (the claim of stack B), ``swept_at`` and ``purged_at`` (the sweep). Then one
``CREATE INDEX`` on ``(status, purged_at)``, the read of the purge step. On Postgres each
``ADD COLUMN`` waits for a lock that makes every reader of the table wait, so the lock wait is
bounded, as in ``0017``.

DOWNGRADE. Drops the index, then the three columns, each with one ``ALTER TABLE ... DROP COLUMN``.
Entries that the sweep deleted do not come back, and each claim is lost. An image before this
migration does not know ``abandoned`` and ``expired``: its replay refuses them as not sealed, and
its seal can seal an empty swept copy (accepted, ``erd.md`` section 5.1).

AUTHORING NOTE. Written from the operations that ``tortoise makemigrations -n frozen_copy_retention
models`` proposes, edited as ``0014``-``0016`` were: the autodetector's ``AlterField`` on
``OAuthConnection.account`` is left out (the pre-existing drift ``0012`` describes). Each
``AddField`` is ``_AddColumn``, whose reverse is a plain DROP COLUMN: on SQLite, Tortoise 1.1.8's
``RemoveField`` (the reverse of ``AddField``) rebuilds the table and loses its indexes (``0017``).
The index is the last operation, so the downgrade drops it before ``purged_at``.
"""

from typing import Any

from tortoise import fields, migrations
from tortoise.indexes import Index
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
    dependencies = [("models", "0017_drop_migration_note")]

    initial = False

    operations = [
        ops.RunPython(code=_bound_lock_wait, reverse_code=ops.RunPython.noop),
        _AddColumn(
            model_name="FrozenCopy",
            name="claimed_at",
            field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
        _AddColumn(
            model_name="FrozenCopy",
            name="swept_at",
            field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
        _AddColumn(
            model_name="FrozenCopy",
            name="purged_at",
            field=fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
        ops.AddIndex(model_name="FrozenCopy", index=Index(fields=["status", "purged_at"])),
    ]
