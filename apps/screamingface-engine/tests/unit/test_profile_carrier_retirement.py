"""Stage D's selector carrier is absent below the ingress refusal boundary."""

from __future__ import annotations

import inspect
import json
from dataclasses import fields
from typing import cast

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.catalog.aigateway import _headers as catalog_headers
from screamingface_engine.catalog.port import Credential
from screamingface_engine.connections.aigateway import _headers as connection_headers
from screamingface_engine.connections.port import Caller
from screamingface_engine.request_scope import RequestScope
from screamingface_engine.runner_queue import encode_message
from screamingface_engine.worker.supervisor import cold_child_env
from screamingface_engine.worker.warm_pool import deploy_env
from screamingface_engine.world.connector import _headers as world_headers
from url4.streaming.interfaces import Executor

_FORGED_IDENTITY = {
    "X-User-Email": "alice@example.com",
    "X-Profile": "must-not-leave-the-engine",
}
_RETIRED_ENV_KEY = "AIGATEWAY_PROFILE"


def test_runner_implementations_have_no_profile_selector() -> None:
    """INVARIANT: every JobRunner implementation satisfies the selector-less port."""
    assert "profile" not in inspect.signature(InProcessJobRunner.schedule).parameters
    assert "profile" not in inspect.signature(QueueJobRunner.schedule).parameters


def test_runtime_state_has_no_profile_carrier() -> None:
    """INVARIANT: no queue/env or request object can retain a Profile selector."""
    assert not hasattr(job_env, "AIGATEWAY_PROFILE")
    assert "profile" not in {field.name for field in fields(RequestScope)}
    assert "profile" not in {field.name for field in fields(Credential)}
    assert "profile" not in {field.name for field in fields(Caller)}
    assert "profile" not in inspect.signature(Credential.derive).parameters


def test_queue_message_has_no_profile_carrier() -> None:
    assert "AIGATEWAY_PROFILE" not in json.loads(encode_message("topic", "'hi'", 60))


def test_ambient_profile_is_scrubbed_at_every_run_environment_boundary() -> None:
    """INVARIANT: a stray deploy-time value cannot survive into run or child environments."""
    ambient = {_RETIRED_ENV_KEY: "must-not-reach-a-run", "RETAINED_DEPLOY_VALUE": "yes"}
    runner = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda _: cast(Executor, object()),
        base_env=ambient,
    )

    inprocess = runner._env("topic", "'hi'", 60, None)  # noqa: SLF001
    cold = cold_child_env(ambient, {}, 1)
    warm = deploy_env(ambient)

    for env in (inprocess, cold, warm):
        assert _RETIRED_ENV_KEY not in env
        assert env["RETAINED_DEPLOY_VALUE"] == "yes"


def test_outbound_gateway_headers_strip_profile_from_identity() -> None:
    """INVARIANT: identity input cannot smuggle the retired selector to AIGateway."""
    assert "X-Profile" not in catalog_headers(Credential.derive(identity=_FORGED_IDENTITY))
    assert "X-Profile" not in connection_headers(Caller(_FORGED_IDENTITY))
    scope = RequestScope(identity_headers=_FORGED_IDENTITY, origin="run")
    assert "X-Profile" not in world_headers(scope)
