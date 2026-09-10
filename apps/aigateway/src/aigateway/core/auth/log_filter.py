from __future__ import annotations

import logging
import re
from typing import Any, cast


class RedactProvisioningTokenFilter(logging.Filter):
    _HEADER_NAME = "x-aigw-provisioning-token"
    _PATTERN = re.compile(
        r"(X-Aigw-Provisioning-Token(?:\s*[:=]\s*|\s+[\"']))([^\s\"',}]+)",
        re.IGNORECASE,
    )
    _RAW_HEADER_PATTERN = re.compile(
        r"(b?[\"']x-aigw-provisioning-token[\"']\s*,\s*b?[\"'])([^\"']+)",
        re.IGNORECASE,
    )

    @classmethod
    def _redact(cls, value: str) -> str:
        redacted = cls._PATTERN.sub(r"\1[REDACTED]", value)
        return cls._RAW_HEADER_PATTERN.sub(r"\1[REDACTED]", redacted)

    @classmethod
    def _is_header_key(cls, value: object) -> bool:
        if isinstance(value, bytes):
            value = value.decode("latin-1")
        if not isinstance(value, str):
            return False
        return value.lower() == cls._HEADER_NAME

    @staticmethod
    def _redacted_like(value: object) -> object:
        return b"[REDACTED]" if isinstance(value, bytes) else "[REDACTED]"

    @classmethod
    def _redact_obj(cls, value: object) -> object:
        if isinstance(value, str):
            return cls._redact(value)
        if isinstance(value, bytes):
            redacted = cls._redact(value.decode("latin-1"))
            return redacted.encode("latin-1")
        if isinstance(value, tuple):
            if len(value) == 2 and cls._is_header_key(value[0]):
                return (value[0], cls._redacted_like(value[1]))
            return tuple(cls._redact_obj(item) for item in value)
        if isinstance(value, list):
            if len(value) == 2 and cls._is_header_key(value[0]):
                return [value[0], cls._redacted_like(value[1])]
            return [cls._redact_obj(item) for item in value]
        if isinstance(value, dict):
            return {
                key: cls._redacted_like(item) if cls._is_header_key(key) else cls._redact_obj(item)
                for key, item in value.items()
            }
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        redacted_rendered = self._redact(rendered)
        if redacted_rendered != rendered and record.name != "uvicorn.access":
            record.msg = redacted_rendered
            record.args = ()
            return True

        record.msg = self._redact_obj(record.msg)
        record.args = cast(Any, self._redact_obj(record.args))
        return True


_REDACTION_INSTALLED = "_aigw_provisioning_token_redaction"


def factory_chain_has(factory: object, flag: str) -> bool:
    """Is `flag` set anywhere in this record-factory wrapper chain — not just on top?

    INVARIANT: idempotence must be about the CHAIN, never about the outermost factory.

    Two installers now share `logging.setLogRecordFactory` — this module's redaction and
    `aigateway.call_context`'s correlation id (OME-938) — and each wraps whatever it finds.
    A top-only check means each installer sees the OTHER's wrapper, concludes it has not run,
    and wraps again. Every interleaved pair then adds two layers, and since `create_app`
    installs both, a process that builds many apps (the test suite builds thousands) grows the
    chain until creating ONE log record overflows the stack — surfacing as
    `RecursionError: maximum recursion depth exceeded` at fixture setup, nowhere near anything
    that looks like logging.

    WHY this lives in the security module rather than beside the newer installer: `core` must
    not import from the app root, and this is where the first factory has always been. `seen`
    guards a cycle a third party could introduce — without it a malformed chain would hang
    instead of raising.
    """
    seen: set[int] = set()
    while factory is not None and id(factory) not in seen:
        seen.add(id(factory))
        if getattr(factory, flag, False):
            return True
        factory = getattr(factory, "__wrapped__", None)
    return False


def install_provisioning_token_redaction() -> None:
    """Install process-wide redaction for records from any logger/handler path.

    AIDEV-NOTE (OME-938): the idempotence guard walks the wrapper CHAIN, not just the outermost
    factory. This module no longer owns `setLogRecordFactory` alone — `call_context` installs a
    correlation-id factory too — and a top-only check means each installer sees the other's
    wrapper, concludes it has not run, and wraps again. Every interleaved pair added two layers
    until creating one log record overflowed the stack. See `call_context.factory_chain_has`.
    """
    current_factory = logging.getLogRecordFactory()
    if factory_chain_has(current_factory, _REDACTION_INSTALLED):
        return

    redactor = RedactProvisioningTokenFilter()

    def redacting_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current_factory(*args, **kwargs)
        redactor.filter(record)
        return record

    setattr(redacting_factory, _REDACTION_INSTALLED, True)
    setattr(redacting_factory, "__wrapped__", current_factory)
    logging.setLogRecordFactory(redacting_factory)
