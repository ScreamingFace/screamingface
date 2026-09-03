"""Spec §2.1's report, as pydantic models.

Two rules shape every `model_config` below.

**Unknown keys are forbidden at the top level and preserved inside `client` and `context`.** The
top level is a small stable set, so an unknown key there is a typo worth a 422. `client` and
`context` are the declared extension points: clients in four languages will not ship in lockstep,
and a `node` client adding `electron_version` must not be rejected by a service that predates it.
What arrives there is stored verbatim, counted against the depth and key-count caps, and never
interpreted.

**`client` names no language.** Three of the four client surfaces are not Python — Studio
(Electron), aigateway-ui (Next.js), the portal (browser JS) — so `name` identifies the SDK or app
and `runtime` identifies whatever executes it. The same `{name, version}` pair is reused for
`client`, `runtime`, and `frontend` so that "which versions are failing?" is a group-by rather
than a string parse.

The vocabularies for `host`, `platform`, and `runtime.name` are **documented, not enforced**: an
unrecognised value is stored, not rejected. Nothing branches on them in v1, and a client shipping
before the service learns its name must still be able to report a bug.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .caps import Truncation
from .models import EMAIL_MAX_LENGTH

SupportedSchema = Literal["screamingface.error-report/v1"]
SUPPORTED_SCHEMA: SupportedSchema = "screamingface.error-report/v1"
SCHEMA_FAMILY = SUPPORTED_SCHEMA.rpartition("/")[0]

_EXTENSIBLE = ConfigDict(extra="allow")
_CLOSED = ConfigDict(extra="forbid")


class Runtime(BaseModel):
    """The language runtime: `cpython`, `node`, `browser`, …"""

    model_config = _EXTENSIBLE

    name: str
    version: str


class Frontend(BaseModel):
    """Browser-side host of the client, reported through a widget comm when there is one."""

    model_config = _EXTENSIBLE

    name: str
    version: str


class Client(BaseModel):
    model_config = _EXTENSIBLE

    name: str
    version: str
    host: str
    platform: str
    runtime: Runtime
    frontend: Frontend | None = None
    user_agent: str | None = None


class Error(BaseModel):
    """The failure itself.

    `message` is carried VERBATIM and must not be "cleaned up" into structured fields: in the
    current Python client the WebSocket close code and the elapsed seconds exist only inside that
    string, because `ExecutionError` adds no attributes over its base.

    `type` and `message` are the two required members. Everything else is genuinely optional —
    a report with neither a type nor a message is not a weaker report, it is not a report.
    """

    model_config = _CLOSED

    type: str
    message: str
    code: str | None = None
    status: int | None = None
    permanent: bool | None = None
    retryable: bool | None = None
    hint: str | None = None
    notes: list[str] = Field(default_factory=list)
    details: dict[str, Any] | None = None
    cause: dict[str, Any] | None = None
    traceback: str | None = None


class Correlation(BaseModel):
    """All-nullable by design. A report with no trace id is weaker, not invalid — until
    `OME-967` lands, reports join on (endpoint, approximate timestamp) only.

    INVARIANT: nothing here ever authorizes anything. An id in a report is a claim, not a
    credential (`OME-966`).
    """

    model_config = _CLOSED

    trace_id: str | None = None
    run_id: str | None = None
    gateway_call_id: str | None = None


class Benchmark(BaseModel):
    model_config = _EXTENSIBLE

    id: str | None = None
    revision: str | None = None


class Candidate(BaseModel):
    model_config = _EXTENSIBLE

    name: str | None = None
    kind: str | None = None
    models: list[str] | None = None


class Context(BaseModel):
    """Caller-supplied and nullable throughout. A generic `except` around an evaluation gets none
    of it, because the runner re-raises untouched and the transport attaches no candidate — so the
    service treats every field as optional and never infers one.

    `engine_host` is a HOST, never a full URL: a URL carries a path and a query string, and a
    query string is where a prompt ends up.
    """

    model_config = _EXTENSIBLE

    engine_host: str | None = None
    benchmark: Benchmark | None = None
    candidate: Candidate | None = None


class ReportDocument(BaseModel):
    model_config = _CLOSED

    schema_: SupportedSchema = Field(alias="schema")
    """Aliased because `schema` shadows an attribute pydantic's `BaseModel` still defines. The
    wire name is `schema` and only `schema` — the alias is not populatable by field name."""

    occurred_at: datetime
    client: Client
    error: Error
    correlation: Correlation = Field(default_factory=Correlation)
    context: Context | None = None
    note: str | None = None
    reply_to: str | None = Field(default=None, max_length=EMAIL_MAX_LENGTH)
    """Self-asserted and never identity. It matters more than it looks: the Python client parses
    only `exp` from its Access token, so it has no email of its own — without this, an SDK report
    cannot be answered.

    **DECIDED: a syntactically invalid address is ACCEPTED, and nothing here or downstream
    checks the syntax of one.** `str`, not `EmailStr`, and that is a decision rather than an
    omission — spec §9's caller table already states the posture in two words, *accepted,
    unverified*, for both caller classes, and this is where the code says so.

    The reasoning is that rejecting costs more than accepting. A `422` on `reply_to` throws away
    the error, the traceback, the client versions and the trace id — everything that makes the
    report diagnosable — over the one field this service authorizes nothing on and never treats
    as identity. A report with a typo'd address is still a report somebody can act on; a report
    that was refused is not. Spec §8's rule for the client is that a report is never lost, and
    losing one to a mistyped address is this service losing it.

    The cost is paid where it can be, not hidden: `delivery/render.py` labels a value that does
    not look like an address as such, so a triager reading the ticket is not misled into believing
    somebody is waiting on a reply that will bounce. That label is a rendering — it never rewrites
    or drops the value, and no code branches on it.

    **The `max_length` below is a LENGTH refusal and is not a syntax check** — the two are
    unrelated and the second must not be added on the strength of the first:

    Bounded to the COLUMN's width, and that is the whole reason the bound is here rather than in
    `caps.py` with §2.4's truncating rows. An unbounded value inside a body well under the 64 KiB
    cap reaches a `varchar(320)`, tortoise's validator raises, and every ORM failure leaves the
    store as `StorageUnavailable` — so a 400-character address was answered `503`, which spec §8
    tells the client means *keep the report and retry unchanged*. That is a permanent failure
    reported as a transient one. Truncate-and-mark would be worse than a refusal here: a shortened
    address is not a shorter address, it is somebody else's or nobody's, and the field exists to
    be replied to. As a `max_length` it is a schema violation with a field pointer, which is
    exactly spec §2.3's `422` row.
    """


@dataclass(frozen=True, slots=True)
class BoundedReport:
    """What the route hands everything downstream: a report whose every leaf fits a stated cap.

    Nothing after this point re-checks a size. That is the point of the type.
    """

    document: ReportDocument
    """The typed view, for code that wants fields."""

    payload: Mapping[str, Any]
    """The validated, truncated mapping — this is what gets persisted."""

    truncations: tuple[Truncation, ...]
    """What §2.4 cut, and by how much."""

    scanned: Mapping[str, Any]
    """Control-stripped but **pre-truncation**, and never persisted.

    It exists for one reason: `OME-1007` classifies content, and a classifier that reads
    `payload` cannot see prompt text that truncation removed — which would make truncation a way
    to smuggle content past the check. Both mappings are held for one request over a body already
    capped at 64 KiB.
    """
