"""A Tortoise app that is not the Engine's, for `test_run_wiring.py` (OME-1785)."""

from tortoise import fields
from tortoise.models import Model


class Neighbour(Model):
    class Meta(Model.Meta):
        table = "neighbour"

    id = fields.IntField(primary_key=True)
