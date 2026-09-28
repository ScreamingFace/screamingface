from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from url4.streaming.protocol.taxonomy import CostBreakdown, ErrorInfo, TokenUsage


class StartedData(BaseModel):
    url4: str


Severity = Literal["DEBUG", "INFO", "WARN", "ERROR"]

SEVERITY_NUMBER: dict[Severity, int] = {"DEBUG": 5, "INFO": 9, "WARN": 13, "ERROR": 17}
"""OTel SeverityNumber per level. The model owns BOTH severity fields, so it owns the mapping
between them too — `LogData(severity_number=9, severity_text="ERROR")` would otherwise validate."""


class LogData(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    severity_number: int
    """OTel SeverityNumber — see :data:`SEVERITY_NUMBER`; use :meth:`at` rather than pairing
    this with `severity_text` by hand."""
    severity_text: Severity
    body: str
    attributes: dict[str, str | int | float | bool | None] = {}

    @classmethod
    def at(
        cls,
        severity: Severity,
        body: str,
        attributes: dict[str, str | int | float | bool | None] | None = None,
    ) -> "LogData":
        """Build a log at `severity`, deriving `severity_number` so the pair cannot disagree."""
        return cls(
            severity_number=SEVERITY_NUMBER[severity],
            severity_text=severity,
            body=body,
            attributes=attributes or {},
        )


class SpanData(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True, use_attribute_docstrings=True, title="GenAI span"
    )

    name: str
    kind: Literal["client", "internal", "server"] = "internal"
    operation: str = Field(
        validation_alias="gen_ai.operation.name",
        serialization_alias="gen_ai.operation.name",
    )
    provider: str | None = Field(
        default=None,
        validation_alias="gen_ai.provider.name",
        serialization_alias="gen_ai.provider.name",
    )
    request_model: str | None = Field(
        default=None,
        validation_alias="gen_ai.request.model",
        serialization_alias="gen_ai.request.model",
    )
    response_model: str | None = Field(
        default=None,
        validation_alias="gen_ai.response.model",
        serialization_alias="gen_ai.response.model",
    )
    input_tokens: int | None = Field(
        default=None,
        validation_alias="gen_ai.usage.input_tokens",
        serialization_alias="gen_ai.usage.input_tokens",
    )
    output_tokens: int | None = Field(
        default=None,
        validation_alias="gen_ai.usage.output_tokens",
        serialization_alias="gen_ai.usage.output_tokens",
    )
    finish_reasons: list[str] | None = Field(
        default=None,
        validation_alias="gen_ai.response.finish_reasons",
        serialization_alias="gen_ai.response.finish_reasons",
    )
    """How each model call on this span ended (`stop` | `length` | `content_filter` |
    `tool_calls`). A LIST because one span can make several calls — a tool-calling turn is
    several round trips.

    Absent (`None`) when this span contributed no reason at all: either it made no model call, or
    its calls omitted `finish_reason`. Those two are NOT distinguishable here — the producer
    collapses both to absent so the attribute follows OTel's absent-or-populated convention."""
    refusal: str | None = Field(default=None)
    """The provider's refusal text, when it sends one. Deliberately NOT a `gen_ai.*` alias:
    OTel has no semantic convention for this field, and inventing one would misrepresent a
    local extension as a standard attribute."""
    cache_status: Literal["hit", "miss", "bypass"] | None = Field(default=None)
    """Whether the gateway served this span's call from its response cache.

    Absent when nothing reported one — an older gateway, or a path that never reached the cache.
    Without it a hit that cost nothing upstream is still billed as a fresh call, an error that
    HIDES savings and so goes unreported. Not a `gen_ai.*` alias, for the same reason as
    `refusal`: OTel defines no convention for it."""
    cache_reason: str | None = Field(default=None)
    """The gateway's reason for that status, VERBATIM — its vocabulary, not ours.

    Recorded rather than mapped so "I asked for no caching and something still cached" stays an
    answerable question; normalising it here would erase exactly the distinction that answers it."""
    cache_saved_cost_usd: Decimal | None = Field(default=None)
    """What the provider would have charged had the gateway not served this span's hits from its
    cache, as the PROVIDER itself priced them.

    A COUNTERFACTUAL, not consumption: the current-request cost stays 0 on a hit (PRD I1), and
    `CostBreakdown` is a closed object (`extra="forbid"`) so this deliberately does NOT ride in
    the cost block. Absent when nothing priceable was saved — `None` is not `Decimal("0")`.

    INVARIANT: a SPAN TOTAL, summed across every provider-authored hit this span made. A
    tool-calling turn is several independently-keyed calls against one span (PRD §4.1), so the
    money here is additive where the `cache_status` above it is categorical and last-wins. That
    is what lets a trace backend sum this attribute across a run's spans and land on the run's
    own `cache.saved_cost_usd` — the thing anyone will do with an attribute named for money."""
    cache_saved_cost_archive_usd: Decimal | None = Field(default=None)
    """The same total for this span's ARCHIVE-MATCHED hits, and the reason there are two fields.

    A price paired from the DRACO archive, real but whose per-row attribution is unproven (PRD
    ans:Q5), so it may only ever be reported and totalled on its own. Kept as a second FIELD
    rather than as a provenance tag beside one amount precisely so the two can never be summed
    (PRD S5): a single amount plus a label invites a consumer to add the labels away, while two
    differently-named money fields state the separation in the shape itself."""
    start: datetime
    end: datetime | None = None
    status: Literal["ok", "error"] = "ok"

    @model_validator(mode="after")
    def _saved_cost_is_non_negative_money(self) -> "SpanData":
        """Both saved-cost totals are counterfactual MONEY, so both share money's domain.

        `SpanData` carries no provenance field — the two provenances are two differently-named
        fields precisely so they cannot be summed — so only the amount domain is checked here.
        """
        for name in ("cache_saved_cost_usd", "cache_saved_cost_archive_usd"):
            amount = getattr(self, name)
            if amount is not None and (not amount.is_finite() or amount < 0):
                raise ValueError(f"{name} must be a finite non-negative amount, got {amount!r}")
        return self


class CostUsageData(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True, use_attribute_docstrings=True, title="Cost / usage"
    )

    scope: Literal["self", "subtree"]
    """``self`` = this node only (authoritative); ``subtree`` = self + Σ descendants."""
    provider: str = Field(
        validation_alias="gen_ai.provider.name",
        serialization_alias="gen_ai.provider.name",
    )
    model: str = Field(
        validation_alias="gen_ai.response.model",
        serialization_alias="gen_ai.response.model",
    )
    pricing_version: str
    usage: TokenUsage
    cost: CostBreakdown


class HeartbeatData(BaseModel):
    pass


class ResultArtifact(BaseModel):
    """Claim ticket for a result too large to ride the stream inline (OME-892).

    The node parks the full result as a content-addressed file and emits this reference
    instead; the client redeems it over HTTP (`GET /artifacts/{id}`) and verifies
    `size_bytes` + `sha256` before trusting the bytes.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    id: str = Field(pattern=r"^[0-9a-f]{64}$")
    """Content address: the lowercase sha256 hex of the UTF-8 body, which is also the
    fetch path segment. The pattern is the path-traversal guard — an id that validates
    can never name anything outside a flat artifact directory."""
    size_bytes: int = Field(ge=1)
    """Exact UTF-8 byte count of the complete body — the first integrity check."""
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    """Digest of the complete body — the second integrity check, kept as its own field so
    `id` may change addressing scheme without changing what the client verifies."""


class ResultData(BaseModel):
    """The run's final result: a complete inline `body`, or an `artifact` claim ticket.

    INVARIANT: exactly one of `body` / `artifact` is set. A body you can see is complete
    and trustworthy; an artifact means the complete result is one HTTP GET away
    (`GET /artifacts/{id}`, verified against the ticket's size and sha256). The
    truncate-and-still-succeed path this replaces (GitHub #642) is unrepresentable.
    """

    body: str | None = None
    media_type: str | None = None
    # WHY exclude_if and not exclude_none on the codec: `media_type: null` was on the wire
    # before OME-892, so dropping every null would change frames old clients already parse.
    # Omitting only an absent `artifact` keeps inline result frames byte-identical to
    # pre-OME-892 — the ticket appears on the wire only when one is actually issued. (A
    # wrap model_serializer would do the same but erases the model's JSON schema, which
    # the Engine's OpenAPI docs gate rejects.)
    artifact: ResultArtifact | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def _exactly_one_of_body_or_artifact(self) -> "ResultData":
        if (self.body is None) == (self.artifact is None):
            raise ValueError("exactly one of body or artifact must be set")
        return self


class TerminatedData(BaseModel):
    status: Literal["succeeded", "failed", "stopped", "timed_out"]
    error: ErrorInfo | None = None


class StopData(BaseModel):
    reason: str | None = None


class CachePolicy(BaseModel):
    """Per-run cache intent — whether this run may participate in the gateway's response cache.

    INTENT ONLY. The translation into any gateway's request vocabulary lives in the adapter that
    talks to it, never here: this module ships to SDK users, so a change to some server's body
    shape must not edit a file they install.

    INVARIANT — the field set is CLOSED, and `extra="forbid"` is what closes it. The gateway this
    protocol is consumed against accepts exactly one cache-control key; an unrecognised one there
    does not degrade to "ignored", it makes the whole request BYPASS the cache, silently and even
    alongside an otherwise valid opt-in. So a caller inventing `no_store` must fail HERE, loudly,
    rather than have it forwarded and pay for it on every call with nothing raised anywhere.
    """

    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)

    participate: bool | None = None
    """`None` means NOT STATED, which is not the same as `False`.

    Absent must stay distinguishable from an explicit opt-out: the precedence rule between the
    HTTP and frame carriers can only prefer a stated policy over silence if silence has its own
    value, and collapsing the two would make opting out unexpressible."""
    max_age: int | None = None
    """Caller's freshness bound in seconds, parsed from `Cache-Control: max-age=<n>`.

    url4-INTERNAL — never sent upstream. It is preserved rather than collapsed at the parsing
    edge so the value survives to the point where an entry's age can be compared against it; the
    gateway neither accepts a bound nor reports an age today, so it degrades to an opt-out."""


class AttachData(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    from_sequence: int | None = Field(default=None, ge=1)
    cache: CachePolicy | None = None
    """Cache intent for the run this attach opens. `None` means the frame DID NOT DECLARE one —
    not "off". Optional because this is a live wire type: every client already in flight sends an
    attach frame without it."""


class ErrorData(BaseModel):
    code: str
    message: str
    ref_id: str | None = None
