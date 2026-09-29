"""The Tortoise adapter of the capture sink (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - one traced call writes its prompt once per key, and one index row.

INVARIANT (CV-24): the prompt is stored once per ``key_hash``. ``ignore_conflicts=True`` renders
``ON CONFLICT DO NOTHING`` (Postgres) and ``INSERT OR IGNORE`` (SQLite), so ten concurrent first
writes of one key leave one prompt row and never raise.

AIDEV-NOTE: do NOT wrap the two statements in ``in_transaction()``. On Postgres a failed statement
inside a transaction poisons it (the same reason as the note in ``routes/chat.py``). Two autocommit
statements are safe: a prompt row without a capture row is harmless (erd I-P1).
"""

from __future__ import annotations

from .models import CacheCaptureEntry, RequestCachePrompt
from .ports import CaptureRecord


class TortoiseCaptureSink:
    async def record(self, record: CaptureRecord) -> None:
        if record.key_hash is not None and record.request_material is not None:
            await RequestCachePrompt.bulk_create(
                [
                    RequestCachePrompt(
                        key_hash=record.key_hash, request_json=record.request_material
                    )
                ],
                ignore_conflicts=True,
            )
        await CacheCaptureEntry.create(
            account_id=record.account_id,
            trace_id=record.trace_id,
            key_hash=record.key_hash,
            outcome=record.outcome,
            response_json=record.response_json,
        )
