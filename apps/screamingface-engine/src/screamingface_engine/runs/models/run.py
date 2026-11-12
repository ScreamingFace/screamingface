"""One Run: who registered it, what it evaluates, the facts its state needs besides its
Candidates (the cancel flag and the stop's reason), and what the Engine's driver needs to finish
it after its Client has gone (E5 P2 spec D4, D8, D10, D11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tortoise import fields
from tortoise.models import Model

from screamingface_engine.runs.records import (
    MAX_BENCHMARK_LENGTH,
    MAX_CLIENT_KEY_LENGTH,
    MAX_CLIENT_VERSION_LENGTH,
    MAX_OWNER_EMAIL_LENGTH,
)

if TYPE_CHECKING:
    from screamingface_engine.runs.models.candidate import Candidate

RUN_ID_LENGTH = 36  # `run_` + 32 hex digits (`runs.ids`)
OWNER_KEY_LENGTH = 64  # a sha256 in hex (`runs.records.owner_key`)
SHA256_LENGTH = 64
STOP_REASON_LENGTH = 16


class BaseRun(Model):
    # WHY each Meta subclasses its parent's: a bare nested `Meta` is an incompatible override to
    # pyright. Tortoise reads only the attributes, so the concrete model states `abstract = False`.
    class Meta(Model.Meta):
        abstract = True

    id = fields.CharField(primary_key=True, max_length=RUN_ID_LENGTH)
    # INVARIANT (spec D6): the hash of the owner's normalised email, never the email itself.
    owner = fields.CharField(max_length=OWNER_KEY_LENGTH)
    client_key = fields.CharField(max_length=MAX_CLIENT_KEY_LENGTH)
    benchmark = fields.CharField(max_length=MAX_BENCHMARK_LENGTH)
    case_count = fields.IntField()
    client_version = fields.CharField(max_length=MAX_CLIENT_VERSION_LENGTH)
    # INVARIANT (spec D12): sticky; set once and never cleared.
    canceled = fields.BooleanField(default=False)
    # WHY not `auto_now_add`: the store stamps both from its injected clock, so a test can move
    # time and the state rule (R5) reads the same clock that wrote them.
    created_at = fields.DatetimeField()
    # INVARIANT (spec §4.3): moves forward only, on every bind, schedule, settle and cancel.
    last_activity_at = fields.DatetimeField()
    # E5 P2 spec D11: a detached Run stops at `deadline_at`; an attached one when nobody follows
    # it (D10), or at `deadline_at` too when that rule is off.
    detached = fields.BooleanField(default=False, db_default=False)
    deadline_at = fields.DatetimeField(null=True)
    # INVARIANT (E5 P2 spec D12): the first stop's reason, set once and never changed.
    stopped_by = fields.CharField(max_length=STOP_REASON_LENGTH, null=True)
    # E5 P2 spec D8: the driver starts the Candidates as this owner after the Client has gone.
    # AIDEV-NOTE: personal data; returned by no route, and never logged.
    owner_email = fields.CharField(max_length=MAX_OWNER_EMAIL_LENGTH, null=True)
    # E5 P2 spec D4: one driver per Run, by this lease. NULL when nobody holds it.
    driver_lease_until = fields.DatetimeField(null=True)
    # INVARIANT (E5 P2 spec R10): moves forward only; the attached Run's orphan clock.
    last_followed_at = fields.DatetimeField(null=True)
    # E5 P2 spec D9b: the Client's context lives in the run-results store; these name it.
    context_sha256 = fields.CharField(max_length=SHA256_LENGTH, null=True)
    context_bytes = fields.IntField(null=True)


class Run(BaseRun):
    class Meta(BaseRun.Meta):
        abstract = False
        table = "runs"
        # WHY (spec §4.1): a retried `POST /runs` returns the same Run, even under a race.
        unique_together = (("owner", "client_key"),)
        # Newest-first paging within one owner, the id breaking ties (spec D5).
        indexes = (("owner", "created_at", "id"),)

    if TYPE_CHECKING:
        candidates: fields.ReverseRelation[Candidate]
