"""Structured client advisories shared by headless and rich presentation adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type NoticeSeverity = Literal["info", "warning"]

_SEVERITIES = frozenset({"info", "warning"})


@dataclass(frozen=True, slots=True)
class ClientNotice:
    """One successful-operation advisory with stable identity and display copy."""

    code: str
    severity: NoticeSeverity
    title: str
    body: str

    def __post_init__(self) -> None:
        for name in ("code", "title", "body"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"Client notice {name} must be a string")
            selected = value.strip()
            if not selected:
                raise ValueError(f"Client notice {name} must not be empty")
            object.__setattr__(self, name, selected)
        if not isinstance(self.severity, str):
            raise TypeError("Client notice severity must be a string")
        if self.severity not in _SEVERITIES:
            raise ValueError("Client notice severity must be 'info' or 'warning'")

    @property
    def message(self) -> str:
        """Plain-text rendering for environments without a rich notice surface."""
        return f"{self.title}. {self.body}"


PARTIAL_SUBMISSION_NOTICE = ClientNotice(
    code="partial_submission",
    severity="warning",
    title="Partial submission",
    # WHY no claim about publication: the advisory is emitted before the POST, so a failed
    # write must not have already told the researcher their score is on the board.
    body=(
        "This score is based on fewer benchmark cases and is not directly comparable "
        "with a full-run score."
    ),
)


__all__: list[str] = []
