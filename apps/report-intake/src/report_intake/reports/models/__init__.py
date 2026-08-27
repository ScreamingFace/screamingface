"""Report models — spec §5's single table."""

from .base import BaseReportIntakeModel
from .report import (
    EMAIL_MAX_LENGTH,
    IDEMPOTENCY_KEY_MAX_LENGTH,
    REF_MAX_LENGTH,
    BaseReport,
    Report,
)

__all__ = [
    "EMAIL_MAX_LENGTH",
    "IDEMPOTENCY_KEY_MAX_LENGTH",
    "REF_MAX_LENGTH",
    "BaseReport",
    "BaseReportIntakeModel",
    "Report",
]
