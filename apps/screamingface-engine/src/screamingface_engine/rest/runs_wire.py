"""The `/runs` wire (E5 P1 spec §4.1, E5 P2 spec §4.1): what `POST /runs` takes and what every
`/runs` read answers.

FEATURE: first-class Runs (OME-1785) and a detached Run (OME-1837).

INVARIANT (spec §4.1): no body here carries the owner or the owner's email.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    PlainSerializer,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from screamingface_engine import job_env
from screamingface_engine.runs.records import (
    CandidateRecord,
    CandidateStart,
    CandidateState,
    ContextRef,
    RunRecord,
    RunState,
    StopReason,
)


class StartBody(BaseModel):
    """One Candidate's start (E5 P2 spec D8): its url4 expression and the flags the start route
    takes as headers, checked as that route checks them."""

    # WHY forbid: a field this Engine does not know is refused, not silently dropped.
    model_config = ConfigDict(extra="forbid")

    name: str
    url4: str
    answer_seed: StrictInt | None = None
    capture: StrictBool = False
    use_cache: StrictBool = True
    replay_frozen_copy: str | None = None

    @field_validator("replay_frozen_copy")
    @classmethod
    def _frozen_copy_id(cls, value: str | None) -> str | None:
        if value is not None and job_env.FROZEN_COPY_ID.fullmatch(value) is None:
            raise ValueError("replay_frozen_copy must be a frozen copy id")
        return value

    @model_validator(mode="after")
    def _one_mode(self) -> StartBody:
        # As `X-Capture` with `X-Replay-Frozen-Copy` on the start route (OME-1307).
        if self.capture and self.replay_frozen_copy is not None:
            raise ValueError("a start cannot both capture and replay a frozen copy")
        return self

    def to_start(self) -> CandidateStart:
        return CandidateStart(
            name=self.name,
            url4=self.url4,
            answer_seed=self.answer_seed,
            capture=self.capture,
            use_cache=self.use_cache,
            replay_frozen_copy=self.replay_frozen_copy,
        )

    @classmethod
    def of(cls, start: CandidateStart) -> StartBody:
        return cls(
            name=start.name,
            url4=start.url4,
            answer_seed=start.answer_seed,
            capture=start.capture,
            use_cache=start.use_cache,
            replay_frozen_copy=start.replay_frozen_copy,
        )


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_key: str
    benchmark: str
    case_count: StrictInt
    # E5 P2 spec D1: the Engine starts every Candidate, so each carries its start.
    candidates: list[StartBody]
    client_version: str
    # The Client's context, kept as sent (spec D9b): the Engine does not parse it.
    context: str | None = None
    detach: StrictBool = False
    deadline_s: StrictInt | None = None


def _cost_text(cost: Decimal | None) -> str | None:
    """A cost in plain positional form, without trailing zeros. WHY: Postgres returns a `NUMERIC`
    at its column's full scale and SQLite does not, so one cost would read `0.5` on one database
    and `0.500000000000` on the other; and `str()` would write a tiny cost as `1E-12`."""
    return None if cost is None else f"{cost.normalize():f}"


class CandidateBody(BaseModel):
    """`start` and `record` are set by `GET /runs/{id}` only, and every other read leaves them
    out: the routes answer with `response_model_exclude_unset` (E5 P2 spec §4.1)."""

    index: int
    name: str
    state: CandidateState
    attempt_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    # Exact: a decimal string, as cost travels everywhere else on the wire.
    cost_usd: Annotated[Decimal | None, PlainSerializer(_cost_text, return_type=str | None)]
    error_code: str | None
    start: StartBody | None = None
    record: dict[str, Any] | None = None

    @classmethod
    def of(cls, candidate: CandidateRecord, *, full: bool) -> CandidateBody:
        body = cls(
            index=candidate.index,
            name=candidate.name,
            state=candidate.state,
            attempt_id=candidate.attempt_id,
            started_at=candidate.started_at,
            finished_at=candidate.finished_at,
            cost_usd=candidate.cost_usd,
            error_code=candidate.error_code,
        )
        if full:
            body.start = None if candidate.start is None else StartBody.of(candidate.start)
            body.record = candidate.record
        return body


class ContextBody(BaseModel):
    sha256: str
    size_bytes: int

    @classmethod
    def of(cls, context: ContextRef | None) -> ContextBody | None:
        return (
            None if context is None else cls(sha256=context.sha256, size_bytes=context.size_bytes)
        )


class RunBody(BaseModel):
    id: str
    state: RunState
    created_at: datetime
    finished_at: datetime | None
    benchmark: str
    case_count: int
    detached: bool
    deadline_at: datetime | None
    stopped_by: StopReason | None
    context: ContextBody | None
    candidates: list[CandidateBody]

    @classmethod
    def of(cls, record: RunRecord, *, full: bool = False) -> RunBody:
        return cls(
            id=record.id,
            state=record.state,
            created_at=record.created_at,
            finished_at=record.finished_at,
            benchmark=record.benchmark,
            case_count=record.case_count,
            detached=record.detached,
            deadline_at=record.deadline_at,
            stopped_by=record.stopped_by,
            context=ContextBody.of(record.context),
            candidates=[CandidateBody.of(c, full=full) for c in record.candidates],
        )


class RunList(BaseModel):
    runs: list[RunBody]
    next_cursor: str | None


__all__ = ["CandidateBody", "ContextBody", "RunBody", "RunCreate", "RunList", "StartBody"]
