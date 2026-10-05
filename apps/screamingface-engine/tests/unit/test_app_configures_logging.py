"""Every ASGI entry keeps app logging, not just `cli.main` (OME-942).

`uvicorn.run()` installs handlers for the `uvicorn*` loggers ONLY, so a `screamingface_engine`
record falls through to `logging.lastResort` and is discarded below WARNING. `logs.py`'s own
docstring documents that regression; until now the only thing preventing it was
`cli.main`, so `uvicorn screamingface_engine.app:create_app_from_env`, an embedding process, or
any other ASGI host silently reproduced it in full.

`create_app` is the one door every ASGI entry goes through, so the fix belongs there.

Self-contained by design (sdlc rule 5), including restoring the process-global logger it
touches.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from screamingface_engine.app import create_app
from screamingface_engine.logs import APP_LOGGER, LEVEL_ENV


@pytest.fixture(autouse=True)
def _restore_app_logger() -> Iterator[None]:
    """Logging is process-global; leave it exactly as found."""
    logger = logging.getLogger(APP_LOGGER)
    handlers = list(logger.handlers)
    level, propagate = logger.level, logger.propagate
    logger.handlers.clear()
    try:
        yield
    finally:
        logger.handlers.clear()
        logger.handlers.extend(handlers)
        logger.setLevel(level)
        logger.propagate = propagate


def _app_handlers() -> list[logging.Handler]:
    return list(logging.getLogger(APP_LOGGER).handlers)


def test_building_the_app_gives_the_app_logger_a_handler() -> None:
    # STORY: as the operator reading a deployment's logs, the App's own lines are there —
    # whatever started the ASGI app.
    assert _app_handlers() == [], "fixture should have cleared the logger"

    create_app()

    handlers = _app_handlers()
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)


def test_the_app_logger_emits_at_info_after_the_app_is_built() -> None:
    """The whole point: INFO is the level the App's evidence is written at, and
    `logging.lastResort` drops it."""
    create_app()

    assert logging.getLogger(APP_LOGGER).isEnabledFor(logging.INFO)


def test_a_record_from_a_submodule_reaches_that_handler() -> None:
    """Behaviour, not wiring: a record emitted by real app code lands in the stream."""
    create_app()
    handler = _app_handlers()[0]
    records: list[logging.LogRecord] = []
    handler.emit = records.append  # type: ignore[method-assign]

    logging.getLogger("screamingface_engine.ws.bridge").info("ws closed code=1006")

    assert [record.getMessage() for record in records] == ["ws closed code=1006"]


def test_the_environment_level_is_honoured_by_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """STORY: as the operator who set `logLevel: DEBUG` in the chart, the pod I restarted is
    actually at DEBUG. Asserted with a NON-default level — INFO passes against code that never
    reads the environment at all."""
    monkeypatch.setenv(LEVEL_ENV, "DEBUG")

    create_app()

    assert logging.getLogger(APP_LOGGER).level == logging.DEBUG


def test_two_apps_in_one_process_do_not_double_every_line() -> None:
    """INVARIANT: `configure` is idempotent, and `create_app` is called more than once per
    process — by tests, by `--local` mode, and after `cli.main` already configured. A second
    handler would duplicate every record rather than fail loudly."""
    create_app()
    create_app()

    assert len(_app_handlers()) == 1


def test_the_app_logger_does_not_propagate() -> None:
    """INVARIANT: propagation off is what stops a later root configuration — uvicorn's, a
    sidecar's — from turning every record into two."""
    create_app()

    assert logging.getLogger(APP_LOGGER).propagate is False
