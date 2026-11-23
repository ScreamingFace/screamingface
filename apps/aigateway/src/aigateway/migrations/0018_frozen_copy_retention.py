"""Retention columns and index of ``frozen_copies`` (OME-1947, spec ``erd.md`` section 5).

UPGRADE. Three nullable datetime columns, no default, no data change (each existing row keeps
NULL): ``claimed_at`` (the claim of stack B), ``swept_at`` and ``purged_at`` (the sweep). Then one
``CREATE INDEX`` on ``(status, purged_at)``, the read of the purge step. On Postgres each
``ADD COLUMN`` waits for a lock that makes every reader of the table wait, so the lock wait is
bounded, as in ``0017``.

INVARIANT (``ck_frozen_copies_sealed_not_swept``, PR #1911 review): no row has ``status = 'sealed'``
with a non-null ``swept_at``. A CHECK constraint on Postgres; on SQLite, where a CHECK cannot be
added to an existing table without building it again, two triggers (insert, update) raise the same
name. WHY: an image before this migration seals each copy that is not ``sealed``. Run beside the
new sweep, it could seal a copy that the sweep made ``abandoned``, and the purge would then empty
a ``sealed`` copy. Now that seal fails with an integrity error (a 500 from the old image) and the
copy stays ``abandoned`` (``erd.md`` section 5.1). Every row that exists when this migration runs
has ``swept_at`` NULL, so the constraint holds at once.

DOWNGRADE. Drops the constraint (or the two triggers), then the index, then the three columns,
each with one ``ALTER TABLE ... DROP COLUMN``. Entries that the sweep deleted do not come back, and
each claim is lost. An image before this migration does not know ``abandoned`` and ``expired``:
its replay refuses them as not sealed. With this migration in place its seal of a swept copy fails
on the constraint; after this downgrade the constraint is gone and that seal can seal an empty
swept copy (accepted, ``erd.md`` section 5.1: the old image alone has no sweep).

AUTHORING NOTE. Written from the operations that ``tortoise makemigrations -n frozen_copy_retention
models`` proposes, edited as ``0014``-``0016`` were: the autodetector's ``AlterField`` on
``OAuthConnection.account`` is left out (the pre-existing drift ``0012`` describes). Each
``AddField`` is ``_AddColumn``, whose reverse is a plain DROP COLUMN: on SQLite, Tortoise 1.1.8's
``RemoveField`` (the reverse of ``AddField``) rebuilds the table and loses its indexes (``0017``).
The index and then the constraint are the last operations, so the downgrade drops them before the
columns they read. The constraint is not in the model state (Tortoise 1.1.8 adds a CHECK on SQLite
by building the table again, ``0017``), so ``makemigrations`` proposes nothing for it.
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


_SEALED_NOT_SWEPT = "ck_frozen_copies_sealed_not_swept"
_SEALED_NOT_SWEPT_CHECK = "status <> 'sealed' OR swept_at IS NULL"
_SQLITE_GUARD_WHEN = "NEW.status = 'sealed' AND NEW.swept_at IS NOT NULL"
_SQLITE_GUARDS = (
    (f"{_SEALED_NOT_SWEPT}_insert", "INSERT"),
    (f"{_SEALED_NOT_SWEPT}_update", "UPDATE OF status, swept_at"),
)


async def _add_sealed_not_swept(apps: Any, schema_editor: BaseSchemaEditor) -> None:
    del apps
    if _dialect_of(schema_editor) == "postgres":
        await schema_editor._run_sql(  # noqa: SLF001
            f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_SEALED_NOT_SWEPT} "
            f"CHECK ({_SEALED_NOT_SWEPT_CHECK})"
        )
        return
    for name, event in _SQLITE_GUARDS:
        trigger = (
            f"CREATE TRIGGER {name} BEFORE {event} ON {_TABLE} "
            f"WHEN {_SQLITE_GUARD_WHEN} "
            f"BEGIN SELECT RAISE(ABORT, '{_SEALED_NOT_SWEPT}'); END"
        )
        if schema_editor.collect_sql:
            await schema_editor._run_sql(trigger)  # noqa: SLF001
        else:
            # WHY not _run_sql: on SQLite it splits the text at each ';', and the body of a
            # trigger has one.
            await schema_editor.client.execute_query(trigger)


async def _drop_sealed_not_swept(apps: Any, schema_editor: BaseSchemaEditor) -> None:
    del apps
    if _dialect_of(schema_editor) == "postgres":
        await schema_editor._run_sql(  # noqa: SLF001
            f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_SEALED_NOT_SWEPT}"
        )
        return
    for name, _event in _SQLITE_GUARDS:
        await schema_editor._run_sql(f"DROP TRIGGER IF EXISTS {name}")  # noqa: SLF001


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
        ops.RunPython(code=_add_sealed_not_swept, reverse_code=_drop_sealed_not_swept),
    ]
