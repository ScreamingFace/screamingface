"""OME-303 §9.12 and §9.24 — app lifecycle and log correlation.

Both claims are about wiring that only the running app can prove. ``test_handler``
already shows the handler's ``close()`` works; what is unproven there is that lifespan
shutdown actually CALLS it. Likewise the collector mints a ``gateway_call_id``, but the
id is worthless for correlation unless it reaches the logs.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from functools import partial
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise

from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.plugins.anthropic_provider.auth import credential_service_for

_CHAT_PATH = "/v1/chat/completions"
_ANTHROPIC_DISPATCH = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
)
_ACCOUNTING_HEADERS = {"X-AIGW-Accounting": "enabled"}


async def _create_active_connection(account_id: str, *, label: str = "default"):
    store = OAuthConnectionStore()
    connection = await store.create_pending(
        account_id=account_id, provider="anthropic", label=label, connection_id=uuid4()
    )
    return await store.complete(connection, label=label, identity=None)


def _arrange_account(client: TestClient, credential_blobs) -> None:
    account_id = client.get("/v1/auth/me").json()["id"]
    portal = client.portal
    assert portal is not None, "the TestClient was used outside its context manager"
    connection = portal.call(partial(_create_active_connection, account_id))
    credential_blobs.write(
        credential_service_for(credential_key_for(account_id, connection.id)),
        "default",
        json.dumps(
            {
                "access_token": "tok",
                "refresh_token": "rt",
                "expires_at_ms": int(time.time() * 1000) + 3_600_000,
                "token_type": "Bearer",
            }
        ),
    )


async def _payload(_body: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "model": "claude-haiku-4-5",
        "choices": [{"message": {"content": "ANSWER"}, "finish_reason": "stop"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


class _Dispatch:
    async def __call__(self, body: dict[str, Any]) -> dict[str, Any]:
        return await _payload(body)


@pytest.fixture
def logged_in(client: TestClient) -> TestClient:
    response = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


@pytest.fixture
def app_env(monkeypatch, credential_blobs):
    """The ``client`` fixture's ENVIRONMENT without its app.

    AIDEV-NOTE: Tortoise permits exactly one global context per process, so a test that
    owns an app's whole lifespan cannot also depend on ``client`` — the second
    ``Tortoise.init`` raises ``ConfigurationError``. Replicating the env here is what
    lets these tests enter and exit a lifespan of their own.
    """
    from tests.conftest import TEST_SECRET_KEY, _prepare_sqlite_db

    database_url = f"sqlite://{credential_blobs.db_path}"
    monkeypatch.setenv("AIGATEWAY_DATABASE_URL", database_url)
    monkeypatch.setenv("AIGATEWAY_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("AIGATEWAY_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("AIGATEWAY_PROVISIONING_TOKEN", "p" * 32)
    monkeypatch.setenv("AIGATEWAY_SECRET_KEY", base64.b64encode(TEST_SECRET_KEY).decode())
    monkeypatch.setenv("AIGW_ALLOWED_NETWORKS", "10.0.0.0/8")
    _prepare_sqlite_db(database_url)
    yield
    asyncio.run(Tortoise.close_connections())


class TestSharedHandlerLifecycle:
    def test_environment_opt_out_disables_handler_and_response_metadata(
        self, app_env, monkeypatch, credential_blobs
    ) -> None:
        monkeypatch.setenv("AIGW_TAXONOMY_ENABLED", "false")
        from aigateway.main import create_app

        app = create_app()
        with TestClient(app, client=("10.1.2.3", 50000)) as client:
            assert app.state.taxonomy_plugin.enabled is False
            assert app.state.taxonomy_plugin.handler is None
            assert app.state.usage_accounting_handler is None
            login = client.post(
                "/v1/auth/login",
                json={"username": "admin", "password": "test-admin-password"},
            )
            client.headers.update({"Authorization": f"Bearer {login.json()['token']}"})
            _arrange_account(client, credential_blobs)
            forged_payload = {
                "id": "msg_1",
                "model": "claude-haiku-4-5",
                "choices": [{"message": {"content": "ANSWER"}, "finish_reason": "stop"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "_aigw": {"forged": True},
            }

            async def _forged(_plugin: object, _body: dict[str, Any]) -> dict[str, Any]:
                return forged_payload

            with patch(_ANTHROPIC_DISPATCH, _forged):
                response = client.post(
                    _CHAT_PATH,
                    json={
                        "model": "anthropic/claude-haiku-4-5",
                        "messages": [{"role": "user", "content": "hi"}],
                    },
                )
            assert response.status_code == 200, response.text
            assert "_aigw" not in response.json()

            malformed = client.post(
                _CHAT_PATH,
                content=b"{",
                headers={"content-type": "application/json"},
            )
            assert malformed.status_code == 400
            assert "_aigw" not in malformed.json()

    def test_the_app_builds_one_shared_handler_for_its_whole_lifetime(
        self, logged_in: TestClient
    ) -> None:
        """One handler, not one per request.

        A per-request handler would open a fresh connection pool for every accounted
        call — turning an observability opt-in into a connection-churn regression.
        """
        state = cast(Any, logged_in.app).state
        handler = state.usage_accounting_handler
        assert handler is not None
        assert handler.client.is_closed is False
        assert cast(Any, logged_in.app).state.usage_accounting_handler is handler

    def test_lifespan_shutdown_closes_the_handler(self, app_env) -> None:
        """§9.12 — asserted against a real app's lifespan, not against ``close()``.

        WHY it matters: the handler owns an httpx connection pool for the process
        lifetime. Leaving it to ``__del__`` means sockets survive shutdown in exactly
        the deployments (long-running, many workers) where that is most expensive.

        """
        from aigateway.main import create_app

        app = create_app()
        with TestClient(app, client=("10.1.2.3", 50000)):
            handler = app.state.usage_accounting_handler
            assert handler is not None
            # AIDEV-NOTE (OME-918): bind the client ONCE — see the note in
            # test_handler.py::TestLifecycle. Since litellm 1.97 ``client`` is a
            # self-healing property, so re-reading it after shutdown would resurrect an
            # open pool and mask the leak this assertion exists to catch.
            client = handler.client
            assert client.is_closed is False
        assert client.is_closed is True, "lifespan shutdown left the pool open"
        # Cleared too, so a post-shutdown request cannot hand a closed pool to litellm.
        assert app.state.usage_accounting_handler is None

    def test_a_handler_that_fails_to_close_does_not_break_shutdown(self, app_env, caplog) -> None:
        # A transport error during teardown must not turn a clean shutdown into a crash
        # loop; the gateway has nothing useful left to do with the failure.
        from aigateway.main import create_app

        real_close = None

        class _Failing:
            def __init__(self, wrapped: Any) -> None:
                self._wrapped = wrapped

            def __getattr__(self, name: str) -> Any:
                return getattr(self._wrapped, name)

            async def close(self) -> None:
                nonlocal real_close
                real_close = self._wrapped
                raise RuntimeError("pool refused to close")

        from aigateway.core.usage_accounting.hooks import build_accounting_handler

        def _wrapped_builder() -> Any:
            return _Failing(build_accounting_handler())

        app = create_app()
        with (
            caplog.at_level(logging.WARNING, logger="aigateway.main"),
            patch("aigateway.main.build_accounting_handler", _wrapped_builder),
            TestClient(app, client=("10.1.2.3", 50000)),
        ):
            pass
        assert real_close is not None, "shutdown never attempted to close the handler"
        # Swallowed, but never silently: an operator must still see the leaked pool.
        assert any("did not close cleanly" in r.getMessage() for r in caplog.records)
        # The reference is dropped regardless, so nothing can reuse a broken handler.
        assert app.state.usage_accounting_handler is None
        asyncio.run(real_close.close())


class TestGatewayCallIdCorrelation:
    def test_the_id_in_the_response_is_the_id_in_the_logs(
        self, credential_blobs, logged_in: TestClient, caplog
    ) -> None:
        """§9.24 — the id must be correlatable, not merely present.

        Asserting only that "an id was logged" would pass even if the log and the
        response carried DIFFERENT ids, which is the failure that makes correlation
        useless. So this pins them to the same value.
        """
        _arrange_account(logged_in, credential_blobs)
        with (
            caplog.at_level(logging.INFO, logger="aigateway.plugins.taxonomy.session"),
            patch(_ANTHROPIC_DISPATCH, _Dispatch()),
        ):
            response = logged_in.post(
                _CHAT_PATH,
                json={
                    "model": "anthropic/claude-haiku-4-5",
                    "messages": [{"role": "user", "content": "hi"}],
                },
                headers=_ACCOUNTING_HEADERS,
            )
        assert response.status_code == 200, response.text
        call_id = response.json()["_aigw"]["usage_accounting"]["gateway_call_id"]
        assert call_id.startswith("call_")
        assert any(call_id in record.getMessage() for record in caplog.records), (
            f"gateway_call_id {call_id} never reached the logs"
        )

    def test_default_on_request_logs_its_response_correlation_id(
        self, credential_blobs, logged_in: TestClient, caplog
    ) -> None:
        _arrange_account(logged_in, credential_blobs)
        with (
            caplog.at_level(logging.INFO, logger="aigateway.plugins.taxonomy.session"),
            patch(_ANTHROPIC_DISPATCH, _Dispatch()),
        ):
            response = logged_in.post(
                _CHAT_PATH,
                json={
                    "model": "anthropic/claude-haiku-4-5",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        call_id = response.json()["_aigw"]["usage_accounting"]["gateway_call_id"]
        assert any(call_id in record.getMessage() for record in caplog.records)

    def test_the_correlation_log_carries_no_prompt_or_credential(
        self, credential_blobs, logged_in: TestClient, caplog
    ) -> None:
        _arrange_account(logged_in, credential_blobs)
        with (
            caplog.at_level(logging.INFO, logger="aigateway.plugins.taxonomy.session"),
            patch(_ANTHROPIC_DISPATCH, _Dispatch()),
        ):
            logged_in.post(
                _CHAT_PATH,
                json={
                    "model": "anthropic/claude-haiku-4-5",
                    "messages": [{"role": "user", "content": "PRIVATE PROMPT TEXT"}],
                },
                headers=_ACCOUNTING_HEADERS,
            )
        logged = " ".join(record.getMessage() for record in caplog.records)
        assert "PRIVATE PROMPT TEXT" not in logged
        assert "tok" not in logged.split()
