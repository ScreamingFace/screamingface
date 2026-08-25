"""The recorded-exchange data model every replay backend shares (OME-961).

Mental model: a *tape* is the cassette — an ordered set of request→response exchanges
captured from (or authored for) the AI Gateway's ``/v1/chat/completions`` surface, plus
the provenance that says where the cassette came from. The cache-seeded gateway plays a
tape back through the real cache table; the OME-962 FakeGateway will play the same model
back through an in-process stub. Neither side imports the other — this module is the
shared vocabulary.

Stages of a tape's life, in execution order:

1. **Author/record** — a generation tool writes a JSON document (``TAPE_SCHEMA``) whose
   ``provenance.authored`` flag says honestly whether a human made the rows up
   (``True``) or a real run recorded them (``False``). There is no default: a tape that
   does not state its origin does not load.
2. **Read** — ``load_tape`` validates the WHOLE document up front (pydantic,
   ``extra="forbid"``): a stale or hand-mangled fixture fails at load time with a field
   path, never later as a mysterious replay miss.
3. **Replay** — a backend looks exchanges up by ``NormalizedRequest`` — the identity
   triple (provider, model, fingerprint) that makes two requests "the same call". The
   fingerprint is the gateway's own global cache ``key_hash`` (sha256 over the closed
   canonical key material), so tape identity and cache identity can never disagree.

INVARIANT: ``response.body`` is the provider payload as RAW bytes (base64 in the JSON
file). The gateway serves cached payloads byte-identical (OME-951 invariant 4), and the
tape must not launder them through a decode/re-encode round trip either.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Literal, Protocol, runtime_checkable

from pydantic import (
    Base64Bytes,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

TAPE_SCHEMA: Final = "screamingface.replay-tape.v1"

_SHA256_HEX = r"^[0-9a-f]{64}$"


class _Strict(BaseModel):
    """Validation-on-read base: unknown fields are refused, values are frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NormalizedRequest(_Strict):
    """The identity of one model call — what makes a replay request "the same".

    ``fingerprint`` is the gateway's global cache ``key_hash``: sha256 over the closed
    canonical material (provider, models, messages, keyed parameters, provider
    projection, revision constants). It is computed by the gateway's own
    ``build_global_cache_key`` — never hand-hashed — so a tape row and the live cache
    row for the same call carry the same 64 hex characters.
    """

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    fingerprint: str = Field(pattern=_SHA256_HEX)


class ExchangeRequest(_Strict):
    """The wire request as the engine sends it to the gateway."""

    method: Literal["POST"] = "POST"
    path: str = Field(min_length=1)
    body: dict[str, object]


class ExchangeResponse(_Strict):
    """The stored provider answer. ``body`` is raw bytes, exactly as the wire had them."""

    status: int = Field(ge=100, le=599)
    media_type: str = "application/json"
    body: Base64Bytes = Field(alias="body_b64")


class Provenance(_Strict):
    """Where this tape came from — the metadata R11's staleness checks hang on.

    ``expression_sha`` is sha256 (hex) of the rendered url4 expression the recording
    ran; ``engine_sha`` names the engine commit that rendered it; ``run_ref`` points at
    the recording run (or names the authoring tool). ``authored`` has NO default on
    purpose: a fixture must say out loud whether it is synthetic.
    """

    board: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    expression_sha: str = Field(pattern=_SHA256_HEX)
    engine_sha: str = Field(min_length=1)
    recorded_at: str = Field(min_length=1)
    run_ref: str = Field(min_length=1)
    authored: bool


class RecordedExchange(_Strict):
    """One request→response pair: identity, wire request, raw response."""

    normalized: NormalizedRequest
    request: ExchangeRequest
    response: ExchangeResponse


class TapeDocument(_Strict):
    """The on-disk shape of a tape file."""

    schema_: str = Field(alias="schema")
    provenance: Provenance
    exchanges: tuple[RecordedExchange, ...]

    @field_validator("schema_")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != TAPE_SCHEMA:
            raise ValueError(f"unknown tape schema: {value!r} (expected {TAPE_SCHEMA!r})")
        return value

    @model_validator(mode="after")
    def _no_duplicate_identities(self) -> TapeDocument:
        # WHY at load: an index keyed on identity would silently keep the LAST
        # duplicate, letting row ORDER decide what replays. Ambiguity fails here.
        seen: set[NormalizedRequest] = set()
        for exchange in self.exchanges:
            identity = exchange.normalized
            if identity in seen:
                raise ValueError(
                    f"duplicate exchange identity: {identity.provider} {identity.model} "
                    f"fingerprint {identity.fingerprint[:12]}… — a tape must answer each "
                    f"call exactly one way"
                )
            seen.add(identity)
        return self


@runtime_checkable
class Tape(Protocol):
    """What a replay backend needs from a tape: provenance, the rows, and lookup."""

    @property
    def provenance(self) -> Provenance: ...

    def exchanges(self) -> Sequence[RecordedExchange]: ...

    def lookup(self, normalized: NormalizedRequest) -> RecordedExchange | None: ...


class LoadedTape:
    """A validated tape file, indexed by normalized identity for O(1) lookup."""

    def __init__(self, document: TapeDocument) -> None:
        self._document = document
        self._by_identity = {exchange.normalized: exchange for exchange in document.exchanges}

    @property
    def provenance(self) -> Provenance:
        return self._document.provenance

    def exchanges(self) -> Sequence[RecordedExchange]:
        return self._document.exchanges

    def lookup(self, normalized: NormalizedRequest) -> RecordedExchange | None:
        return self._by_identity.get(normalized)


def load_tape(path: Path) -> LoadedTape:
    """Read + validate one tape file; any shape problem raises ``ValueError`` at load.

    Args:
        path: a ``*.tape.json`` document in the ``TAPE_SCHEMA`` shape.

    Returns:
        The validated tape, ready for identity lookups.

    Raises:
        ValueError: the file is not valid JSON, not this schema, or any field fails
            validation (including a missing ``authored`` flag) — loud, at read time.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"tape file {path.name} is not valid JSON: {exc}") from exc
    try:
        document = TapeDocument.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"tape file {path.name} failed validation: {exc}") from exc
    return LoadedTape(document)
