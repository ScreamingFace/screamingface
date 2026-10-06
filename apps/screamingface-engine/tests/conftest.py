"""Shared test wiring: two autouse fixtures.

1. `_default_request_scope` — the connector's request scope.

FEATURE (F2, prd/01): the connector reads its caller state from a ``request_scope`` ContextVar,
and every production path binds one before a handler runs — the child run path from ``job_env``,
the sync surface from verified headers. Tests that drive a handler directly therefore need a
scope too, so this autouse fixture is the test harness's producer: an anonymous default scope
bound for the duration of each test.

WHY this does not weaken the contract: ``current_scope()`` still raises ``RequestScopeError``
when nothing is bound, and that is asserted in ``tests/unit/test_request_scope.py`` against a
fresh ``contextvars.Context``. Tests that care about identity, cache or seed bind their
OWN scope inside the test, which shadows this one. The production producer is exercised
end-to-end by ``test_world_golden_parity.py``, ``test_cache_policy_threading.py`` and
``test_answer_seed_threading.py`` through ``build_executor``, and each producer is proven
with this fixture OFF (the ``no_default_scope`` marker) in ``tests/unit/test_scope_producers.py``.

2. `_isolate_app_logger` — suite-wide isolation of the one piece of process-global state
the App configures.

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
from screamingface_engine.request_scope import RequestScope, request_scope


@pytest.fixture(autouse=True)
def _default_request_scope(request: pytest.FixtureRequest) -> Iterator[None]:
    # FEATURE (FX-61): `@pytest.mark.no_default_scope` turns this harness producer OFF, so a test
    # can prove a PRODUCTION producer bound the scope — not this fixture. See
    # `tests/unit/test_scope_producers.py`.
    if request.node.get_closest_marker("no_default_scope") is not None:
        yield
        return
    with request_scope(RequestScope(origin="run")):
        yield


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


# WHY a baseline taken at IMPORT time rather than "as each test found it": a module- or
# session-scoped fixture that builds an App (e.g. `test_selector_openapi.py`'s `schema`) is set
# up BEFORE this function-scoped fixture, so "as found" would already be the configured state
# (`propagate = False` plus the App's handler) and would be restored as if it were pristine —
# leaking into every later module. The conftest is imported before any App exists.
_BASELINE_HANDLERS = list(logging.getLogger(APP_LOGGER).handlers)
_BASELINE_LEVEL = logging.getLogger(APP_LOGGER).level
_BASELINE_PROPAGATE = logging.getLogger(APP_LOGGER).propagate


def _restore_baseline(logger: logging.Logger) -> None:
    logger.handlers.clear()
    logger.handlers.extend(_BASELINE_HANDLERS)
    logger.setLevel(_BASELINE_LEVEL)
    logger.propagate = _BASELINE_PROPAGATE


@pytest.fixture(autouse=True)
def _isolate_app_logger(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Start every test from the unconfigured `screamingface_engine` logger, leave it that way,
    and keep `caplog` able to see it after an App is built."""
    logger = logging.getLogger(APP_LOGGER)
    _restore_baseline(logger)
    bridge = _CaplogBridge(caplog.handler, logger)
    logger.addHandler(bridge)
    try:
        yield
    finally:
        _restore_baseline(logger)
