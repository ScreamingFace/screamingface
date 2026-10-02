"""Add the revision-fenced operational outcome register to credential blobs (OME-1250)."""

from typing import Any

from tortoise import fields, migrations
from tortoise.indexes import Index
from tortoise.migrations import operations as ops
from tortoise.migrations.schema_editor.base import BaseSchemaEditor

_MODEL_NAME = "CredentialBlob"
_TABLE = "credential_blobs"
_LOCK_TIMEOUT_MS = 3_000
_SET_LOCK_TIMEOUT_SQL = f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT_MS}ms'"
_REVISION_GUARD_FN = "credential_blobs_reset_operational_outcome"
_REVISION_GUARD = "credential_blobs_revision_follows_value"

# A pre-0013 PostgreSQL binary cannot name the new columns when it replaces a credential. The
# trigger supplies exactly the reset that binary is missing. A current writer increments
# credential_revision itself, so the WHEN predicate skips it and prevents a double increment.
_CREATE_REVISION_GUARD_SQL = f"""
CREATE OR REPLACE FUNCTION {_REVISION_GUARD_FN}() RETURNS trigger AS $$
BEGIN
    NEW.credential_revision := OLD.credential_revision + 1;
    NEW.next_dispatch_sequence := 0;
    NEW.last_outcome_sequence := 0;
    NEW.last_operational_outcome := NULL;
    NEW.last_outcome_at := NULL;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER {_REVISION_GUARD}
BEFORE UPDATE OF value ON {_TABLE}
FOR EACH ROW
WHEN (NEW.value IS DISTINCT FROM OLD.value
      AND NEW.credential_revision IS NOT DISTINCT FROM OLD.credential_revision)
EXECUTE FUNCTION {_REVISION_GUARD_FN}();
"""

_DROP_REVISION_GUARD_SQL = f"""
DROP TRIGGER IF EXISTS {_REVISION_GUARD} ON {_TABLE};
DROP FUNCTION IF EXISTS {_REVISION_GUARD_FN}();
"""


def _dialect_of(schema_editor: BaseSchemaEditor | None) -> str:
    capabilities = getattr(getattr(schema_editor, "client", None), "capabilities", None)
    return (getattr(capabilities, "dialect", "") or "").lower()


async def _bound_lock_wait(apps: Any, schema_editor: BaseSchemaEditor) -> None:
    del apps
    if _dialect_of(schema_editor) == "postgres":
        await schema_editor._run_sql(_SET_LOCK_TIMEOUT_SQL)  # noqa: SLF001


async def _restore_sqlite_indexes(apps: Any, schema_editor: BaseSchemaEditor) -> None:
    if _dialect_of(schema_editor) != "sqlite":
        return
    model = apps.get_model("models", _MODEL_NAME)

    # Tortoise's reverse RemoveField rebuilds omit unique_together. Rebuild once more from the
    # projected model so SQLite creates the pair rule as a table constraint (and therefore the same
    # internal autoindex shape as 0003), then restore its standalone indexes below.
    generator = schema_editor.client.schema_generator(schema_editor.client)
    generated = generator._get_table_sql(model, safe=False)  # noqa: SLF001
    create_table = str(generated["table_creation_string"]).partition(";")[0]
    table = model._meta.db_table
    replacement = f"new__{table}"
    quoted_table = schema_editor.quote(table)
    quoted_replacement = schema_editor.quote(replacement)
    create_replacement = create_table.replace(quoted_table, quoted_replacement, 1)
    columns = list(model._meta.fields_db_projection.values())
    quoted_columns = ", ".join(schema_editor.quote(column) for column in columns)
    await schema_editor._run_sql(create_replacement)  # noqa: SLF001
    await schema_editor._run_sql(  # noqa: SLF001
        f"INSERT INTO {quoted_replacement} ({quoted_columns}) "
        f"SELECT {quoted_columns} FROM {quoted_table}"
    )
    await schema_editor._run_sql(f"DROP TABLE {quoted_table}")  # noqa: SLF001
    await schema_editor._run_sql(  # noqa: SLF001
        f"ALTER TABLE {quoted_replacement} RENAME TO {quoted_table}"
    )

    statements: list[str] = []
    for field in model._meta.fields_map.values():
        if not getattr(field, "index", False) or getattr(field, "pk", False):
            continue
        statements.append(
            schema_editor._get_index_sql(  # noqa: SLF001
                model, [field.source_field or field.model_field_name]
            )
        )
    for index in model._meta.indexes or ():
        if isinstance(index, Index):
            index.resolve_expressions(model)
            statements.append(
                schema_editor._get_index_sql(  # noqa: SLF001
                    model,
                    list(index.field_names),
                    index_name=index.name,
                    index_type=index.INDEX_TYPE,
                    extra=index.extra,
                )
            )
        else:
            columns = [model._meta.fields_map[name].source_field or name for name in index]
            statements.append(schema_editor._get_index_sql(model, columns))  # noqa: SLF001
    for statement in dict.fromkeys(statements):
        await schema_editor._run_sql(statement)  # noqa: SLF001


async def _install_revision_guard(apps: Any, schema_editor: BaseSchemaEditor) -> None:
    del apps
    if _dialect_of(schema_editor) == "postgres":
        await schema_editor._run_sql(_CREATE_REVISION_GUARD_SQL)  # noqa: SLF001


async def _remove_revision_guard(apps: Any, schema_editor: BaseSchemaEditor) -> None:
    del apps
    if _dialect_of(schema_editor) == "postgres":
        await schema_editor._run_sql(_DROP_REVISION_GUARD_SQL)  # noqa: SLF001


class Migration(migrations.Migration):
    dependencies = [("models", "0012_provider_credential_slots")]

    operations = [
        # PostgreSQL ADD COLUMN needs ACCESS EXCLUSIVE even though no table rewrite occurs.
        # Give up the lock queue promptly; operators can rerun the atomic migration later.
        ops.RunPython(code=_bound_lock_wait, reverse_code=ops.RunPython.noop),
        ops.RunPython(code=ops.RunPython.noop, reverse_code=_restore_sqlite_indexes),
        ops.AddField(
            model_name=_MODEL_NAME,
            name="credential_revision",
            field=fields.BigIntField(default=1, db_default=1),
        ),
        ops.AddField(
            model_name=_MODEL_NAME,
            name="next_dispatch_sequence",
            field=fields.BigIntField(default=0, db_default=0),
        ),
        ops.AddField(
            model_name=_MODEL_NAME,
            name="last_outcome_sequence",
            field=fields.BigIntField(default=0, db_default=0),
        ),
        ops.AddField(
            model_name=_MODEL_NAME,
            name="last_operational_outcome",
            field=fields.CharField(max_length=32, null=True),
        ),
        ops.AddField(
            model_name=_MODEL_NAME,
            name="last_outcome_at",
            field=fields.DatetimeField(null=True),
        ),
        # Last on upgrade and therefore first on downgrade: the PostgreSQL trigger may only exist
        # while every operational column it references exists.
        ops.RunPython(
            code=_install_revision_guard,
            reverse_code=_remove_revision_guard,
        ),
    ]
