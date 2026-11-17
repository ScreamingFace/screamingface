"""Remove ``migration_note`` from the migration state only; the column stays (OME-1138, L4c-1).

UPGRADE. No SQL. The projected ``ProviderCredentialSlot`` loses the field, as the model does. The
column stays in ``provider_credential_slots``, nullable, and nothing reads or writes it: Tortoise
names every declared field in its SELECT and INSERT, so every image before this one, L4a's
included, needs the column. Dropping it here would break their marker queries while a rollout
still runs their Pods, and after any rollback to them. ``0017`` drops it one gateway release
later, when no running image declares it.

DOWNGRADE. No SQL: the field returns to the projected state, over the column that never left.

AUTHORING NOTE. Generated with ``tortoise makemigrations -n forget_migration_note models`` and then
edited, as ``0012``–``0015`` were: the autodetector's ``AlterField`` on ``OAuthConnection.account``
is DROPPED (the pre-existing drift ``0012`` describes), and its ``RemoveField`` became
``ForgetMigrationNote``, which changes the projected state only.
"""

from tortoise import migrations
from tortoise.migrations import operations as ops
from tortoise.migrations.schema_editor.base import BaseSchemaEditor
from tortoise.migrations.schema_generator.state import State


class ForgetMigrationNote(ops.RemoveField):
    """``RemoveField`` with no SQL in either direction: the column outlives the field."""

    def __init__(self) -> None:
        super().__init__(model_name="ProviderCredentialSlot", name="migration_note")

    async def database_forward(
        self,
        app_label: str,
        old_state: State,
        new_state: State,
        state_editor: BaseSchemaEditor | None = None,
    ) -> None:
        return None

    async def database_backward(
        self,
        app_label: str,
        old_state: State,
        new_state: State,
        state_editor: BaseSchemaEditor | None = None,
    ) -> None:
        return None


class Migration(migrations.Migration):
    dependencies = [("models", "0015_cache_entry_write_order")]

    initial = False

    operations = [ForgetMigrationNote()]
