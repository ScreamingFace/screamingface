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

from collections.abc import Callable
from typing import Any

import pytest

from screamingface_engine.config import Settings
from screamingface_engine.request_scope import RequestScope, request_scope


@pytest.fixture(autouse=True)
def _default_request_scope() -> object:
    with request_scope(RequestScope()):
        yield


NodeTierSettings = Callable[..., Settings]


@pytest.fixture
def node_tier_settings() -> NodeTierSettings:
    """Settings for an App with a node tier: a node base URL and the store both tiers share.

    WHY S3 and not the default filesystem store: FX-38 refuses a filesystem store when
    ``node_base_url`` is set (the node pod's disk is not the App's, OME-929). Constructing the S3
    store dials nothing, so the tests stay offline. Keyword overrides replace any field.
    """

    def build(**overrides: Any) -> Settings:
        fields: dict[str, Any] = {
            "jwt_secret": "s" * 32,
            "node_base_url": "http://node.test",
            "artifact_store": "s3",
            "artifact_s3_endpoint_url": "http://garage.test:3900",
            "artifact_s3_bucket": "artifacts",
            "artifact_s3_access_key": "GKtest",
            "artifact_s3_secret_key": "secret",
        }
        return Settings(**{**fields, **overrides})

    return build
