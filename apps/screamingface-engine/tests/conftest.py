"""Suite-wide isolation of the one piece of process-global state the App configures.

WHY this exists (OME-942): `create_app` now calls `logs.configure()`, so that every ASGI entry
keeps app logging and not just `cli.main` — and `configure` deliberately sets
`propagate = False` on the `screamingface_engine` logger, which is what stops a later root
configuration (uvicorn's, a sidecar's) from turning every record into two.

`logging` is process-global. Without this fixture the FIRST test that builds an App silently
changes how every LATER test's records travel: pytest's `caplog` captures at the ROOT logger,
so a suite-mate asserting on `screamingface_engine.*` records would see an empty capture — and
fail for a reason that has nothing to do with what it tests, depending on test ORDER.

INVARIANT: this isolates state, it never substitutes for asserting the behaviour.
`tests/unit/test_app_configures_logging.py` asserts the handler, the level and
`propagate is False` directly, so the production contract is still pinned by a test.

AIDEV-NOTE: the same save/restore is done locally by `test_logs_configuration.py`, which
predates this file and is deliberately left self-contained.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from screamingface_engine.logs import APP_LOGGER


class _CaplogBridge(logging.Handler):
    """Feed `caplog` the records that `propagate = False` keeps away from the root logger.

    WHY conditional on `propagate` AT EMIT TIME rather than simply attaching caplog's own
    handler here: a test that has NOT built an App still propagates, so its records reach
    caplog at the root as they always did. Forwarding them here as well would deliver each one
    TWICE, and the suite is full of `len(records) == 1` assertions — the fix would then break
    the tests it exists to keep working.

    AIDEV-NOTE: this observes, it never filters. Every record the app logger accepts is either
    captured at the root (propagating) or forwarded here (not) — exactly one of the two.
    """

    def __init__(self, target: logging.Handler, source: logging.Logger) -> None:
        super().__init__(level=logging.NOTSET)
        self._target = target
        self._source = source

    def emit(self, record: logging.LogRecord) -> None:
        if not self._source.propagate:
            self._target.handle(record)


@pytest.fixture(autouse=True)
def _isolate_app_logger(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Leave the `screamingface_engine` logger exactly as each test found it, and keep
    `caplog` able to see it after an App is built."""
    logger = logging.getLogger(APP_LOGGER)
    handlers = list(logger.handlers)
    level, propagate = logger.level, logger.propagate
    bridge = _CaplogBridge(caplog.handler, logger)
    logger.addHandler(bridge)
    try:
        yield
    finally:
        logger.handlers.clear()
        logger.handlers.extend(handlers)
        logger.setLevel(level)
        logger.propagate = propagate
