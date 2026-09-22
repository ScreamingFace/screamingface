"""Shared test wiring.

FEATURE (F2, prd/01): the connector reads its caller state from a ``request_scope`` ContextVar,
and every production path binds one before a handler runs — the child run path from ``job_env``,
the sync surface from verified headers. Tests that drive a handler directly therefore need a
scope too, so this autouse fixture is the test harness's producer: an anonymous default scope
bound for the duration of each test.

WHY this does not weaken the contract: ``current_scope()`` still raises ``RequestScopeError``
when nothing is bound, and that is asserted in ``tests/unit/test_request_scope.py`` against a
fresh ``contextvars.Context``. Tests that care about identity, profile, cache or seed bind their
OWN scope inside the test, which shadows this one. The production producer is exercised
end-to-end by ``test_world_golden_parity.py``, ``test_cache_policy_threading.py`` and
``test_answer_seed_threading.py`` through ``build_executor``.
"""

from __future__ import annotations

import pytest

from screamingface_engine.request_scope import RequestScope, request_scope


@pytest.fixture(autouse=True)
def _default_request_scope() -> object:
    with request_scope(RequestScope()):
        yield
