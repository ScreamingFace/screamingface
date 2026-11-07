"""One Candidate of a Run: its place in the Run, the topic it started on, and how it ended."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tortoise import fields
from tortoise.models import Model

from screamingface_engine.auth.token import TOPIC_LENGTH
from screamingface_engine.candidate_outcomes import COST_DIGITS, COST_PLACES, ERROR_CODE_LENGTH
from screamingface_engine.runs.records import MAX_CANDIDATE_NAME_LENGTH

if TYPE_CHECKING:
    from screamingface_engine.runs.models.run import Run

STATE_LENGTH = 16


class BaseCandidate(Model):
    class Meta(Model.Meta):
        abstract = True

    id = fields.IntField(primary_key=True)

    # Zero-based, in the Run's `candidates` order: what `X-SF-Run-Candidate` names (spec §4.1).
    index = fields.IntField()
    name = fields.CharField(max_length=MAX_CANDIDATE_NAME_LENGTH)
    # INVARIANT (spec R2): a topic binds to exactly one Candidate of one Run (unique), so an
    # outcome for it always has one target. NULL until the Candidate's first start binds it.
    topic = fields.CharField(max_length=TOPIC_LENGTH, null=True, unique=True)
    state = fields.CharField(max_length=STATE_LENGTH, default="pending")
    bound_at = fields.DatetimeField(null=True)
    finished_at = fields.DatetimeField(null=True)
    cost_usd = fields.DecimalField(max_digits=COST_DIGITS, decimal_places=COST_PLACES, null=True)
    error_code = fields.CharField(max_length=ERROR_CODE_LENGTH, null=True)


class Candidate(BaseCandidate):
    class Meta(BaseCandidate.Meta):
        abstract = False
        table = "run_candidates"
        unique_together = (("run", "index"),)
        # Reconcile's scan (spec R6): live Candidates by how long ago they were bound.
        indexes = (("state", "bound_at"),)

    run: fields.ForeignKeyRelation[Run] = fields.ForeignKeyField(
        "runs.Run", related_name="candidates", on_delete=fields.OnDelete.CASCADE
    )

    if TYPE_CHECKING:
        run_id: str
