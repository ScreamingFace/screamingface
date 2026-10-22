"""Index ``request_cache_entries`` in write order (epic OME-1311).

UPGRADE. One ``CREATE INDEX`` on ``(updated_at, key_hash)``: the order the community-cache pages
are read in (``core/request_cache/community_pages.py``). Without it every page sorts the whole
table; with it a page is a range read. No row and no other index is touched, and nothing is
rebuilt. On Postgres the build holds a lock that makes writes to the table wait for its duration
(seconds at ~600k rows).

DOWNGRADE. ``DROP INDEX`` of that index only.

AUTHORING NOTE. Generated with ``tortoise makemigrations -n cache_entry_write_order models`` and
then edited, as 0014 was: the autodetector's ``AlterField`` on ``OAuthConnection.account`` is
DROPPED. That is the pre-existing drift between 0002's foreign-key spelling and the projected
state (see 0012); applying it would rebuild ``oauth_connections`` on SQLite and drop that table's
standalone indexes.
"""

from tortoise import migrations
from tortoise.indexes import Index
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("models", "0014_frozen_copies")]

    initial = False

    operations = [
        ops.AddIndex(
            model_name="RequestCacheEntry",
            index=Index(fields=["updated_at", "key_hash"]),
        ),
    ]
