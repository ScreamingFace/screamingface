"""Suite-wide isolation of the one piece of process-global state the app configures.

WHY this exists (OME-937): `create_app` — and `scoreboard.main`'s module-level `app`, built the
moment anything imports it — calls `logs.configure()`, which deliberately sets
`propagate = False` on the `scoreboard` logger so that a later root configuration cannot turn
every record into two. `logging` is process-global, and pytest's `caplog` captures at the ROOT
logger, so without this fixture every `caplog` assertion on a `scoreboard.*` record would see an
empty capture once any app had been built — failing for a reason unrelated to what it tests.

INVARIANT: this isolates state, it never substitutes for asserting the behaviour.
`test_logs_configuration.py` asserts the handler, the level and `propagate is False` directly.

AIDEV-NOTE: mirrors the engine's `tests/conftest.py` (OME-942). The pristine state is defined
explicitly rather than snapshotted at import, because importing `scoreboard.main` (the root
conftest does) has already configured the logger by the time this module loads.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from scoreboard.logs import APP_LOGGER


class _CaplogBridge(logging.Handler):
    """Feed `caplog` the records that `propagate = False` keeps away from the root logger.

    WHY conditional on `propagate` AT EMIT TIME: a test that has not built an app still
    propagates, so its records reach caplog at the root; forwarding them here too would deliver
    each one twice. Exactly one of the two paths carries every record.

    WHY also conditional on caplog's handler NOT already being on the logger: pytest >= 9
    attaches its capture handlers directly to every logger that is non-propagating when a test
    PHASE begins — so an app built in a fixture (setup phase) is already captured during the
    call phase, and forwarding as well doubled each record. The bridge covers only the case
    pytest misses: a logger that becomes non-propagating mid-phase (an app built in the test).
    """

    def __init__(self, target: logging.Handler, source: logging.Logger) -> None:
        super().__init__(level=logging.NOTSET)
        self._target = target
        self._source = source

    def emit(self, record: logging.LogRecord) -> None:
        if not self._source.propagate and self._target not in self._source.handlers:
            self._target.handle(record)


def _restore_pristine(logger: logging.Logger) -> None:
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


@pytest.fixture(autouse=True)
def _isolate_app_logger(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Start every test from an unconfigured `scoreboard` logger, leave it that way, and keep
    `caplog` able to see it after an app is built."""
    logger = logging.getLogger(APP_LOGGER)
    _restore_pristine(logger)
    logger.addHandler(_CaplogBridge(caplog.handler, logger))
    try:
        yield
    finally:
        _restore_pristine(logger)
