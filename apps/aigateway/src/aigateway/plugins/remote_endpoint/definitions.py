"""Schema v1 of the remote-endpoint config, validated into immutable definitions.

# FEATURE: hosted BYOM — an operator approves an endpoint once; the gateway serves it as an
# ordinary provider whose keys live in the existing per-account Connections.
# INVARIANT: this module never reads a file. Any reader (TOML today) hands it a plain document, so
# the same definitions and grants come out whatever the source format is.
# INVARIANT: a refusal names the location and the rule, never the offending value, so a rejected
# private origin or account list does not land in startup logs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SCHEMA_VERSION = 1
CHAT_CONTRACT = "openai-chat-basic-v1"

_ENDPOINT_ID = re.compile(r"^byom_[0-9a-f]{32}$")
_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
_HOSTNAME = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})+$")
_ALIAS = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
_SEGMENT = r"[A-Za-z0-9._~-]+"
_REQUEST_PATH = re.compile(rf"^/(?:{_SEGMENT}(?:/{_SEGMENT})*)?$")
_UPSTREAM_MODEL = re.compile(r"^[\x21-\x7e]{1,256}$")
_URL_TEXT = re.compile(r"^[\x21-\x7e]+$")


class RemoteEndpointConfigError(ValueError):
    """The remote-endpoint config is unusable; the message carries locations and rules only."""


@dataclass(frozen=True, slots=True)
class ChatTarget:
    alias: str
    request_path: str
    upstream_model: str
    task: Literal["chat"] = "chat"
    contract: Literal["openai-chat-basic-v1"] = CHAT_CONTRACT


@dataclass(frozen=True, slots=True)
class EndpointDefinition:
    """What an instance needs to call its endpoint — and deliberately nothing about who may."""

    id: str
    display_name: str
    origin: str
    validation_target: str
    targets: tuple[ChatTarget, ...]

    def target(self, alias: str) -> ChatTarget | None:
        return next((target for target in self.targets if target.alias == alias), None)

    def model_id(self, target: ChatTarget) -> str:
        return f"{self.id}/{target.alias}"


@dataclass(frozen=True, slots=True)
class EndpointGrant:
    enabled: bool
    account_ids: frozenset[str]


@dataclass(frozen=True)
class RemoteEndpointConfig:
    endpoints: tuple[EndpointDefinition, ...]
    grants: Mapping[str, EndpointGrant]


class _Strict(BaseModel):
    # WHY strict: a TOML document already carries real booleans and integers, so a string where a
    # boolean belongs is an operator mistake to report, not a value to coerce.
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class _ChatTargetDoc(_Strict):
    alias: str
    task: Literal["chat"]
    contract: Literal["openai-chat-basic-v1"]
    request_path: str
    upstream_model: str

    @field_validator("alias")
    @classmethod
    def _alias(cls, value: str) -> str:
        if not _ALIAS.fullmatch(value):
            raise ValueError("must be 1-64 lowercase letters, digits, '.', '_' or '-'")
        return value

    @field_validator("request_path")
    @classmethod
    def _request_path(cls, value: str) -> str:
        # INVARIANT: a fixed same-origin path — never absolute, network-path, templated or
        # dot-segmented — so the origin alone decides where a key is sent.
        segments = value.split("/")[1:]
        if not _REQUEST_PATH.fullmatch(value) or any(s in {".", ".."} for s in segments):
            raise ValueError("must be a fixed absolute path of unreserved characters")
        return value

    @field_validator("upstream_model")
    @classmethod
    def _upstream_model(cls, value: str) -> str:
        if not _UPSTREAM_MODEL.fullmatch(value):
            raise ValueError("must be 1-256 printable ASCII characters without spaces")
        return value


class _EndpointDoc(_Strict):
    id: str
    display_name: str
    enabled: bool
    origin: str
    allowed_account_ids: list[str]
    validation_target: str
    targets: list[_ChatTargetDoc] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _ENDPOINT_ID.fullmatch(value):
            raise ValueError("must be 'byom_' followed by 32 lowercase hex digits")
        return value

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, value: str) -> str:
        if not (0 < len(value) <= 128 and value == value.strip() and value.isprintable()):
            raise ValueError("must be 1-128 printable characters without edge spaces")
        return value

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        return _canonical_origin(value)

    @field_validator("allowed_account_ids")
    @classmethod
    def _accounts(cls, value: list[str]) -> list[str]:
        if not all(_is_canonical_uuid(item) for item in value):
            raise ValueError("must list canonical lowercase account UUIDs")
        if len(set(value)) != len(value):
            raise ValueError("must not repeat an account")
        return value

    @model_validator(mode="after")
    def _targets_resolve(self) -> _EndpointDoc:
        aliases = [target.alias for target in self.targets]
        if len(set(aliases)) != len(aliases):
            raise ValueError("duplicate target alias")
        if self.validation_target not in aliases:
            raise ValueError("validation_target must name a declared target alias")
        return self


class _Document(_Strict):
    schema_version: int
    endpoints: list[_EndpointDoc] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _version(cls, value: int) -> int:
        if value != SCHEMA_VERSION:
            raise ValueError(f"must be {SCHEMA_VERSION}")
        return value

    @model_validator(mode="after")
    def _unique_ids(self) -> _Document:
        ids = [endpoint.id for endpoint in self.endpoints]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate endpoint id")
        return self


def parse_remote_endpoint_config(document: Any) -> RemoteEndpointConfig:
    """Validate a whole config document; nothing is returned unless every endpoint is valid."""
    if not isinstance(document, Mapping):
        raise RemoteEndpointConfigError("remote endpoint config document must be a table")
    try:
        parsed = _Document.model_validate(document)
    except ValidationError as exc:
        raise RemoteEndpointConfigError(_sanitized(exc)) from None
    return RemoteEndpointConfig(
        endpoints=tuple(_definition(endpoint) for endpoint in parsed.endpoints),
        grants=MappingProxyType(
            {
                endpoint.id: EndpointGrant(
                    enabled=endpoint.enabled, account_ids=frozenset(endpoint.allowed_account_ids)
                )
                for endpoint in parsed.endpoints
            }
        ),
    )


def _definition(endpoint: _EndpointDoc) -> EndpointDefinition:
    return EndpointDefinition(
        id=endpoint.id,
        display_name=endpoint.display_name,
        origin=endpoint.origin,
        validation_target=endpoint.validation_target,
        targets=tuple(
            ChatTarget(
                alias=target.alias,
                request_path=target.request_path,
                upstream_model=target.upstream_model,
            )
            for target in endpoint.targets
        ),
    )


def _canonical_origin(value: str) -> str:
    """`https://<dns-name>` exactly; an explicit `:443` is the one accepted spelling variant."""
    if not _URL_TEXT.fullmatch(value) or not value.startswith("https://"):
        raise ValueError("must be an https origin of printable ASCII")
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError:
        raise ValueError("must use port 443") from None
    if port not in (None, 443):
        raise ValueError("must use port 443")
    if "@" in parts.netloc or parts.path or "?" in value or "#" in value:
        raise ValueError("must not carry userinfo, path, query or fragment")
    host = parts.hostname or ""
    # WHY compare the netloc: `hostname` is lowercased and unbracketed, so any other spelling
    # (upper case, an IP literal in brackets) differs from it and is refused rather than rewritten.
    if parts.netloc not in {host, f"{host}:443"}:
        raise ValueError("must use a canonical lowercase hostname")
    if not _HOSTNAME.fullmatch(host) or host.rsplit(".", 1)[-1].isdigit():
        raise ValueError("must use a fully qualified DNS hostname, not an address")
    return f"https://{host}"


def _is_canonical_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _sanitized(exc: ValidationError) -> str:
    problems = [
        f"{'.'.join(str(part) for part in error['loc']) or '<document>'}: {error['msg']}"
        for error in exc.errors(include_url=False, include_input=False, include_context=False)
    ]
    return "remote endpoint config is invalid: " + "; ".join(problems)
