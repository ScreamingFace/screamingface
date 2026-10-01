"""Log configuration for every entry of the scoreboard image (OME-937).

WHY this module exists at all: `uvicorn.run()` installs handlers for the `uvicorn*` loggers
ONLY and leaves the root logger with none. Every `scoreboard.*` record therefore fell through
to `logging.lastResort`, which emits message-only at WARNING — so the app's INFO lines were
discarded, and `SCOREBOARD_LOG_LEVEL` (plumbed chart → configmap → `uvicorn.run`) governed
uvicorn's loggers and never the app's.

Stdlib only, deliberately — the seed and baseline-import Jobs need this as much as the server,
and neither runs uvicorn.

AIDEV-NOTE: ported from `apps/screamingface-engine/src/screamingface_engine/logs.py`. The
engine's run-context filter (OME-1069) is engine-specific and deliberately not ported.
"""

from __future__ import annotations

import logging
import os
from typing import TextIO

APP_LOGGER = "scoreboard"
LEVEL_ENV = "SCOREBOARD_LOG_LEVEL"
DEFAULT_LEVEL = "INFO"

# Matches uvicorn's own column so a deployment's logs read as one stream rather than two.
_FORMAT = "%(levelname)s:     %(name)s %(message)s"

# WHY: `trace` is a valid uvicorn `--log-level`, and the same env var feeds both. uvicorn
# registers the TRACE name (level 5) only when `uvicorn.config` is imported — which the Job CLIs
# never do — so without this mapping a valid setting would crash `logger.setLevel`.
_TRACE_NAME = "TRACE"
_TRACE_LEVEL = 5

_INSTALLED = "_scoreboard_log_handler"
"""Marks the handler THIS module installed.

Idempotence has to be about our own handler, not about the logger being empty: anything else
may have attached one first — a test harness, a sidecar, an embedding process — and
`if not logger.handlers` would then read that as "already configured" and install nothing.
"""


def _level() -> int | str:
    name = os.getenv(LEVEL_ENV, DEFAULT_LEVEL).upper()
    return _TRACE_LEVEL if name == _TRACE_NAME else name


def configure(stream: TextIO | None = None) -> None:
    """Give the `scoreboard` logger tree its own handler and level.

    Idempotent: a second call neither stacks handlers nor disturbs anyone else's.
    `propagate` is disabled so that a later root configuration — uvicorn's, a test harness's,
    a sidecar's — cannot turn every record into two. uvicorn's own loggers are not touched.
    """

    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(_level())
    if not any(getattr(handler, _INSTALLED, False) for handler in logger.handlers):
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(_FORMAT))
        setattr(handler, _INSTALLED, True)
        logger.addHandler(handler)
    logger.propagate = False


__all__ = ["APP_LOGGER", "DEFAULT_LEVEL", "LEVEL_ENV", "configure"]
