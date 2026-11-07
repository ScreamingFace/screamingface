"""Source observation fields shared by external-result import and read contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, BeforeValidator, StringConstraints


def _reject_control_characters(value: object) -> object:
    if isinstance(value, str) and any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("provenance text must not contain control characters")
    return value


class BaselineObservation(BaseModel):
    # WHY: nullable for old imports; do not infer a source's metric or read date
    # from the board definition or the time we happened to import its score.
    metric_name: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
            BeforeValidator(_reject_control_characters),
        ]
        | None
    ) = None
    observed_at: AwareDatetime | None = None


class BaselineProvenance(BaselineObservation):
    # INVARIANT: attribution is import/storage-only. Never inherit this type in
    # a public read DTO: baselines are shared even on private boards.
    # A future manual-entry endpoint must obtain this from its authenticated actor.
    attached_by: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
            BeforeValidator(_reject_control_characters),
        ]
        | None
    ) = None
