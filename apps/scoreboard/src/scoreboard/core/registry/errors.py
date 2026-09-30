"""Errors of the system registry.

FEATURE: OME-1307 (E14). Each class carries the stable `code` that SB-submit and SB-grants put in
the coded error body (D7 X-8). The HTTP status in each comment is the mapping those units apply.

INVARIANT: the core holds no HTTP knowledge; it names a code, never a status.
"""

from __future__ import annotations

from typing import ClassVar


class RegistryError(Exception):
    code: ClassVar[str]


class InvalidSystemName(RegistryError):  # SB-submit -> 422
    code = "invalid_system_name"

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule  # empty | ascii | length | slash | pattern
        self.message = message


class SystemNameTaken(RegistryError):  # -> 409
    code = "system_name_taken"

    def __init__(self, name: str, suggestion: str) -> None:
        super().__init__(f"system name {name!r} is taken; try {suggestion!r}")
        self.name = name
        self.suggestion = suggestion


class NotSystemOwner(RegistryError):  # -> 403
    code = "not_system_owner"

    def __init__(self, name: str) -> None:
        super().__init__(f"you do not own the system {name!r}")
        self.name = name


class SystemNotFound(RegistryError):  # -> 404
    code = "system_not_found"

    def __init__(self, name: str) -> None:
        super().__init__(f"no system is named {name!r}")
        self.name = name


class InvalidUrl4(RegistryError):  # -> 422
    code = "invalid_url4"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Url4TooLarge(RegistryError):  # -> 422 (D7 X-22)
    code = "url4_too_large"

    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"url4 expression is {size} characters; the limit is {limit}")
        self.size = size  # characters
        self.limit = limit  # characters


class InvalidPin(RegistryError):  # SB-grants -> 422
    code = "invalid_replay_pin"

    def __init__(self, pin: str, message: str) -> None:
        super().__init__(f"invalid replay pin {pin!r}: {message}")
        self.pin = pin
        self.message = message


class PinNotFound(RegistryError):  # SB-grants -> 404
    code = "replay_pin_not_found"

    def __init__(self, pin: str) -> None:
        super().__init__(f"replay pin {pin!r} names no system revision")
        self.pin = pin


class RegistryConflict(RegistryError):  # -> 409, retry
    """A write lost a race twice. The caller may retry the request."""

    code = "registry_conflict"


class RegistryWriteConflict(Exception):
    """Raised by a SystemRepository adapter when a unique constraint rejects a write.

    Not a RegistryError: the service catches it and never lets it escape.
    """
