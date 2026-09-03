from __future__ import annotations

import json
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

# INVARIANT: run_cost_usd mirrors DECIMAL(12, 6) exactly — six decimal places and
# six integer digits, so 0.000001 through 999999.999999.
COST_QUANTUM = Decimal("0.000001")
COST_CEILING = Decimal("999999.999999")
# INVARIANT: the one canonical zero — POSITIVE, at full scale. Decimal("-0") is
# equal to this, so equality can never detect the difference; only is_signed() can.
_ZERO_COST = Decimal("0").quantize(COST_QUANTUM)


def _validate_run_cost(value: Decimal) -> Decimal:
    """Reject a cost that cannot be stored; normalize every cost that can.

    Only two things are actually unstorable and therefore rejected: a negative or
    non-finite value, and one above the column ceiling. Everything else is
    normalized rather than refused, because a 422 here discards the WHOLE
    submission — the score result along with the cost.

    WHY, in the order the rules apply:
      * float noise on a representable value (0.07 * 3 == 0.21000000000000002) is
        quantized to 0.210000, losing nothing. Rejecting it would discard valid
        scores the moment a client starts summing per-call float costs;
      * zero is canonicalized to POSITIVE zero, since -0.0 otherwise serves the
        string "-0.000000" (spec 2.6);
      * a positive cost below one quantum rounds AWAY from zero, never to zero
        (spec 2.2's second revision, and the D5 invariant it protects).

    AIDEV-NOTE: the bounds cannot move to Field(max_digits=..., decimal_places=...).
    Those constraints run BEFORE this validator, so they would reject the very
    values it exists to normalize.
    """
    # ge=0 on the field already rejects negatives, and NaN fails that comparison,
    # but +Infinity passes it — and quantize() raises InvalidOperation rather than
    # returning a value, so non-finites have to go before any arithmetic.
    if not value.is_finite():
        raise ValueError("run_cost_usd must be a finite decimal number")
    # INVARIANT: the ceiling is checked BEFORE quantizing. quantize() raises on an
    # absurd exponent (1e30), which would surface as a 500 rather than a 422 —
    # the exact failure this validator exists to close.
    #
    # AIDEV-NOTE: there is deliberately no ceiling re-check after quantizing.
    # quantize is monotone and COST_CEILING sits exactly on the 6dp grid, so
    # anything that would round up past it is already rejected here. An earlier
    # draft had that branch plus a test comment claiming to exercise it; both were
    # wrong — the value never reached it.
    if value > COST_CEILING:
        raise ValueError(f"run_cost_usd must not exceed {COST_CEILING}")
    if value == 0:
        # INVARIANT: zero is always POSITIVE zero. -0.0 passes ge=0 (-0 == 0) and
        # quantize preserves the sign, so it used to serve the string "-0.000000":
        # a negative dollar figure, and backend-dependent besides (Postgres
        # normalizes sign-zero, SQLite keeps it). A client summing signed per-call
        # figures produces -0.0 from 0.0 * -1, so this is received, not theoretical.
        return _ZERO_COST
    # INVARIANT (D5): a positive cost is NEVER stored as zero — that would publish a
    # run which cost real money as free and hand it the cheapest slot on the Pareto
    # frontier. Clamping to one quantum expresses exactly that: it rounds away from
    # zero, so the figure is never understated (it cannot buy frontier position) and
    # the submission is never discarded, which rejecting did — the score result
    # went with it. Overstates by at most one quantum. See spec 2.2's 2nd revision.
    return max(value.quantize(COST_QUANTUM, rounding=ROUND_HALF_UP), COST_QUANTUM)


def _serialize_run_cost(value: Decimal | None) -> str | None:
    """Pin the JSON form to exactly 6 decimal places.

    WHY: Pydantic emits Decimal as a JSON *string* carrying whatever scale and
    notation the value happens to have — "12.5" from SQLite, "12.500000" from a
    padded Postgres DECIMAL, "1E+3" for a cost submitted as 1e3. That is a
    backend-dependent wire format, and it breaks the feature this field exists
    for: OME-770's frontier and cheapest-run stat are computed in JavaScript,
    where `<` on strings is lexicographic ("10" < "9.5" is true), so an unpinned
    scale makes $1000 rank cheaper than $3.50 and renders 1E+3 in the Cost column.
    Quantizing on read also normalizes the scale of rows written before the
    validator existed, and normalizes sign-zero — without which a stored
    "-0.000000" (reachable by raw SQL) would still serve a negative figure.

    It does NOT repair a row outside DECIMAL(12, 6): quantize RAISES on those
    rather than normalizing, which is why the row loop guards the conversion
    (spec 2.7).

    AIDEV-NOTE: a fixed-scale string does not make that hazard impossible —
    "1000.000000" < "3.500000" is still true. It forces consumers to convert
    explicitly (parseFloat), which is reviewable in a way a bare `<` on two
    numbers is not. Pass 2 must convert before comparing, and its frontier tests
    must cover values of differing integer width. See spec 2.4.
    """
    if value is None:
        return None
    if value == 0:
        return f"{_ZERO_COST:f}"
    # INVARIANT (D5) on the READ side too: a positive cost must never be published as
    # zero. The validator clamps on the way in, but a row written by raw SQL — or
    # before the validator existed — can hold a sub-quantum positive, and quantizing
    # alone would render it "0.000000", i.e. a run that cost money shown as free.
    # Found in review: stored Decimal("4E-7") serialized to "0.000000".
    quantized = max(value.quantize(COST_QUANTUM, rounding=ROUND_HALF_UP), COST_QUANTUM)
    return f"{quantized:f}"


# INVARIANT: the ONE definition of the cost's wire form, shared by every read DTO.
# The RankedLeaderboardEntry / HistorySubmission / ScoreSchema duplication has
# already caused two defects (a 500 and a silent omission), so the serializer is
# attached to a type rather than repeated per class. `when_used="json"` is
# deliberate: _ranked_entry splats entry.model_dump() in PYTHON mode and must keep
# receiving a Decimal, not a string.
RunCostUsd = Annotated[
    Decimal | None,
    PlainSerializer(_serialize_run_cost, return_type=str | None, when_used="json"),
]

# INVARIANT: a baseline's metadata is operator-supplied (via the import CLI, not a
# public HTTP endpoint) but still bounded, so one bad import can't make
# GET /v1/leaderboard/{id} fail to serialize for every consumer (found in PR review).
_METADATA_MAX_DEPTH = 4
_METADATA_MAX_BYTES = 4096


def _metadata_depth(value: object, current: int = 0) -> int:
    if isinstance(value, dict):
        return max((_metadata_depth(v, current + 1) for v in value.values()), default=current)
    if isinstance(value, list):
        return max((_metadata_depth(v, current + 1) for v in value), default=current)
    return current


def _validate_bounded_metadata(value: dict[str, Any] | None) -> dict[str, Any] | None:
    # WHY: shared by both the import DTO and the read schema — a bad row must never
    # reach storage in the first place, but bounding the read side too means the
    # invariant holds regardless of how a row got into the database (found in PR
    # review: metadata was previously bounded on import only).
    if value is None:
        return value
    if _metadata_depth(value) > _METADATA_MAX_DEPTH:
        raise ValueError(f"metadata must not be nested past {_METADATA_MAX_DEPTH} levels deep")
    if len(json.dumps(value)) > _METADATA_MAX_BYTES:
        raise ValueError(f"metadata must serialize to at most {_METADATA_MAX_BYTES} bytes")
    return value


def _publish_submitter(value: str | None) -> str | None:
    """Publish the local part of an email, never the domain.

    WHY: since OME-404 this field holds the mesh-verified address from the Cloudflare
    Access identity header, and the read API is PUBLIC and unauthenticated — a
    harvester can pull every submitter's address straight out of
    `GET /v1/leaderboard/{id}`. Stripping in the portal would have looked correct
    while leaving the JSON exposed, so the trim lives here, where every consumer
    (portal, SDK notebook view, anything future) is served from one place.

    INVARIANT: this is a SERIALIZER, not a validator. The stored value keeps its
    domain so OpenMined can still contact a submitter and audit which verified
    identity produced a score. Do NOT move this onto ScoreSubmission — that carries
    the value inbound, and trimming there would write the truncated form to the
    database irreversibly.

    AIDEV-NOTE: this is a stopgap, not privacy. `filip.boltuzic` still names a
    person, `first.last@domain` is trivially reconstructed, and
    trask@openmined.org and trask@gmail.com both render `trask` — two testers on
    different domains become indistinguishable on a board that attributes credit.
    A real username field is the fix; OME-772 records that none exists (OME-834).
    """
    if value is None:
        return value
    # WHY whitespace is REMOVED rather than treated as a signal: three review passes
    # tried to read intent from whitespace, and each fixed one half while breaking
    # the other.
    #   pass 1 gated on `@` alone     -> " @openmined.org" published " ", a BLANK
    #                                    submitter, and the SDK's _text rejects
    #                                    blank-after-strip, raising LeaderboardError
    #                                    for the WHOLE board off one poisoned row;
    #   pass 2 rejected ALL whitespace -> "trask@openmined.org " (one trailing space)
    #                                    published the full domain — the exposure this
    #                                    function exists to close, beaten by a space;
    #   pass 3 stripped only the ends  -> "me @ openmined.org" still published whole,
    #                                    and a harvester just normalises it back.
    #
    # The owner settled the question underneath all three (2026-08-15): this field is
    # an IDENTITY, not a display name. So the test is simply "is this an address?" —
    # whitespace is formatting noise wherever it sits, not evidence of intent.
    #
    # INVARIANT: the blank-local hazard stays closed. With every space gone, an empty
    # local part is empty rather than blank, so "  @openmined.org  " falls through to
    # the untouched original instead of publishing "  ".
    #
    # AIDEV-NOTE: this is still a read-time GUESS about a value nothing constrains on
    # the way in — the reason it took four passes. OME-840 closes it properly by
    # validating the address on the write path; when that lands this can stop guessing.
    candidate = "".join(value.split())
    if "@" not in candidate:
        return value
    local, _, domain = candidate.rpartition("@")
    # A public address needs a non-empty local part and a DOTTED domain. That dot is
    # what keeps free text safe: "Team A @ OpenMined" collapses to "TeamA@OpenMined",
    # whose domain is a word rather than a host, so it passes through whole. Same for
    # the handle form, `user@github`.
    return local if local and "." in domain else value


# INVARIANT: the ONE definition of how a submitter reaches a client, shared by every
# read DTO so the four cannot drift. `when_used="json"` is deliberate — _ranked_entry
# splats entry.model_dump() in PYTHON mode and must keep receiving the stored value.
SubmittedBy = Annotated[
    str | None,
    PlainSerializer(_publish_submitter, return_type=str | None, when_used="json"),
]


def _publish_authors(value: list[str] | None) -> list[str] | None:
    """Apply the submitter privacy boundary to every credited author.

    INVARIANT: one trimming rule, delegated. `submitted_by` and `authors` must degrade
    identically, or the same address is redacted on one field and published on the other.

    AIDEV-NOTE: `or author` below is a TYPE narrowing, not a fallback — read as a fallback it looks
    like it publishes a raw address whenever the trimmer balks, which is the opposite of what this
    function is for. It cannot: `_publish_submitter` returns None only for a None input, and these
    elements are typed `str`. For anything that is not a dotted-domain address the trimmer already
    returns the full value on purpose (see its docstring), so there is nothing here to rescue.
    """
    if value is None:
        return None
    return [_publish_submitter(author) or author for author in value]


# INVARIANT: author addresses are full in Python mode (staff export) and local-part-only in
# public JSON. Keeping the serializer on one shared type prevents the three read DTOs from
# drifting and exposing domains on only one endpoint.
Authors = Annotated[
    list[str] | None,
    PlainSerializer(_publish_authors, return_type=list[str] | None, when_used="json"),
]

# Deliberately syntax-only. This does not resolve a domain, check deliverability, require an
# allowlisted co-author, or normalize the address. The dotted domain also guarantees the public
# serializer above can apply the same local-part publication rule as submitted_by.
AuthorEmail = Annotated[
    str,
    Field(
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$",
    ),
]


class ClientInfo(BaseModel):
    """Optional client metadata for a score submission."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    version: str | None = None
    platform: str | None = None


class FieldErrorDetail(BaseModel):
    """Field-specific HTTP error detail."""

    model_config = ConfigDict(extra="forbid")

    field: str
    message: str


class FieldErrorResponse(BaseModel):
    """HTTP error response for errors tied to a request field."""

    model_config = ConfigDict(extra="forbid")

    detail: FieldErrorDetail


class MessageErrorResponse(BaseModel):
    """HTTP error response with a flat detail message."""

    model_config = ConfigDict(extra="forbid")

    detail: str


class ScoreSubmission(BaseModel):
    """Input DTO for score ingestion."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    benchmark_id: str
    # WHY optional: the deployed Client sends this nested in `metadata` rather than as a typed
    # field, so the store resolves either shape (_resolve_benchmark_revision). Requiring it
    # here would 422 every submission in the field; see OME-775 D5.
    benchmark_revision: str | None = None
    spec_id: str
    url4_expression: Annotated[str, Field(max_length=32_000)]
    submitted_by: str | None = None
    # None means the client did not specify a credit line; reads then derive [submitted_by].
    # An explicit list is exact — the submitter is not auto-added (OME-1051 D1).
    authors: Annotated[list[AuthorEmail], Field(min_length=1, max_length=10)] | None = None
    # the exact primary score the Engine Benchmark produced — any
    # finite number, higher is better
    score: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    total_questions: int
    correct_questions: int | None = None
    ran_with_providers: list[str]
    ran_at_local: datetime | None = None
    # Nested client metadata, matching the SF "Publish to Leaderboard" wire shape
    # (D-SCORE-006). Persisted onto the flat client_* columns by the store.
    client: ClientInfo | None = None
    metadata: dict[str, Any] | None = None
    # INVARIANT (OME-822): every direct submission reports a cost. A fully
    # cache-served run genuinely costing nothing is represented by 0; omission or
    # null is a client bug and is rejected by this non-nullable required field.
    # Database and read DTOs deliberately remain nullable because imported and
    # legacy rows can still have no known cost. Decimal, not float — this is money.
    # INVARIANT: the request contract mirrors the column exactly — DECIMAL(12, 6).
    # `ge=0` alone let three failures through, each reproduced live:
    #   0.0000009 -> accepted (201) and silently stored as 0.000001, publishing a
    #     figure the submitter never sent;
    #   1000000   -> accepted on SQLite, but seven integer digits overflow
    #     DECIMAL(12, 6) on Postgres, so it passed locally and would fail in
    #     production;
    #   1e30      -> reached the database and returned HTTP 500 instead of 422.
    #
    # AIDEV-NOTE: the bounds are enforced by the validator below, NOT by
    # Field(max_digits=..., decimal_places=...). Those constraints run BEFORE an
    # after-validator, so they would reject the float-noise values that spec 2.2
    # requires us to quantize and accept. `ge=0` stays here (it also rejects NaN,
    # which fails the comparison); allow_inf_nan=False stops +Infinity, which
    # would pass ge=0 and then raise inside quantize().
    run_cost_usd: Decimal = Field(ge=0, allow_inf_nan=False)

    @field_validator("run_cost_usd")
    @classmethod
    def validate_run_cost(cls, value: Decimal) -> Decimal:
        return _validate_run_cost(value)

    @field_validator("url4_expression")
    @classmethod
    def validate_url4_expression(cls, value: str) -> str:
        if not value:
            raise ValueError("url4_expression must be non-empty")
        return value

    @field_validator("benchmark_id", "spec_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if not value:
            raise ValueError("identifier fields must be non-empty")
        return value

    @field_validator("total_questions")
    @classmethod
    def validate_total_questions(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("total_questions must be positive")
        return value

    @field_validator("correct_questions")
    @classmethod
    def validate_correct_questions(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("correct_questions must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_questions(self) -> ScoreSubmission:
        if self.correct_questions is not None and self.correct_questions > self.total_questions:
            raise ValueError("correct_questions cannot exceed total_questions")
        return self


# INVARIANT (OME-894): the only two visibilities there are. A private benchmark stays LISTED in
# the public catalogue and marked (owner decision, 2026-08-24) — participants must be able to find
# it to enter, and the catalogue carries no scores, so listing it leaks nothing.
Visibility = Literal["public", "private"]


class BenchmarkSchema(BaseModel):
    """Read DTO for benchmarks."""

    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    description: str | None
    # Short editorial line for the portal catalogue's "Focus" column (OME-874). Null when the
    # benchmark ships without one.
    focus: str | None
    dataset_url: str | None
    # WHY exposed: a client comparing its run against the board needs to know which revision
    # the board is registered at, so it can tell a real score gap from an incomparable one.
    revision: str | None
    # WHY exposed (OME-1056): a client that ran a subset needs to see the canonical size to
    # understand why its score is absent from the ranking. None means the board declares no
    # canonical scope and therefore ranks everything.
    case_count: int | None
    visibility: Visibility
    created_at: datetime


class ScoreSchema(BaseModel):
    """Read DTO for a score."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    version: int
    benchmark_id: str
    # WHY: the Engine benchmark revision this score was measured against, resolved from either
    # wire shape by the store. Null for imported baselines and rows predating OME-775.
    benchmark_revision: str | None
    spec_id: str
    url4_expression: str
    submitted_by: SubmittedBy
    authors: Authors = None
    submitted_at: datetime
    score: float
    total_questions: int
    # WHY nullable: only binary-graded benchmarks ever had a correctness count; rows
    # submitted after OME-866 carry None unless the client sent one.
    correct_questions: int | None
    ran_with_providers: list[str]
    ran_at_local: datetime | None
    client_name: str | None
    client_version: str | None
    client_platform: str | None
    verified_by_screamingface: bool
    metadata: dict[str, Any] | None
    # FEATURE: OME-323 — manual open/closed correction; None defers to the
    # classification registry. Operator-only, never set via ScoreSubmission.
    openness_override: Literal["open", "closed"] | None = None
    run_cost_usd: RunCostUsd


class LeaderboardEntry(BaseModel):
    """Read DTO for a leaderboard row before route rank assignment."""

    model_config = ConfigDict(extra="forbid")

    spec_id: str
    # WHY exposed: the board partitions ranking on this, so a client seeing two rows for one
    # spec needs the revision to know why they are not competing (OME-775). Null for rows that
    # predate the column and for imported baselines.
    benchmark_revision: str | None
    score: float
    total_questions: int
    ran_with_providers: list[str]
    submitted_at: datetime
    submitted_by: SubmittedBy
    authors: Authors = None
    verified_by_screamingface: bool
    url4_expression: str
    # Self-reported and unverifiable: re-running a submission tells us what *we*
    # paid, not what the submitter paid. Exposed so the board can show it, but it
    # must be presented with its provenance and never as a verified figure.
    run_cost_usd: RunCostUsd


class LeaderboardStoreEntry(LeaderboardEntry):
    """Store-only leaderboard row carrying identity across independent projections."""

    source_id: str = Field(exclude=True)


class BaselineSchema(BaseModel):
    """Read DTO for an imported single-model baseline ('line to beat')."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    benchmark_id: str
    model_name: str
    score: float
    source: str
    source_url: str | None
    imported_at: datetime
    metadata: dict[str, Any] | None
    # FEATURE: OME-323 — manual open/closed correction, mirrors ScoreSchema's field.
    openness_override: Literal["open", "closed"] | None = None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_bounded_metadata(value)


class FrontierPoint(BaseModel):
    """One step of the open/closed frontier trend (OME-323, spec §5/§6): the
    running-best score at the moment it changed, and whether the entry holding
    that position was open or closed."""

    model_config = ConfigDict(extra="forbid")

    at: datetime
    score: float
    openness: Literal["open", "closed"]
    # INVARIANT: always "score" — a Baseline's imported_at isn't a trustworthy
    # real-world timestamp, so it never participates in this walk (spec §6).
    holder: Literal["score"]
    label: str


class FrontierResult(BaseModel):
    """Return type of `compute_frontier` — no `benchmark_id`, since the pure
    function itself has no notion of which benchmark it was called for. The route
    adds that to build the public `FrontierResponse`."""

    model_config = ConfigDict(extra="forbid")

    open_count: int
    closed_count: int
    open_share: float
    current: FrontierPoint | None
    trend: list[FrontierPoint]


class FrontierResponse(BaseModel):
    """Read DTO for GET /v1/leaderboard/{benchmark_id}/frontier (OME-323, spec §5)."""

    model_config = ConfigDict(extra="forbid")

    benchmark_id: str
    open_count: int
    closed_count: int
    open_share: float
    current: FrontierPoint | None
    trend: list[FrontierPoint]


class BaselineImportRow(BaseModel):
    """Input DTO for importing a single-model baseline score (e.g. from LMArena /
    Artificial Analysis). Re-importing the same (benchmark_id, model_name, source)
    updates the existing row rather than duplicating it (see BaselineStore).
    """

    model_config = ConfigDict(extra="forbid")

    benchmark_id: str
    model_name: str
    # WHY: strict + no-inf-nan closes a Pydantic v2 laziness gap where JSON true/false
    # coerce to 1.0/0.0 and numeric strings coerce to float, letting malformed source
    # data silently become a plausible-looking score (found in PR review).
    # INVARIANT (OME-866): benchmark-native — an imported baseline ranks against
    # community entries on ONE board, so its score must be on that benchmark's native
    # scale. Any finite number is storable; there is no universal 0..1 range.
    score: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    source: str
    # WHY: this is returned through the public API and a future client will likely
    # render it as a link — restrict to http(s) so a javascript:/data: URI can't
    # become an XSS vector downstream (found in PR review).
    source_url: Annotated[str, Field(max_length=2048)] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("benchmark_id", "model_name", "source")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if not value:
            raise ValueError("identifier fields must be non-empty")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("source_url must start with http:// or https://")
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_bounded_metadata(value)
