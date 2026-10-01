"""The scoreboard's own log records have to survive the process that hosts them (OME-937).

`uvicorn.run()` configures the `uvicorn*` loggers and nothing else, so `scoreboard.*` records
reached `logging.lastResort` — WARNING-level, message-only — and INFO was discarded.
`SCOREBOARD_LOG_LEVEL` reached uvicorn and never the app. These tests pin the fix and every
entry that must apply it: the ASGI app and the two job CLIs.

The `scoreboard` logger is reset around every test by `tests/unit/conftest.py`.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest

from scoreboard import import_baselines, seed
from scoreboard.config import Settings
from scoreboard.logs import APP_LOGGER, LEVEL_ENV, configure
from scoreboard.main import create_app


def _own_handlers() -> list[logging.Handler]:
    return [
        h for h in logging.getLogger(APP_LOGGER).handlers if isinstance(h, logging.StreamHandler)
    ]


def test_a_scoreboard_info_record_reaches_the_configured_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # STORY: as the operator reading a deployment's logs, the app's INFO lines are there.
    monkeypatch.delenv(LEVEL_ENV, raising=False)
    stream = io.StringIO()
    configure(stream)

    logging.getLogger("scoreboard.scores.store").info("score accepted id=42")

    rendered = stream.getvalue()
    assert "score accepted id=42" in rendered
    assert "INFO" in rendered
    assert "scoreboard.scores.store" in rendered


def test_the_configured_level_filters_below_it(monkeypatch: pytest.MonkeyPatch) -> None:
    # The knob is real in both directions: raising it silences INFO.
    monkeypatch.setenv(LEVEL_ENV, "warning")
    stream = io.StringIO()
    configure(stream)

    logger = logging.getLogger("scoreboard.scores.store")
    logger.info("chatty")
    logger.warning("worth seeing")

    assert "chatty" not in stream.getvalue()
    assert "worth seeing" in stream.getvalue()


def test_an_operator_can_lower_the_level_without_a_code_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LEVEL_ENV, "debug")
    stream = io.StringIO()
    configure(stream)

    logging.getLogger("scoreboard.scores.frontier").debug("frontier detail")

    assert "frontier detail" in stream.getvalue()


def test_uvicorns_trace_level_does_not_crash_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    # REGRESSION GUARD: `trace` is a valid uvicorn --log-level and the same env var feeds both,
    # but stdlib `logging` has no TRACE name outside a process that imported uvicorn.config
    # (the job CLIs never do). Configuring must not turn a valid value into a startup crash.
    monkeypatch.setenv(LEVEL_ENV, "trace")
    stream = io.StringIO()
    configure(stream)

    logging.getLogger("scoreboard.scores.store").debug("trace-level detail")

    assert "trace-level detail" in stream.getvalue()


def test_configuration_is_idempotent_so_records_are_not_doubled() -> None:
    stream = io.StringIO()
    configure(stream)
    configure(stream)

    logging.getLogger("scoreboard.scores.store").info("once")

    assert stream.getvalue().count("once") == 1


def test_a_foreign_handler_does_not_suppress_our_own() -> None:
    # Idempotence is about OUR handler, not an empty logger: a harness or sidecar handler
    # attached first must not make configure() install nothing.
    logging.getLogger(APP_LOGGER).addHandler(logging.NullHandler())
    stream = io.StringIO()

    configure(stream)
    logging.getLogger("scoreboard.scores.store").info("still recorded")

    assert "still recorded" in stream.getvalue()


def test_the_app_logger_does_not_propagate_into_a_root_configuration() -> None:
    configure(io.StringIO())

    assert logging.getLogger(APP_LOGGER).propagate is False


def test_uvicorns_loggers_are_left_alone() -> None:
    # The ticket's boundary: uvicorn owns its own loggers via `uvicorn.run(log_level=...)`.
    uvicorn_logger = logging.getLogger("uvicorn")
    before = (list(uvicorn_logger.handlers), uvicorn_logger.level, uvicorn_logger.propagate)

    configure(io.StringIO())

    after = (list(uvicorn_logger.handlers), uvicorn_logger.level, uvicorn_logger.propagate)
    assert after == before


def test_building_the_app_configures_app_logging(tmp_path: Path) -> None:
    # Every ASGI host goes through create_app, so the fix belongs there, not only in cli.main.
    assert _own_handlers() == []

    create_app(Settings(database_url=f"sqlite://{tmp_path / 'x.sqlite3'}", cors_origins=[]))

    assert len(_own_handlers()) == 1
    assert logging.getLogger(APP_LOGGER).isEnabledFor(logging.INFO)


def test_the_seed_job_configures_app_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    # The seed Job is its own process; uvicorn never runs there.
    monkeypatch.delenv(seed.SEED_BENCHMARKS_ENV, raising=False)
    monkeypatch.delenv(seed.ENGINE_URL_ENV, raising=False)

    seed.main([])

    assert len(_own_handlers()) == 1


def test_the_baseline_import_job_configures_app_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(import_baselines.SEED_BASELINES_ENV, raising=False)

    import_baselines.main([])

    assert len(_own_handlers()) == 1
