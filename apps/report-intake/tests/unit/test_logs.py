"""The app logger must be able to speak.

Without its own handler every `report_intake` record falls through to `logging.lastResort`, which
emits at WARNING and message-only — so INFO is discarded and what survives arrives with no level,
no logger name, and no timestamp. This service's most important events have no caller to complain
to: the reporter already has their `202`.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Generator

import pytest

from report_intake import logs
from report_intake.config import Settings
from report_intake.main import create_app


@pytest.fixture
def app_logger() -> Generator[logging.Logger, None, None]:
    """Hand back the real logger, blank on entry and restored on exit.

    Blank on entry matters as much as restored on exit: `create_app` configures this same global
    logger, so any earlier test in the session leaves a handler behind and the idempotence cases
    below would pass or fail depending on collection order.
    """
    logger = logging.getLogger(logs.APP_LOGGER)
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    logger.handlers = []
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    try:
        yield logger
    finally:
        logger.handlers = handlers
        logger.setLevel(level)
        logger.propagate = propagate


def test_a_configured_logger_emits_the_level_and_the_logger_name(
    app_logger: logging.Logger,
) -> None:
    stream = io.StringIO()
    logs.configure("info", stream)

    app_logger.info("a report was rejected as content-bearing")

    assert "INFO" in stream.getvalue()
    assert logs.APP_LOGGER in stream.getvalue()


def test_an_info_record_survives_at_the_default_level(app_logger: logging.Logger) -> None:
    """The whole point: `logging.lastResort` would have dropped this one."""
    stream = io.StringIO()
    logs.configure(logs.DEFAULT_LEVEL, stream)

    app_logger.info("delivery deferred; the record stays pending")

    assert "delivery deferred" in stream.getvalue()


def test_a_second_call_does_not_stack_a_second_handler(app_logger: logging.Logger) -> None:
    logs.configure("info", io.StringIO())
    installed = len(app_logger.handlers)

    logs.configure("info", io.StringIO())

    assert len(app_logger.handlers) == installed


def test_a_handler_someone_else_installed_does_not_count_as_configured(
    app_logger: logging.Logger,
) -> None:
    """Idempotence is about OUR handler, not about the logger being empty. `if not
    logger.handlers` would read a test harness's or a sidecar's handler as "already configured"
    and install nothing — silently, and looking exactly like the bug this module exists to fix.
    """
    stream = io.StringIO()
    app_logger.addHandler(logging.NullHandler())

    logs.configure("info", stream)
    app_logger.info("still audible")

    assert "still audible" in stream.getvalue()


def test_records_do_not_propagate_to_whatever_configures_the_root(
    app_logger: logging.Logger,
) -> None:
    """uvicorn, a test harness, or a sidecar configuring the root later must not turn every
    record into two."""
    logs.configure("info", io.StringIO())

    assert app_logger.propagate is False


def test_the_level_comes_from_settings_by_way_of_create_app(
    hermetic_environment: None, app_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configured from `create_app`, not only from `cli.main`: a pod's entrypoint is uvicorn
    importing the app module, so configuring logs in the CLI alone leaves every deployed process
    on `lastResort`.
    """
    monkeypatch.setenv("REPORT_INTAKE_LOG_LEVEL", "warning")

    create_app(Settings())

    assert app_logger.level == logging.WARNING
    assert app_logger.handlers != []
