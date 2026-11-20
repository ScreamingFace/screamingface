"""Where the attempt header sits in the real app (contract C7, test-plan §4 item 9).

# FEATURE: Router Recipe extension Unit 5.1 — the header layer is immediately inside the call-id
# layer, so every refusal a later layer makes still carries the count.
# INVARIANT: one counter per request survives the auth-disabled guard, which runs the route in a
# task of its own; a mounted `root_path` and an absent usage collector change nothing.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tortoise import Tortoise

from aigateway.core.auth.local_only import AuthDisabledLocalOnlyMiddleware
from aigateway.middleware import BodyCapMiddleware, CallIdMiddleware, UpstreamAttemptsMiddleware
from tests.conftest import TEST_SECRET_KEY, CredentialBlobProbe, _prepare_sqlite_db

from .conftest import CHAT, HEADER, chat_body, connect
from .litellm_seam import OPENAI_COMPLETION, FakeTransport, connect_error_then

ROOT = "/gw"


@pytest.fixture
def local_gateway(
    seam: FakeTransport,
    credential_blobs: CredentialBlobProbe,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """The local deployment shape: no login, loopback only, mounted under a path prefix."""
    del seam
    database_url = f"sqlite://{credential_blobs.db_path}"
    monkeypatch.setenv("AIGATEWAY_DATABASE_URL", database_url)
    monkeypatch.setenv("AIGATEWAY_SECRET_KEY", base64.b64encode(TEST_SECRET_KEY).decode())
    monkeypatch.setenv("AIGW_AUTH_MODE", "disabled")
    # WHY off: the count must never need the usage collector.
    monkeypatch.setenv("AIGW_TAXONOMY_ENABLED", "false")
    _prepare_sqlite_db(database_url)

    from aigateway.main import create_app

    app = create_app()
    with TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000), root_path=ROOT
    ) as test_client:
        yield connect(test_client, prefix=ROOT)
    asyncio.run(Tortoise.close_connections())


def _stack(client: TestClient) -> list[object]:
    return [middleware.cls for middleware in cast(FastAPI, client.app).user_middleware]


def test_the_header_layer_is_immediately_inside_the_call_id(client: TestClient) -> None:
    stack = _stack(client)

    assert stack[:3] == [CallIdMiddleware, UpstreamAttemptsMiddleware, BodyCapMiddleware]


def test_the_local_guard_sits_inside_the_header_layer(local_gateway: TestClient) -> None:
    stack = _stack(local_gateway)

    assert stack[:4] == [
        CallIdMiddleware,
        UpstreamAttemptsMiddleware,
        BodyCapMiddleware,
        AuthDisabledLocalOnlyMiddleware,
    ]


def test_two_sends_cross_the_local_guard_under_a_root_path(
    local_gateway: TestClient, seam: FakeTransport
) -> None:
    seam.respond = connect_error_then(OPENAI_COMPLETION)

    response = local_gateway.post(f"{ROOT}{CHAT}", json=chat_body("huggingface"))

    assert response.status_code == 200, response.text
    assert len(seam.sent) == 2
    assert response.headers[HEADER] == "2"


def test_a_local_guard_refusal_is_zero(local_gateway: TestClient, seam: FakeTransport) -> None:
    response = local_gateway.post(
        f"{ROOT}{CHAT}", json=chat_body("huggingface"), headers={"host": "example.test"}
    )

    assert response.status_code == 403, response.text
    assert seam.sent == []
    assert response.headers[HEADER] == "0"
