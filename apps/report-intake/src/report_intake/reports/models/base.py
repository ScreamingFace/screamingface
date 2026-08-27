from __future__ import annotations

from tortoise import Model


class BaseReportIntakeModel(Model):
    class Meta:
        abstract = True
