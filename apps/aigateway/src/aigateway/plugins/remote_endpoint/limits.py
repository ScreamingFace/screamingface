"""A classifier target's `limits` table: validated at startup, published on its catalog row.

# FEATURE: Router Recipe extension Unit 5.1 (contract C7) — an operator writes the bounds a
# qualified classifier holds; the Gateway enforces exactly them on every request and answer.
# INVARIANT: every value is a TOML integer in its range, never a boolean or a float; a breach fails
# startup with the location and the rule, never the value.
# WHY the choice ranges: they are the C16 rows for candidates, labels, descriptions and
# instructions, so no qualified target accepts what a Router could never send.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aigateway.core.classification_input import LIMITS_CONTRACT

_MAX_INT = 2_147_483_647
_Count = Annotated[int, Field(ge=1, le=_MAX_INT)]


class _LimitsDoc(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TextLimitsDoc(_LimitsDoc):
    """The optional table of an `hf-text-classification-v1` target: the three text keys."""

    max_labels: _Count
    max_label_bytes: _Count
    max_text_chars: _Count


class ChoiceLimitsDoc(_LimitsDoc):
    """The required table of a `systemone-choice-v1` target: all six keys, in the C7 ranges."""

    max_labels: Annotated[int, Field(ge=1, le=32)]
    max_label_bytes: Annotated[int, Field(ge=1, le=64)]
    max_text_chars: _Count
    max_options: Annotated[int, Field(ge=1, le=32)]
    max_description_chars: Annotated[int, Field(ge=1, le=1024)]
    max_instructions_chars: Annotated[int, Field(ge=1, le=4096)]

    @model_validator(mode="after")
    def _labels_cover_options(self) -> ChoiceLimitsDoc:
        # INVARIANT: an answer may return every option it was offered.
        if self.max_labels < self.max_options:
            raise ValueError("max_labels must be at least max_options")
        return self


@dataclass(frozen=True, slots=True)
class ClassifierLimits:
    max_labels: int
    max_label_bytes: int
    max_text_chars: int
    max_options: int | None = None
    max_description_chars: int | None = None
    max_instructions_chars: int | None = None

    @classmethod
    def of(cls, doc: TextLimitsDoc | ChoiceLimitsDoc) -> ClassifierLimits:
        return cls(**doc.model_dump())

    def row(self) -> dict[str, str | int]:
        """The catalog row's `limits`: the configured values under the contract's name."""
        values = {f.name: getattr(self, f.name) for f in fields(self)}
        return {"contract": LIMITS_CONTRACT, **{k: v for k, v in values.items() if v is not None}}
