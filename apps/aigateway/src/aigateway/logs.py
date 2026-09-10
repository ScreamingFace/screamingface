"""Log configuration for the aigateway app logger tree.

WHY this module exists: ``uvicorn.run()`` installs handlers for the
``uvicorn*`` loggers ONLY and leaves the root logger with none. Every
``aigateway.*`` record therefore fell through to ``logging.lastResort``,
which emits at WARNING — so the gateway's INFO lines were discarded in every
deployment that has ever run. Found via OME-889: the per-provider concurrency
limit line (the operator's only proof of which limit is in force) never
appeared in the stack log.

Same defect, same cure as the Engine's ``screamingface_engine/logs.py`` —
mirrored rather than shared because apps must not import each other's
internals (a 30-line stdlib module does not justify a shared package).
"""

from __future__ import annotations

import logging
import os
from typing import TextIO

from aigateway.call_context import record_call_id

APP_LOGGER = "aigateway"
LEVEL_ENV = "AIGW_LOG_LEVEL"
DEFAULT_LEVEL = "INFO"

# Matches uvicorn's own column so a deployment's logs read as one stream rather than two.
# `%(call_context)s` is filled by `CallContextFilter` (OME-938); `defaults=` keeps a record that
# reaches the handler WITHOUT passing the filter — a foreign handler's, a library's — from
# raising KeyError in the formatter and taking the log line with it.
_FORMAT = "%(levelname)s:     %(name)s %(call_context)s%(message)s"


class CallContextFilter(logging.Filter):
    """Render the bound request's correlation ids onto every record that passes through.

    FEATURE (OME-938): `call_context.install_call_context_injection` puts `gateway_call_id` on
    the RECORD, but `_FORMAT` is plain text — an attribute nobody prints is not correlation.
    This filter is what turns the attribute into output, exactly as the Engine's
    `RunContextFilter` does for `topic`/`trace_id`.

    `key=value` and not free prose: it is the shape the Engine already emits, and the shape a
    collector can be taught to parse into a real attribute. Unbound (boot, shutdown, tests) it
    renders nothing at all, so those lines stay byte-identical to before.

    AIDEV-NOTE: `OME-1120` adds `trace_id` here, beside the call id — that is why this renders a
    LIST of parts rather than one interpolation.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        parts = []
        call_id = record_call_id(record)
        if call_id is not None:
            parts.append(f"gateway_call_id={call_id}")
        record.call_context = (" ".join(parts) + " ") if parts else ""
        return True


_INSTALLED = "_aigateway_log_handler"
"""Marks the handler THIS module installed.

Idempotence has to be about our own handler, not about the logger being empty:
anything else may have attached one first — a test harness, a sidecar, an
embedding process — and ``if not logger.handlers`` would then read that as
"already configured" and install nothing at all. The failure is silent and
looks exactly like the bug this module exists to fix.
"""


def configure(stream: TextIO | None = None) -> None:
    """Give the ``aigateway`` logger tree its own handler and level.

    Idempotent: a second call neither stacks handlers nor disturbs anyone
    else's. ``propagate`` is disabled so that a later root configuration —
    uvicorn's, a test harness's, a sidecar's — cannot turn every record into
    two.
    """

    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(os.getenv(LEVEL_ENV, DEFAULT_LEVEL).upper())
    if not any(getattr(handler, _INSTALLED, False) for handler in logger.handlers):
        handler = logging.StreamHandler(stream)
        # WHY the filter sits on the HANDLER and not the logger (OME-938): a filter on a logger
        # is not consulted for records that arrive from a CHILD logger, so `aigateway.foo`'s
        # lines would render an empty context while `aigateway`'s own rendered correctly —
        # the partial-coverage failure this feature exists to remove.
        handler.addFilter(CallContextFilter())
        handler.setFormatter(logging.Formatter(_FORMAT, defaults={"call_context": ""}))
        setattr(handler, _INSTALLED, True)
        logger.addHandler(handler)
    logger.propagate = False


__all__ = [
    "APP_LOGGER",
    "DEFAULT_LEVEL",
    "LEVEL_ENV",
    "CallContextFilter",
    "configure",
]
