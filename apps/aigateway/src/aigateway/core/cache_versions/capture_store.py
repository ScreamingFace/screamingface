"""The Tortoise adapter of the capture sink (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - one traced call writes its prompt once per key, and one index row.

INVARIANT (CV-24): the prompt is stored once per ``key_hash``. ``ignore_conflicts=True`` renders
``ON CONFLICT DO NOTHING`` (Postgres) and ``INSERT OR IGNORE`` (SQLite), so ten concurrent first
writes of one key leave one prompt row and never raise.

AIDEV-NOTE: the two statements run in ONE ``in_transaction()``. WHY:
- One transaction is one commit for each traced call, so the call waits for one fsync, not two.
  On a shared disk a stalled commit cost 40 to 160 ms at p99 (the CI bench, OME-1434).
- The pair is all-or-nothing. A prompt row without its capture row is useless to a freeze.
- The Postgres "poisoned transaction" risk (see the note in ``routes/chat.py``) is handled. The
  prompt insert cannot fail on a duplicate key (ON CONFLICT DO NOTHING / INSERT OR IGNORE), and
  ``in_transaction`` rolls back on any exception, so a failed capture insert leaves no prompt row.
- Capture fails open in the route: the except block of ``record_capture`` in
  ``routes/chat_capture_stage.py`` catches the sink error and counts it in
  ``CaptureStats.failures``.
- ``record`` never runs inside a caller's outer transaction. Its only caller is ``record_capture``,
  and the single exit of the chat route is not inside ``in_transaction``. If a later caller wraps
  it in a transaction, this block becomes a savepoint, and the pair is all-or-nothing only within
  that caller's transaction.
- The ``as conn`` and ``using_db=conn`` are explicit so that a future helper cannot pick another
  connection.
"""

from __future__ import annotations

from tortoise.transactions import in_transaction

from .models import CacheCaptureEntry, RequestCachePrompt
from .ports import CaptureRecord


class TortoiseCaptureSink:
    async def record(self, record: CaptureRecord) -> None:
        async with in_transaction() as conn:
            if record.key_hash is not None and record.request_material is not None:
                await RequestCachePrompt.bulk_create(
                    [
                        RequestCachePrompt(
                            key_hash=record.key_hash, request_json=record.request_material
                        )
                    ],
                    ignore_conflicts=True,
                    using_db=conn,
                )
            await CacheCaptureEntry.create(
                account_id=record.account_id,
                trace_id=record.trace_id,
                key_hash=record.key_hash,
                outcome=record.outcome,
                response_json=record.response_json,
                using_db=conn,
            )
