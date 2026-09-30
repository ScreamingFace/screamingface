from __future__ import annotations

from tortoise import Model

# The width of an idempotency key: `IdempotencyKey.key` and `ReportedResult.run_id` (FS-1).
IDEMPOTENCY_KEY_MAX_LEN = 255


class BaseScoreboardModel(Model):
    class Meta:
        abstract = True
