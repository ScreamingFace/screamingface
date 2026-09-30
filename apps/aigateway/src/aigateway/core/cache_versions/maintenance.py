"""The operator prune of orphan prompts (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - a cache prune must never delete a prompt that a later freeze needs.

INVARIANT (CV-D13): a prompt row survives while any ``cache_capture_entry`` row (the run index) or
any live ``request_cache_entries`` row names its key.

AIDEV-NOTE: capture writes a prompt only together with a capture row, so in normal operation this
statement deletes nothing. It exists so that a manual cleanup cannot delete a prompt that a later
freeze needs. ``DEPLOYMENT.md`` shows the same string, and a test pins that.
"""

from __future__ import annotations

from typing import Final

from tortoise import connections

PRUNE_ORPHAN_PROMPTS_SQL: Final = (
    "DELETE FROM request_cache_prompt "
    "WHERE NOT EXISTS (SELECT 1 FROM cache_capture_entry c "
    "WHERE c.key_hash = request_cache_prompt.key_hash) "
    "AND NOT EXISTS (SELECT 1 FROM request_cache_entries e "
    "WHERE e.key_hash = request_cache_prompt.key_hash)"
)


async def prune_orphan_prompts() -> int:
    """Delete the prompts that no capture row and no live cache row names; return the count.

    The statement runs unchanged on SQLite and on PostgreSQL. The first item of the result of
    ``execute_query`` is the number of rows that the statement deleted, on both drivers.
    """
    deleted, _rows = await connections.get("default").execute_query(PRUNE_ORPHAN_PROMPTS_SQL)
    return deleted
