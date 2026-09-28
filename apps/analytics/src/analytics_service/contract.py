"""Strict privacy allowlist; no product objects cross this boundary."""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Identifier = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
]
Duration = Literal["under_1s", "1_10s", "10_60s", "1_10m", "10_60m", "over_60m"]


class InvalidPayload(ValueError):
    """Expose only a code, never validation inputs."""


class EventTooLarge(InvalidPayload):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Event(StrictModel):
    event_id: Identifier
    operation_id: Identifier
    session_id: Identifier
    persistent_id: Identifier | None = None
    id_scope: Literal["installation", "browser", "session"]
    event: Literal[
        "evaluation_started", "evaluation_finished", "submission_started", "submission_finished"
    ]
    timestamp: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")]
    sdk_version: Annotated[
        str, Field(max_length=64, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.+-]*)$")
    ]
    surface: Literal["python_sdk", "cli"]
    interface: Literal["sync", "async"]
    origin: Literal["colab", "local_jupyter", "python", "cli"]
    usage_mode: Literal["byok", "hosted"]
    workflow: Literal["recipe", "raw_url4", "submission"]
    outcome: Literal["succeeded", "completed_with_failures", "failed", "cancelled"] | None = None
    duration_bucket: Duration | None = None

    @field_validator("timestamp")
    @classmethod
    def valid_date(cls, value: str) -> str:
        datetime.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def combinations(self) -> Self:
        # INVARIANT: omission differs from explicit null for forbidden fields.
        if self.id_scope == "session":
            if "persistent_id" in self.model_fields_set:
                raise ValueError("invalid scope")
        elif self.persistent_id is None:
            raise ValueError("missing persistent ID")
        self.check_operation()
        return self

    def check_operation(self) -> None:
        if self.event.startswith("submission") != (self.workflow == "submission"):
            raise ValueError("invalid workflow")
        if self.event.endswith("started"):
            if self.model_fields_set & {"outcome", "duration_bucket"}:
                raise ValueError("start has terminal fields")
        elif self.outcome is None or self.duration_bucket is None:
            raise ValueError("missing terminal fields")
        if self.workflow == "submission" and self.outcome == "completed_with_failures":
            raise ValueError("invalid submission outcome")


class Batch(StrictModel):
    schema_version: Literal[1]
    consent_version: Literal["1"]
    consent_granted: Literal[True]
    events: Annotated[list[Event], Field(min_length=1, max_length=20)]

    @field_validator("schema_version", "consent_granted", mode="before")
    @classmethod
    def no_boolean_integer_coercion(cls, value: object, info) -> object:
        expected = bool if info.field_name == "consent_granted" else int
        if type(value) is not expected:
            raise ValueError("invalid type")
        return value


def parse_batch(data: object, *, now: datetime | None = None) -> Batch:
    check_event_sizes(data)
    try:
        batch = Batch.model_validate(data)
    except ValidationError:
        raise InvalidPayload("invalid_payload") from None
    instant = now or datetime.now(UTC)
    unique: dict[str, Event] = {}
    for event in batch.events:
        timestamp = datetime.fromisoformat(event.timestamp)
        if not instant - timedelta(hours=24) <= timestamp <= instant + timedelta(minutes=5):
            raise InvalidPayload("invalid_timestamp")
        if event.event_id in unique and unique[event.event_id] != event:
            raise InvalidPayload("conflicting_event")
        unique[event.event_id] = event
    return batch.model_copy(update={"events": list(unique.values())})


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidPayload("duplicate_key")
        result[key] = value
    return result


def decode_body(body: bytes) -> object:
    return json.loads(body, object_pairs_hook=reject_duplicate_keys)


def check_event_sizes(data: object) -> None:
    if isinstance(data, dict) and isinstance(data.get("events"), list):
        for event in data["events"]:
            if len(json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode()) > 4096:
                raise EventTooLarge("event_too_large")
