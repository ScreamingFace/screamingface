"""The frozen copy: an opted-in run's chat and tool exchanges, kept for replay (OME-1307).

FEATURE: E14 reproducible submission. A copy is opened by the run's account, filled while the run
captures, then sealed. Replay reads only sealed copies. Design: 02-frozen-copy-design.md §3.

INVARIANT (F1): entries are insert-only, and a sealed copy accepts no insert.
INVARIANT (F2): copies and entries are kept forever; no endpoint lists stored requests.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from tortoise import fields
from tortoise.models import Model

if TYPE_CHECKING:
    from aigateway.core.auth.models import Account

STATUS_OPEN = "open"
STATUS_SEALED = "sealed"
KIND_CHAT = "chat"
KIND_TOOL = "tool"


class FrozenCopy(Model):
    class Meta:
        table = "frozen_copies"

    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    # The account that opened the copy. Only it may write or seal.
    account: fields.ForeignKeyRelation[Account] = fields.ForeignKeyField(
        "models.Account",
        related_name="frozen_copies",
        on_delete=fields.OnDelete.CASCADE,
    )
    status = fields.CharField(max_length=16, default=STATUS_OPEN)
    # Set at seal; 0 while open.
    entries = fields.IntField(default=0)
    created_at = fields.DatetimeField(auto_now_add=True)
    sealed_at = fields.DatetimeField(null=True)

    if TYPE_CHECKING:
        account_id: uuid.UUID


class FrozenCopyEntry(Model):
    class Meta:
        table = "frozen_copy_entries"
        # The replay lookup: every entry of one (copy, kind, digest) in capture order.
        indexes = (("frozen_copy_id", "kind", "request_digest", "created_at"),)

    id = fields.UUIDField(pk=True, default=uuid.uuid4)
    frozen_copy: fields.ForeignKeyRelation[FrozenCopy] = fields.ForeignKeyField(
        "models.FrozenCopy",
        related_name="entry_rows",
        on_delete=fields.OnDelete.CASCADE,
    )
    kind = fields.CharField(max_length=8)
    request_digest = fields.CharField(max_length=64)
    request_json: Any = fields.JSONField()
    response_json: Any = fields.JSONField()
    # 200 for a success; the HTTP status of a captured error.
    status_code = fields.IntField()
    created_at = fields.DatetimeField(auto_now_add=True)

    if TYPE_CHECKING:
        frozen_copy_id: uuid.UUID


__models__ = [FrozenCopy, FrozenCopyEntry]
