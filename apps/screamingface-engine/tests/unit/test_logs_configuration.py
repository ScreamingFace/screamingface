"""The App's own log records have to survive the process that hosts them.

`uvicorn.run()` configures the `uvicorn*` loggers and nothing else, so before this the
App's INFO records reached `logging.lastResort` — a WARNING-level fallback — and were
discarded. Every deployment logged health checks and nothing else, which reads as an idle
service rather than a muted one.

Self-contained by design (sdlc rule 5), including restoring the global logger it touches.
"""

import io
import logging
from collections.abc import Iterator

import pytest

from screamingface_engine.logs import APP_LOGGER, LEVEL_ENV, configure, run_scope


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


def test_an_info_record_from_the_app_reaches_a_handler() -> None:
    # STORY: as the engineer reading back a drop, the line the App wrote is
    # actually there. Before this, `_logger.info(...)` anywhere in
    # `screamingface_engine` produced no output at all in a deployed process — the
    # evidence existed in the code and nowhere else.
    stream = io.StringIO()
    configure(stream)

    logging.getLogger("screamingface_engine.ws.bridge").info(
        "ws stream ended outcome=client close 1006"
    )

    assert "ws stream ended outcome=client close 1006" in stream.getvalue()


def test_configuration_is_idempotent_so_records_are_not_doubled() -> None:
    # A second call must not stack a second handler: duplicated lines would make the frame
    # and heartbeat counts read as twice what they were.
    stream = io.StringIO()
    configure(stream)
    configure(stream)

    logging.getLogger("screamingface_engine.ws.bridge").info("once")

    assert stream.getvalue().count("once") == 1


def test_the_app_logger_does_not_propagate_into_a_root_configuration() -> None:
    # uvicorn, a test harness, or a sidecar may configure the root logger later. Propagating
    # would then emit every record twice through two different formatters.
    configure(io.StringIO())

    assert logging.getLogger(APP_LOGGER).propagate is False


def test_an_operator_can_lower_the_level_without_a_code_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Debugging a live drop should not require a new image.
    monkeypatch.setenv(LEVEL_ENV, "debug")
    stream = io.StringIO()
    configure(stream)

    logging.getLogger("screamingface_engine.ws.bridge").debug("cursor detail")

    assert "cursor detail" in stream.getvalue()


def test_a_foreign_handler_does_not_suppress_our_own() -> None:
    # REGRESSION: idempotence used to be "the logger has no handlers", so anything that
    # attached one first — a harness, a sidecar, an embedding process — made `configure`
    # install nothing. The App then logged into that foreign handler's level and format, or
    # nowhere at all, which is indistinguishable from the muting this module exists to fix.
    logging.getLogger(APP_LOGGER).addHandler(logging.NullHandler())
    stream = io.StringIO()

    configure(stream)
    logging.getLogger("screamingface_engine.ws.bridge").info("still recorded")

    assert "still recorded" in stream.getvalue()


def test_a_record_inside_a_run_scope_carries_topic_and_trace_id() -> None:
    # FEATURE (OME-1069): a Job's process logs are the operator's only view of a run that is
    # not the CloudEvents stream, and every line inside a run must be attributable to it.
    stream = io.StringIO()
    configure(stream)

    with run_scope("cap-topic", "ab" * 16):
        logging.getLogger("screamingface_engine.ws.bridge").info("run started")

    rendered = stream.getvalue()
    assert "topic=cap-topic trace_id=" in rendered
    assert "run started" in rendered


def test_a_record_outside_a_run_scope_renders_unchanged() -> None:
    # The control plane never binds a run scope, so its lines must be byte-identical to
    # before the feature existed — an empty run-context field, not a placeholder.
    stream = io.StringIO()
    configure(stream)

    logging.getLogger("screamingface_engine.ws.bridge").info("ws stream ended")

    rendered = stream.getvalue()
    assert "ws stream ended" in rendered
    assert "topic=" not in rendered


def test_run_scope_restores_the_previous_context_on_exit() -> None:
    # Nested scopes (a run wrapping a benchmark's own scope) must restore the outer run's
    # identity rather than leaving the inner one bound for the rest of the process.
    stream = io.StringIO()
    configure(stream)
    logger = logging.getLogger("screamingface_engine.ws.bridge")

    with run_scope("outer-topic"):
        with run_scope("inner-topic"):
            logger.info("inner")
        logger.info("outer")

    rendered = stream.getvalue()
    assert "topic=inner-topic" in rendered
    assert "topic=outer-topic" in rendered
