"""Log configuration for the report-intake service.

WHY this module exists at all: `uvicorn.run()` installs handlers for the `uvicorn*` loggers ONLY
and leaves the root logger with none. Every `report_intake` record therefore falls through to
`logging.lastResort`, which emits at WARNING and message-only — so INFO lines are discarded in
every deployment and the ones that survive arrive without a level, a name, or a timestamp. The
symptom is a service whose logs contain nothing but access lines, which reads as "nothing
happened" rather than "this process cannot say anything".

That matters here more than it looks. This service's operational events are precisely the ones
nothing else can observe: a report we permanently failed to file, a bot gate that could not be
evaluated, a payload rejected as content-bearing. None of them have a caller to complain to —
the reporter already got their `202`.

Copied from the engine's `logs.py`, NOT from scoreboard's arrangement, which has exactly the
`lastResort` bug described above: `SCOREBOARD_LOG_LEVEL` governs only uvicorn's loggers, never
the app's. Stdlib only, deliberately — this must work before any framework is imported.
"""

import logging
from typing import TextIO

APP_LOGGER = "report_intake"
DEFAULT_LEVEL = "info"

# Matches uvicorn's own column so a deployment's logs read as one stream rather than two.
_FORMAT = "%(levelname)s:     %(name)s %(message)s"

_INSTALLED = "_report_intake_log_handler"
"""Marks the handler THIS module installed.

Idempotence has to be about our own handler, not about the logger being empty: anything else may
have attached one first — a test harness, a sidecar, an embedding process — and
`if not logger.handlers` would then read that as "already configured" and install nothing at all.
The failure is silent and looks exactly like the bug this module exists to fix.
"""


def configure(level: str = DEFAULT_LEVEL, stream: TextIO | None = None) -> None:
    """Give the `report_intake` logger tree its own handler and level.

    The level arrives from `Settings.log_level` rather than from the environment directly:
    `Settings` is the sole authority on this service's environment, and a module reading
    `os.environ` behind its back is how the two drift apart.

    Idempotent: a second call neither stacks handlers nor disturbs anyone else's. `propagate` is
    disabled so that a later root configuration — uvicorn's, a test harness's, a sidecar's —
    cannot turn every record into two.
    """
    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(level.upper())
    if not any(getattr(handler, _INSTALLED, False) for handler in logger.handlers):
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(_FORMAT))
        setattr(handler, _INSTALLED, True)
        logger.addHandler(handler)
    logger.propagate = False


__all__ = ["APP_LOGGER", "DEFAULT_LEVEL", "configure"]
