from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationError,
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


def _validate_run_cost(value: Decimal | None) -> Decimal | None:
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
    # OME-822: absent is legal again, but only beside a status saying the amount is
    # unknowable — `ScoreSubmission.validate_cost_matches_its_status` enforces that
    # pairing. There is nothing to normalize here.
    if value is None:
        return None
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

# FEATURE: OME-822 / OME-1251 D4 — whether a submitted cost can be believed as a number.
#
# INVARIANT: a RUN-level vocabulary, NOT the gateway's per-call `DirectCostStatus`. A run is many
# calls; no member of that vocabulary can say "forty priced, three not", which is the common case.
#
#   complete     every component priced — the amount is exact and is stored
#   partial      the amount is not derivable, but cache saved-cost evidence exists, so a real
#                lower bound is known even though the total is not
#   unavailable  not derivable and no cost evidence at all
#
# `partial` and `unavailable` behave identically today — both store a null amount and so leave
# every cost-bearing surface. The distinction is kept because this is a STORED column: if the
# board ever shows a lower bound somewhere, `partial` is the set it applies to, and widening the
# vocabulary later would cost a migration plus another one-directional client rollout.
RunCostStatus = Literal["complete", "partial", "unavailable"]

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

# INVARIANT: counting distinct people must not turn repeated author entries into
# an unbounded public write. This matches the established metadata envelope.
_AUTHORS_MAX_BYTES = 4096
_AUTHORS_MAX_DISTINCT = 10

# FEATURE: OME-1181 — the declared candidate model routes.
#
# WHY a count cap AND a byte cap: 32 routes of 255 characters is still 8 KiB of
# client-controlled text arriving on a public write path. Same reasoning and the
# same envelope as `authors` above and `metadata`.
#
# WHY 32: the live maximum on any board is 4 (a three-member fusion plus its
# synthesizer). A recipe naming 32 distinct models is already implausible, so the
# cap bounds the payload without constraining any real submission.
_MODELS_MAX_ROUTES = 32
_MODELS_MAX_BYTES = 4096

# INVARIANT: this mirrors the Client's own route grammar (`_MODEL_ROUTE_RE` in
# `packages/screamingface/.../_evaluation/candidate.py:429`), anchored. The two ends must agree
# on what a route is, or the Client compiles an expression the board then rejects at submit —
# a failure that would only appear in the field, after a release.
_MODEL_ROUTE_PATTERN = r"^[A-Za-z0-9\-_.~]+(?:/[A-Za-z0-9\-_.~]+)*$"

ModelRoute = Annotated[str, Field(max_length=255, pattern=_MODEL_ROUTE_PATTERN)]


def _author_identity(author: str) -> str:
    """The one comparison identity for author validation and publication."""
    return author.casefold()


def _publish_authors(value: list[str] | None) -> list[str] | None:
    """Publish one unambiguous credit per distinct author.

    INVARIANT: duplicate detection and the submission cap use the same full-address,
    case-insensitive identity. The first submitted spelling and order win, while storage
    remains untouched because this function runs only as a JSON serializer.

    WHY domains appear only for collisions: OME-834's privacy rule remains the default,
    but two distinct people with the same local part cannot both publish as the same name.
    The domain is the minimum already-stored discriminator that makes that row truthful.
    """
    if value is None:
        return None

    distinct: list[tuple[str, str]] = []
    seen: set[str] = set()
    for author in value:
        identity = _author_identity(author)
        if identity not in seen:
            seen.add(identity)
            published = _publish_submitter(author)
            # `author` is non-null, so this is type narrowing rather than a raw-address fallback.
            distinct.append((author, published if published is not None else author))

    local_counts: dict[str, int] = {}
    for _, published in distinct:
        local = published.casefold()
        local_counts[local] = local_counts.get(local, 0) + 1

    return [
        author if local_counts[published.casefold()] > 1 else published
        for author, published in distinct
    ]


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


def _validate_bounded_authors(value: list[str] | None) -> list[str] | None:
    """The author-list bounds, shared by `ScoreSubmission` and `ScoreMetadataPatch`.

    INVARIANT: the cap protects credit cardinality, not raw audit history. The serializer uses this
    exact key when it collapses repeated identities. A PATCH must apply the SAME bounds as a POST,
    so both call this one function.
    """
    if value is None:
        return value
    if len({_author_identity(author) for author in value}) > _AUTHORS_MAX_DISTINCT:
        raise ValueError(f"authors must credit at most {_AUTHORS_MAX_DISTINCT} distinct people")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > _AUTHORS_MAX_BYTES:
        raise ValueError(f"authors must serialize to at most {_AUTHORS_MAX_BYTES} bytes")
    return value


_PAPER_URL_MAX_CHARS = 2048
_PAPER_URL_SCHEMES = frozenset({"http", "https"})


def _validate_paper_url(value: str) -> str:
    """Accept an absolute `http(s)` link with a host, and return it UNCHANGED.

    FEATURE: OME-1307 — this checks the SHAPE of the link, never that the paper exists or that the
    named authors wrote it (out of scope for E14).

    INVARIANT: the string is stored exactly as sent. That is why this is not pydantic's `HttpUrl`,
    which lower-cases the host and appends a slash: a link a researcher pasted must come back as
    they pasted it. The portal still runs every link through `httpUrlOrNull` on read (M21).
    """
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError("paper_url must not contain control characters")
    # WHY any whitespace, anywhere: `urlsplit` quietly strips leading and trailing blanks, so a
    # link with one would validate, be stored as sent, and then not be the URL it looks like.
    if any(char.isspace() for char in value):
        raise ValueError("paper_url must not contain whitespace")
    parts = urlsplit(value)
    if parts.scheme.lower() not in _PAPER_URL_SCHEMES:
        raise ValueError("paper_url must use the http or https scheme")
    if not parts.hostname:
        raise ValueError("paper_url must name a host")
    # WHY refuse user info: a paper link is shown and followed by readers, and
    # `https://trusted.example@evil.test/` reads as the first host while going to the second.
    # `username` is "" (not None) for a bare `@`, so test for None.
    if parts.username is not None or parts.password is not None:
        raise ValueError("paper_url must not contain user info")
    return value


PaperUrl = Annotated[
    str,
    Field(min_length=1, max_length=_PAPER_URL_MAX_CHARS),
    AfterValidator(_validate_paper_url),
]


# FEATURE: OME-1307 — the gateway cache revision label: `cr-` plus 12 lower-case hex characters.
# INVARIANT: the same spelling on the submission, on a recorded reproduction and in the column
# width (`VARCHAR(32)`). Pydantic's pattern is a Rust regex, where `$` matches only at the very end,
# so a label with a trailing newline is refused.
CacheRevision = Annotated[str, Field(pattern=r"^cr-[0-9a-f]{12}$")]
# `complete`: every call of the run is in the cache, so a replay can answer it. `partial`: not.
ReproducibleStatus = Literal["complete", "partial"]
# A 32-bit signed INT, the width of the column. Anything wider would fail on PostgreSQL after
# passing here, so it is refused as a 422 instead of reaching the database.
AnswerSeed = Annotated[int, Field(ge=-(2**31), le=2**31 - 1)]


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


class CodedErrorDetail(BaseModel):
    """A machine-readable refusal: a stable `code` plus a human `message`."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class CodedErrorResponse(BaseModel):
    """HTTP error response whose detail carries a stable code (for example `not_score_owner`)."""

    model_config = ConfigDict(extra="forbid")

    detail: CodedErrorDetail


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
    authors: Annotated[list[AuthorEmail], Field(min_length=1)] | None = None
    # FEATURE: OME-1307 — a link to the paper behind this result. None means "not given", so a
    # same-owner resubmit without it keeps the stored link (an older SDK never sends it).
    # AIDEV-NOTE: deliberately absent from `_content_hash`, like `authors`: it is display-only.
    paper_url: PaperUrl | None = None
    # FEATURE: OME-1181 — the candidate's DECLARED model routes, as composed in the recipe.
    #
    # WHY optional: this field deploys BEFORE the Client that populates it (OME-1179
    # constraint 1). `extra="forbid"` above means the rollout is one-directional — a Client
    # sending an unknown field to an older board gets a 422 — so the board must tolerate its
    # absence or the deploy order reverses and every in-field submission breaks.
    #
    # INVARIANT: `None` and `[]` are different. None is "the client did not send them"; an
    # empty list would claim the run used no models at all, which no real submission can mean
    # (`CandidateResult.models` is required and non-empty at the Client) and which would store
    # an unclassifiable row that looks populated.
    #
    # AIDEV-NOTE: deliberately absent from `_content_hash`. These routes are a richer
    # projection of what `url4_expression` already carries, and that IS hashed — see the
    # invariant on `_content_hash` in store.py before changing this.
    models: Annotated[list[ModelRoute], Field(min_length=1)] | None = None
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
    # GOAL (OME-822): every direct submission reports a cost. A fully cache-served
    # run genuinely costing nothing is represented by 0; a client that can determine
    # its cost and stays silent is a client bug.
    #
    # NOT ENFORCED YET — this is the EXPAND phase. The field below is optional and
    # nullable, and a submission omitting BOTH it and `run_cost_status` is accepted.
    # `OME-1258` is what turns the goal into a 422, once `OME-1252` is live in the SDK
    # version submitters actually run. See the note on `run_cost_status` below.
    #
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
    #
    # OME-822/OME-1251 D1: OPTIONAL. An absent amount is legal beside a status that says it is
    # unknowable, and the model validator below enforces that pairing in both directions.
    #
    # AIDEV-NOTE: omitting BOTH this and `run_cost_status` is ACCEPTED, and stores an unlabelled
    # row indistinguishable from a legacy one. Read `validate_cost_matches_its_status` below — it
    # returns early on a null status. An earlier revision of this comment claimed the pair was
    # rejected; that was never true on this head, and
    # `test_a_submission_with_neither_amount_nor_status_stays_unlabelled` pins the real
    # behaviour. `OME-1258` is what starts refusing it.
    run_cost_usd: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    # INVARIANT (OME-1251 D4): a RUN-level vocabulary, deliberately not the gateway's per-call
    # `DirectCostStatus`. A run has many calls, and no member of that vocabulary can express
    # "forty priced, three not" — the common case and the one that matters.
    #
    # OPTIONAL, and that is the EXPAND half of a deliberate expand/contract split (OME-1258).
    #
    # WHY not required, which is what OME-822 asks for: the deployed SDK sends `run_cost_usd`
    # and no status (`packages/screamingface/.../leaderboards.py:445` on main). A required field
    # here 422s EVERY live submission the moment this deploys — including payloads carrying a
    # perfectly good cost — and the client cannot ship first either, because an older board is
    # `extra="forbid"` and rejects the unknown field. That is a deadlock, and this PR's own
    # documented deploy order could not work (review of PR #841, 2026-09-22).
    #
    # `OME-1258` flips it to required once `OME-1252` is released and confirmed live in the SDK
    # version submitters actually run. Until then silence is accepted, which is precisely the
    # thing OME-822 exists to stop — so the flip is a ticket, not a maybe.
    run_cost_status: RunCostStatus | None = None
    # FEATURE: OME-1325 / OME-1251 D5 — what this run's cache hits would have cost.
    #
    # WHY a second field and not a correction to `run_cost_usd`: the amount above is what the run
    # SPENT, and a cache hit costs nothing upstream. The cost to REPRODUCE is
    # `run_cost_usd + cache_saved_cost_usd`, derived at the point of use. D5 keeps the parts
    # separate so the board can store real data now and choose the basis later; a pre-summed
    # number would be silently low until `OME-1287` lands, with no way to tell how low.
    #
    # INVARIANT: PROVIDER-AUTHORED money only. The archive-matched saving travels in its own field
    # below (`OME-1251` D7), so the board keeps the provenance and can label it later.
    #
    # INVARIANT: ONE-WAY pairing only. `partial` beside a null here stays ACCEPTED: a `partial`
    # run has a saved-cost sum by definition, but `OME-1252` ships the status and NOT this field,
    # and `OME-1326` adds it later, so between those releases every `partial` submission
    # legitimately lacks it. Refusing that would be the deadlock review found in PR #841 (P1-1).
    #
    # The other direction is refused (`validate_saved_cost_matches_its_status` below):
    # `unavailable` means NO cost evidence, so any saving beside it is a contradiction. Older
    # clients never send this field, so nothing deployed can trip it (review of PR #1055, P2).
    cache_saved_cost_usd: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    # FEATURE: OME-1382 / OME-1251 D7 (owner, 2026-10-02, reverses D3) — what this run's cache hits
    # would have cost, priced from the archive (another call of the same model and kind). Summed
    # with the spend and the reported saving at the point of use; never sent pre-summed.
    cache_saved_cost_archive_usd: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    # FEATURE: OME-1307 — which cache version produced this run and whether a replay can answer it.
    #
    # WHY optional: like `paper_url`, these deploy BEFORE the SDK that sends them (`extra="forbid"`
    # makes the rollout one-directional), and the SDK omits each one when it is NULL.
    #
    # INVARIANT: `cache_revision` needs `reproducible` (below). `reproducible` alone is legal: a
    # run with no cacheable call, or calls under two labels, has a status and no single label.
    #
    # AIDEV-NOTE: deliberately absent from `_content_hash`. They describe one execution of a recipe,
    # as the cost fields do, and a resubmit only FILLS them (`_replay_updates`).
    cache_revision: CacheRevision | None = None
    reproducible: ReproducibleStatus | None = None
    answer_seed: AnswerSeed | None = None

    @model_validator(mode="after")
    def validate_cache_revision_has_a_status(self) -> ScoreSubmission:
        """INVARIANT (I1): a label without a status is incoherent, so it is refused."""
        if self.cache_revision is not None and self.reproducible is None:
            raise ValueError("cache_revision requires reproducible")
        return self

    @field_validator("cache_saved_cost_usd", "cache_saved_cost_archive_usd")
    @classmethod
    def validate_cache_saved_cost(cls, value: Decimal | None) -> Decimal | None:
        # Money's domain is already defined once, by the amount this figure sits beside. A second
        # money field with its own rules is how the two drift apart.
        return _validate_run_cost(value)

    @model_validator(mode="after")
    def validate_saved_cost_matches_its_status(self) -> ScoreSubmission:
        """INVARIANT: a saving is cost evidence, so it cannot sit beside `unavailable`.

        Any non-null value, including 0 — not just a positive one. The SDK derives `partial`
        whenever the reported sum is present, so a correct client can never send `unavailable`
        with a saving of any value. The reverse (`partial` without a saving) is deliberately
        allowed for the staged rollout; see the field comment.
        """
        for name in ("cache_saved_cost_usd", "cache_saved_cost_archive_usd"):
            if self.run_cost_status == "unavailable" and getattr(self, name) is not None:
                raise ValueError(
                    f"{name} must be absent when run_cost_status is 'unavailable': "
                    "a saving is cost evidence"
                )
        return self

    @model_validator(mode="after")
    def validate_cost_matches_its_status(self) -> ScoreSubmission:
        """INVARIANT: when a status IS given, `complete` if and only if an amount is present.

        A contract admitting two spellings of the same fact gets both, and the board then has to
        guess which one the client meant. `complete` asserts an exact amount, so asserting it
        without one is incoherent; an amount beside a status saying it is unknowable is the same
        incoherence from the other side. Refusing both keeps `run_cost_status` a fact about the
        amount rather than a second opinion on it.

        INVARIANT: an ABSENT status beside an amount resolves to `complete`. That is not a guess
        — an amount IS the claim the status would make. Resolving here rather than at the store
        means the submission object, the stored row and the response all carry the same fact,
        and it keeps pre-OME-1252 clients producing correctly labelled rows instead of a
        population the flip in `OME-1258` would have to clean up afterwards.

        INVARIANT (OME-1325): an ABSENT status beside only a SAVING resolves to `partial`. A saving
        is cost evidence, so the row is not legacy-shaped, and `partial` is exactly what the SDK
        derives for an unpriced run with a reported saving. Leaving it null would write a row that
        claims to predate cost reporting while carrying a field only new clients send — and replay
        could never repair it, since the snapshot fill needs all three stored fields null (review of
        PR #1055, round 2).

        An absent status with NEITHER amount stays absent: that is a legacy-shaped row, and the
        board genuinely does not know whether the client looked. `OME-1258` is what starts
        refusing it.
        """
        if self.run_cost_status is None:
            if self.run_cost_usd is not None:
                self.run_cost_status = "complete"
            elif (
                self.cache_saved_cost_usd is not None
                or self.cache_saved_cost_archive_usd is not None
            ):
                self.run_cost_status = "partial"
            return self
        priced = self.run_cost_status == "complete"
        if priced and self.run_cost_usd is None:
            raise ValueError("run_cost_usd is required when run_cost_status is 'complete'")
        if not priced and self.run_cost_usd is not None:
            raise ValueError(
                f"run_cost_usd must be absent when run_cost_status is {self.run_cost_status!r}"
            )
        return self

    @field_validator("authors")
    @classmethod
    def validate_distinct_authors(cls, value: list[str] | None) -> list[str] | None:
        return _validate_bounded_authors(value)

    @field_validator("models")
    @classmethod
    def validate_bounded_models(cls, value: list[str] | None) -> list[str] | None:
        # INVARIANT: both caps are needed. The route count alone still admits 32 maximum-length
        # routes, and the byte cap alone still admits thousands of short ones.
        if value is None:
            return value
        if len(value) > _MODELS_MAX_ROUTES:
            raise ValueError(f"models must name at most {_MODELS_MAX_ROUTES} routes")
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > _MODELS_MAX_BYTES:
            raise ValueError(f"models must serialize to at most {_MODELS_MAX_BYTES} bytes")
        return value

    @field_validator("run_cost_usd")
    @classmethod
    def validate_run_cost(cls, value: Decimal | None) -> Decimal | None:
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


#: The saturation verdict words the Engine serves (OME-1455).
#: INVARIANT: value-for-value identical to the Engine's `SATURATION_VERDICTS` in
#: `benchmarks/provenance.py` and the SDK's in `_catalogue_vocabulary.py`; the Engine's
#: `test_the_saturation_verdicts_are_spelled_the_same_on_both_sides` parses this tuple.
SATURATION_VERDICTS: tuple[str, ...] = ("saturated", "open", "unknown")


class PublishedScoreSchema(BaseModel):
    """One published score on the Benchmark's headline metric, with its source (OME-1455).

    A Human Baseline carries `score` and `source_url`; a Frontier Score adds the `model` and
    the `as_of` month. Both are copied from the Engine catalogue, never computed here.

    WHY ``extra="ignore"``, like the block that holds it: pydantic applies each model's OWN
    rule, so a ``forbid`` here is not overridden by the parent's ``ignore`` — one stray key
    inside a stored score object was the same whole-listing 500 the parent had just been
    changed to prevent (second review round on PR 1236).
    """

    model_config = ConfigDict(extra="ignore")

    score: float
    source_url: str
    model: str | None = None
    as_of: str | None = None


class ProvenanceSchema(BaseModel):
    """The Benchmark Provenance block as the Engine declared it (OME-1455).

    Every field is optional: the Engine serves a key only when the Benchmark declares a value,
    and a Benchmark that declares none-published for a fact serves no key for it either. The
    page omits a missing field rather than printing a dash.

    WHY ``extra="ignore"`` on a READ schema, where every other DTO here forbids: this one is
    built from a stored JSON copy, and a key this build does not declare can sit in that copy
    after a Helm rollback (the seed is a post-upgrade hook, so a rollback never reseeds) or
    after a one-sided edit to the seed's reader. ``forbid`` would turn ONE such row into a
    500 on the whole catalogue listing (review finding on PR 1236). Serve the keys this build
    knows.

    INVARIANT: this is the ONE reader of the block, on both sides of the table. The seed cuts
    the block off a catalogue entry through :meth:`from_stored` and the API read rebuilds the
    DTO from the stored copy through the same method, so there is no second class to drift
    from this one (the seed's own copy, pinned to this by field NAME only, let the nested
    ``forbid`` through — second review round on PR 1236).
    """

    model_config = ConfigDict(extra="ignore")

    paper_url: str | None = None
    authors: str | None = None
    citation: str | None = None
    inspect_contributors: list[str] | None = None
    homepage_url: str | None = None
    harness_url: str | None = None
    license: str | None = None
    license_note: str | None = None
    content_warning: str | None = None
    human_baseline: PublishedScoreSchema | None = None
    frontier_score: PublishedScoreSchema | None = None
    notebook: str | None = None

    @classmethod
    def from_stored(cls, raw: Mapping[str, Any]) -> ProvenanceSchema | None:
        """Read a block key by key, so one bad key costs itself and never the block.

        A key this build does not declare is skipped; a declared key whose value does not
        validate (a score sent as a string, a list sent as a word) is skipped the same way, and
        a key that validates to None is left out. None, not an empty schema, when nothing
        readable remains: an empty block would read as "checked, none", which is a claim
        nobody made. Whole-block validation would instead raise on the first bad key — and the
        catalogue listing maps every row through this, so one row's bad key was a 500 for
        every board (second review round on PR 1236).

        Args:
            raw: the block as served flat on a catalogue entry (extra keys beside it are
                ignored) or as stored in the ``provenance`` column.

        Returns:
            The readable keys as this schema, or None when there are none.
        """
        kept: dict[str, Any] = {}
        for name in cls.model_fields:
            if name not in raw:
                continue
            try:
                checked = cls.model_validate({name: raw[name]})
            except ValidationError:
                continue
            value: Any = getattr(checked, name)
            if value is not None:
                kept[name] = value
        return cls(**kept) if kept else None


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
    # OME-1455: where the Benchmark comes from and the derived saturation verdict, both copied
    # from the Engine catalogue. `provenance` is null when the Engine published no block.
    # `saturation` is the Engine's word ("unknown" is itself a verdict: no frontier score
    # recorded); it is null when this board holds NO verdict — a pre-migration row, an Engine
    # that predates the field, or a value outside the verdict vocabulary, which the seed
    # stores as null rather than invent "unknown" on the Engine's behalf.
    provenance: ProvenanceSchema | None
    saturation: str | None
    visibility: Visibility
    created_at: datetime


class ScoreRankingNotice(BaseModel):
    """Why a successfully persisted score will not enter the current ranking.

    AIDEV-NOTE: "the current ranking", literally. This is for a row that is stored and readable
    but ABSENT FROM THE RANKED BOARD. It is not a general "something about this row is off"
    channel, and widening it to one costs the type its meaning.

    An unpriced run (OME-822, `run_cost_status` of `partial` or `unavailable`) deliberately does
    NOT use this, and `OME-1251` D2's original wording — which said it would — was withdrawn for
    that reason. Such a row DOES rank: its score is known and not in doubt. It is absent only
    from the Pareto frontier and the other surfaces that read cost as a number. Giving it a
    notice here would assert something false about it on every read.

    `run_cost_status` already travels on `ScoreSchema`, so the client is told why its cost is
    missing without a second, worse-shaped carrier. Note also that the two fields below are
    revision-specific and required — a member added for any other reason would have to make
    them optional, which weakens the shape for the one case that does belong here.
    """

    model_config = ConfigDict(extra="forbid")

    code: Literal["benchmark_revision_mismatch"]
    submitted_benchmark_revision: str | None
    registered_benchmark_revision: str


class ScoreSchema(BaseModel):
    """Read DTO for a score and the successful submission receipt."""

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
    # FEATURE: OME-1307 — the paper link and the time `authors` or `paper_url` last changed.
    #
    # INVARIANT: EXCLUDED WHEN ABSENT, for exactly the reason `models` below records. This schema
    # feeds the private JSONL export whose bytes authorize a purge; `"paper_url": null` on every
    # legacy row would change every export saved before these fields existed.
    #
    # INVARIANT: null `metadata_updated_at` means "never edited". Only a CHANGE sets it.
    paper_url: str | None = Field(default=None, exclude_if=lambda value: value is None)
    metadata_updated_at: datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    # FEATURE: OME-1181 — the declared candidate model routes, for classification.
    #
    # INVARIANT: EXCLUDED WHEN ABSENT, like `ranking_notice` below and for the same reason.
    # This schema is NOT internal — it is the response model for `POST /scores` and
    # `GET /scores/{id}`, and it also feeds the private JSONL export, whose exact bytes
    # `purge_private_benchmark.export_sha256` hashes to authorize a destructive purge against
    # an operator-supplied digest. Emitting `"models": null` would change every export saved
    # before this field existed, with no underlying row having changed, so a previously
    # certified export could no longer authorize its own purge (review of PR #922).
    #
    # `models` stays off `LeaderboardEntry`, the ranked-board payload (OME-1179 Q2). That
    # decision recorded this schema as internal, which was wrong; the exclusion below is what
    # actually keeps the absent case off the wire.
    models: list[str] | None = Field(default=None, exclude_if=lambda value: value is None)
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
    # FEATURE: OME-822 / OME-1251 D1 — why this row's cost is absent, when it is.
    #
    # INVARIANT: EXCLUDED WHEN ABSENT, for exactly the reason `models` above records. This schema
    # feeds the private JSONL export whose bytes authorize a purge; emitting
    # `"run_cost_status": null` on every legacy row would change every export saved before this
    # field existed, with no row having changed, and a previously certified export could no
    # longer authorize its own purge.
    #
    # INVARIANT: null here is NOT the same as `unavailable`. Null means the row predates this
    # field — an imported baseline, or a submission from before OME-822. `unavailable` means a
    # client looked and could not determine the cost. Collapsing the two would lose the
    # distinction the Pareto frontier depends on.
    run_cost_status: RunCostStatus | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    # FEATURE: OME-1325 / OME-1251 D5 — what this row's cache hits would have cost.
    #
    # WHY it is exported at all when nothing reads it yet: the private JSONL export is how a
    # board is restored, so a stored-but-unexported column is a column that does not survive a
    # round trip. Phase 2 (`OME-1287`-gated) is what starts RANKING on
    # `run_cost_usd + cache_saved_cost_usd`; the value has to already be in the exports by then.
    #
    # INVARIANT: EXCLUDED WHEN ABSENT, for exactly the reason `models` and `run_cost_status`
    # above record. Emitting `"cache_saved_cost_usd": null` on every legacy row would change
    # every export saved before this field existed, with no row having changed, and a previously
    # certified export could no longer authorize its own purge. That is the `OME-1181` Q2 trap.
    #
    # INVARIANT: null is NOT 0. Null means not reported; 0 means a client looked and the run
    # genuinely saved nothing.
    cache_saved_cost_usd: RunCostUsd = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    # FEATURE: OME-1382 / OME-1251 D7 — the archive-matched saving, as STORED. Excluded when absent
    # for the same export-digest reason as `cache_saved_cost_usd` directly above.
    cache_saved_cost_archive_usd: RunCostUsd = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    # FEATURE: OME-1307 — the cache version of the run. EXCLUDED WHEN ABSENT, for exactly the reason
    # `paper_url` and `models` record: the private JSONL export hashes these bytes to authorise a
    # purge, and no legacy row may gain `"reproducible": null`.
    #
    # INVARIANT: a null `reproducible` means "unknown", never `partial`.
    cache_revision: str | None = Field(default=None, exclude_if=lambda value: value is None)
    reproducible: ReproducibleStatus | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    answer_seed: int | None = Field(default=None, exclude_if=lambda value: value is None)
    # FEATURE: OME-1307 — recorded reproductions, DERIVED on read (never stored on `scores`). Only
    # `GET /v1/scores/{id}` fills them; every other path that builds this DTO leaves the default.
    #
    # INVARIANT: EXCLUDED WHEN ZERO or null, for the reason `paper_url` records. An absent count
    # reads as 0 (K8), so a row with no reproductions serializes as it did before the field: the
    # private JSONL export (whose bytes authorise a purge) and the PATCH and resubmit responses,
    # which never compute the count, do not change.
    reproduction_count: int = Field(default=0, exclude_if=lambda value: value == 0)
    last_reproduced_at: datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    # WHY exclude None at the MODEL serializer: ScoreSchema also feeds private JSONL exports and
    # GET responses. A submit-time fact must not add `ranking_notice: null` to either, while a
    # mismatch supplied by POST remains visible and documented in the shared schema.
    ranking_notice: ScoreRankingNotice | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class ScoreMetadataPatch(BaseModel):
    """Body of `PATCH /v1/scores/{id}`: the two fields a submitter may edit after the fact.

    FEATURE: OME-1307 — an ABSENT key means "unchanged" and `paper_url: null` means "clear the
    link"; `model_fields_set` is what tells them apart, so the route must not dump the model with
    defaults. `authors: null` is refused: to go back to the derived credit line, send
    `authors: [submitted_by]`.
    """

    model_config = ConfigDict(extra="forbid")

    authors: Annotated[list[AuthorEmail], Field(min_length=1)] | None = None
    paper_url: PaperUrl | None = None

    @field_validator("authors", mode="before")
    @classmethod
    def refuse_null_authors(cls, value: object) -> object:
        # A FIELD validator (not the model one below) so the 422 points at `body.authors`. It runs
        # only when the key is present, which is exactly the case to refuse.
        if value is None:
            raise ValueError("authors cannot be null; send a list, or omit the key")
        return value

    @field_validator("authors")
    @classmethod
    def validate_distinct_authors(cls, value: list[str] | None) -> list[str] | None:
        return _validate_bounded_authors(value)

    @model_validator(mode="after")
    def validate_one_known_key(self) -> ScoreMetadataPatch:
        if not self.model_fields_set:
            raise ValueError("send at least one of: authors, paper_url")
        return self


class ScoreMetadataEventSchema(BaseModel):
    """One row of a score's edit log, for its owner only (`GET /v1/scores/{id}/metadata-events`).

    INVARIANT: `authors` here is a plain list, NOT the `Authors` type. That type publishes local
    parts only, which is right for a public read and wrong here: the owner reads the full addresses
    they added or removed. The route is owner-only and `no-store` for that reason.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    edited_by: str
    edited_at: datetime
    source: Literal["patch", "resubmit"]
    old_authors: list[str] | None
    new_authors: list[str] | None
    old_paper_url: str | None
    new_paper_url: str | None


class ReproductionSubmission(BaseModel):
    """Body of `POST /v1/scores/{id}/reproductions`: one exact replay a verified identity records.

    FEATURE: OME-1307 — `score`, `total_questions` and `cache_revision` are compared with the stored
    score by the route (a mismatch is `not_exact`); this DTO only checks their shape.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: Annotated[str, Field(min_length=1, max_length=128)]
    score: float
    total_questions: int
    cache_revision: CacheRevision | None = None
    client: ClientInfo


class ReproductionSchema(BaseModel):
    """One recorded reproduction, as the recorder receives it."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    score_id: UUID
    reproduced_by: str
    reproduced_at: datetime
    run_id: str
    cache_revision: str | None
    client_version: str | None


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
    """One step of the open-share trend (OME-1145, D-L): the frontier's open share at the END of a
    UTC day, emitted only when it differs from the previous point. Replaces OME-323's score-holder
    walk.

    INVARIANT (D-U, amended in review round 1): daily sampling, not per submission. Changes within
    one day collapse to that day's end state, so a share that moves and moves back on the same day
    shows neither move. `at` is the day's last event (a submission or an enrichment), a real
    time. See `frontier.py`'s `FrontierReplay` for why: per-submission replay was quadratic on a
    public endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    # The last event (submission or enrichment) of the day this point summarises.
    at: datetime
    # None when that frontier held nothing classifiable (D-S).
    open_share: float | None
    open_count: int
    closed_count: int


class FrontierResult(BaseModel):
    """What `compute_frontier_openness` returns: the open share of the cost/score Pareto frontier.

    FEATURE: OME-1145 — the "N% open" card. Every field describes ONE population, the full-board
    Pareto frontier the ranked table marks (D-L), so the card cannot contradict the table.

    INVARIANT (D-S): `open_share` is None, never 0.0, when nothing was measured: no frontier
    (`frontier_available` false, D12), an empty one, or one holding only unidentified entries.
    0% asserts a closed frontier; nothing measured asserts nothing.
    """

    model_config = ConfigDict(extra="forbid")

    # False on a board with no registered revision: the table makes no frontier claim there
    # (D12), so neither does the card.
    frontier_available: bool
    # Entries on the frontier, before the unidentified ones are set aside.
    frontier_size: int
    open_count: int
    closed_count: int
    # Frontier entries with no `models` (submitted before OME-1180), excluded from the share.
    unidentified_count: int
    # D4: distinct routes the registry did not recognise, sorted, capped (D-T).
    unrecognised_models: list[str]
    open_share: float | None
    trend: list[FrontierPoint]


class FrontierResponse(FrontierResult):
    """Read DTO for GET /v1/leaderboard/{benchmark_id}/frontier (OME-1145)."""

    benchmark_id: str


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
