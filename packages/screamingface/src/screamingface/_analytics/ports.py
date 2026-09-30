"""Small data-only contracts; core never imports persistence or HTTP adapters."""

from dataclasses import dataclass
from typing import Literal, Protocol

type Choice = Literal["unknown", "accepted", "declined"]
type Event = dict[str, str]


@dataclass(frozen=True)
class Consent:
    choice: Choice = "unknown"
    installation_id: str | None = None


class ConsentStore(Protocol):
    def read(self) -> Consent: ...


class AnalyticsSink(Protocol):
    def emit(self, event: Event) -> None: ...

    def clear(self) -> None: ...
