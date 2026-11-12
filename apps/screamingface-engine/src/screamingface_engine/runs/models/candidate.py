"""One Candidate of a Run: its place in the Run, how to start it, the topic it started on, and
how it ended."""

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
TRACE_ID_LENGTH = 32  # a W3C trace id in hex


class BaseCandidate(Model):
    class Meta(Model.Meta):
        abstract = True

    id = fields.IntField(primary_key=True)

    # Zero-based, in the Run's `candidates` order (spec §4.1).
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
    # INVARIANT (spec D12): a cancel owes a stop to every bound Candidate it found live; the stop
    # clears it. A retried cancel stops exactly what is still owed, and nothing else.
    stop_owed = fields.BooleanField(default=False, db_default=False)
    # E5 P2 spec D8: the url4 expression and flags the driver starts it with. NULL on a Run a
    # Client from before P2 registered, which nothing in the Engine starts.
    start: fields.Field[dict | None] = fields.JSONField(null=True)
    # E5 P2 spec §4.3: what the runner reported when the run ended, NULL until then.
    record: fields.Field[dict | None] = fields.JSONField(null=True)
    # INVARIANT (E5 P2 spec §4.3): one trace for the Candidate's whole life, sent with every start.
    trace_id = fields.CharField(max_length=TRACE_ID_LENGTH, null=True)


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
