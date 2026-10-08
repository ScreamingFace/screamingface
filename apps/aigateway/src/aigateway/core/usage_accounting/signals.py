"""Request-local binding for provider transport observation signals."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol

__all__ = ["AccountingSignalTarget", "active_collector", "bound_collector"]


class AccountingSignalTarget(Protocol):
    """The signal receiver used by transport hooks without taxonomy dependencies."""

    def mark_incomplete(self) -> None: ...

    def on_redirect_observed(self, request: object, *, target: str | None = None) -> None: ...

    def on_response_completed(
        self,
        request: object,
        *,
        status: object,
        raw_evidence: dict[str, Any] | None,
        body_completed: bool = True,
        evidence_complete: bool = True,
    ) -> None: ...

    def on_send_admitted(self, request: object) -> None: ...


_ACTIVE: ContextVar[AccountingSignalTarget | None] = ContextVar(
    "aigw_usage_accounting_signal_target", default=None
)


def active_collector() -> AccountingSignalTarget | None:
    """Return the signal target for the request running on this context."""
    return _ACTIVE.get()


@contextmanager
def bound_collector(target: AccountingSignalTarget) -> Iterator[AccountingSignalTarget]:
    """Bind one signal target and restore the previous target on exit."""
    token = _ACTIVE.set(target)
    try:
        yield target
    finally:
        _ACTIVE.reset(token)
