"""The checks every Run wire decoder shares: the Runs answers (`runs`), the Run's event frames
(`run_follow`) and a Candidate's record (`run_record`) (E5 P2 spec §4.1 to §4.3).

INVARIANT: one copy of each rule, so a fix to one (a bool taken for an int, an empty string
taken for text) reaches all three; each decoder fails with its own message, and always as
`engine_contract_error`, which cancels nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from re import Pattern
from typing import NoReturn, cast

from screamingface.errors import ExecutionError


class WireChecks:
    """The shared checks, failing with ``message``."""

    def __init__(self, message: str) -> None:
        self._message = message

    def malformed(self) -> NoReturn:
        raise ExecutionError(self._message, code="engine_contract_error", permanent=True)

    def object(self, value: object) -> Mapping[str, object]:
        if not isinstance(value, dict):
            self.malformed()
        return cast(Mapping[str, object], value)

    @staticmethod
    def optional[T](value: object, decode: Callable[[object], T]) -> T | None:
        return None if value is None else decode(value)

    def text(self, value: object) -> str:
        if not isinstance(value, str) or not value:
            self.malformed()
        return value

    @staticmethod
    def is_int(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    def count(self, value: object) -> int:
        """A whole number from 0 up; never a bool, which is an `int` to Python."""
        if not self.is_int(value) or cast(int, value) < 0:
            self.malformed()
        return cast(int, value)

    def matching(self, value: object, pattern: Pattern[str]) -> str:
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            self.malformed()
        return value

    def time(self, value: object) -> datetime:
        try:
            moment = datetime.fromisoformat(self.text(value))
        except ValueError:
            self.malformed()
        if moment.tzinfo is None:
            self.malformed()
        return moment

    def decimal(self, value: object) -> Decimal:
        """Money as the wire writes it: a fixed-point string, never a JSON float."""
        if not isinstance(value, str):
            self.malformed()
        try:
            amount = Decimal(value)
        except InvalidOperation:
            self.malformed()
        if not amount.is_finite():
            self.malformed()
        return amount


__all__ = ["WireChecks"]
