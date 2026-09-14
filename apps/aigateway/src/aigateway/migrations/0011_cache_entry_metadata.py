"""Append the nullable standard-metadata column to ``request_cache_entries`` (A3, ERD §5.1).

``ALTER TABLE request_cache_entries ADD COLUMN metadata_json TEXT NULL`` — nullable with NO
default, appended last.

UPGRADE. On Postgres this is catalog-only: no table rewrite, no long lock, no backfill. On
SQLite it is a plain in-place ``ADD COLUMN``. Neither dialect rebuilds the table, so the
standalone indexes SQLite drops with a rebuilt table are not at risk and no index-restore
workaround runs forward. Pinned by ``test_0011_does_not_rebuild_the_sqlite_table``.

The 12-column legacy layout stays loadable (``snapshot.ACCEPTED_COLUMN_LAYOUTS``), so a snapshot
taken before this migration still restores with ``metadata_json`` NULL.

DOWNGRADE. ``RemoveField`` DOES rebuild the table on SQLite, and that rebuild recreates no
standalone indexes — the defect 0009 and 0010 both document. A bare ``RemoveField`` would
therefore silently strip all five single-column indexes from every local database, even though
dropping an unindexed column has no reason to touch them. The reverse-only restore below puts
them back, derived from the model so a later indexed field is covered too.

WHY nullable and why no default. NULL is the documented "unknown" for this column and is never
read as ``0`` (PRD I1). A ``DEFAULT '{}'`` would materialise a block claiming a capture that
never happened, and every future writer would inherit it.

ROLLBACK. ``DROP COLUMN metadata_json`` — nullable, unindexed and referenced by no old code, so
nothing else has to move with it. A pre-change gateway reading a table that still has the column
is unaffected by its presence.
"""

from typing import Any

from tortoise import fields, migrations
from tortoise.indexes import Index
from tortoise.migrations import operations as ops
from tortoise.migrations.schema_editor.base import BaseSchemaEditor

_MODEL_NAME = "RequestCacheEntry"
# The only dialect whose DROP COLUMN rebuilds the table (and so loses its indexes).
_REBUILDING_DIALECTS = frozenset({"sqlite"})


async def _restore_sqlite_indexes(apps: Any, schema_editor: BaseSchemaEditor) -> None:
    """Recreate the standalone indexes SQLite's reverse table rebuild dropped.

    Built through the schema generator's own ``_get_index_sql`` so the index NAMES match the
    ones the original ``CreateModel`` produced — a hand-rolled name would leave a duplicate
    index behind on the next rebuild. Derived from the projected model rather than hardcoded,
    so a later indexed column is restored too.
    """
    capabilities = getattr(getattr(schema_editor, "client", None), "capabilities", None)
    dialect = (getattr(capabilities, "dialect", "") or "").lower()
    if dialect not in _REBUILDING_DIALECTS:
        return

    model = apps.get_model("models", _MODEL_NAME)
    statements: list[str] = []
    for field in model._meta.fields_map.values():
        if not getattr(field, "index", False) or getattr(field, "pk", False):
            continue
        column = field.source_field or field.model_field_name
        statements.append(schema_editor._get_index_sql(model, [column]))  # noqa: SLF001
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
            continue
        columns = [model._meta.fields_map[name].source_field or name for name in index]
        statements.append(schema_editor._get_index_sql(model, columns))  # noqa: SLF001

    for statement in dict.fromkeys(statements):
        await schema_editor._run_sql(statement)  # noqa: SLF001


class Migration(migrations.Migration):
    dependencies = [("models", "0010_simplify_request_cache")]

    operations = [
        # First in the list, so it runs LAST on downgrade — after AddField's reverse has
        # rebuilt the table and taken the indexes with it. The forward direction is a no-op
        # by design: ADD COLUMN rebuilds nothing.
        ops.RunPython(code=ops.RunPython.noop, reverse_code=_restore_sqlite_indexes),
        # Mirrors `BaseRequestCacheEntry.metadata_json` exactly — any drift here re-arms the
        # autodetector, which would propose the same add again (`makemigrations` drift is caught
        # by `test_autodetector_proposes_no_request_cache_change`).
        ops.AddField(
            model_name=_MODEL_NAME,
            name="metadata_json",
            field=fields.TextField(null=True),
        ),
    ]
