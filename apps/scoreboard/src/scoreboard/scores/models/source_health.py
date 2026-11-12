"""Availability of an exact citation URL, separate from score edit history."""

from tortoise import fields

from .base import BaseScoreboardModel


class BaseSourceHealth(BaseScoreboardModel):
    class Meta:
        abstract = True

    # WHY: a fixed-size digest avoids PostgreSQL index limits for long Unicode URLs.
    source_key = fields.CharField(max_length=64, primary_key=True)
    source_url = fields.CharField(max_length=2048)
    available = fields.BooleanField()
    checked_at = fields.DatetimeField()
    last_available_at = fields.DatetimeField(null=True)


class SourceHealth(BaseSourceHealth):
    class Meta:
        table = "external_source_health"
