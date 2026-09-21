"""Local mode owns one explicit loopback AI Gateway connection."""

import pytest
from fastapi import FastAPI

from screamingface_engine.config import LOCAL_AIGATEWAY_BASE_URL, Settings
from screamingface_engine.connections.aigateway import AigatewayConnections
from screamingface_engine.local import create_local_app


def _app(**kwargs: object) -> FastAPI:
    return create_local_app(Settings(jwt_secret="s" * 32, **kwargs), env={})  # type: ignore[arg-type]


def test_local_app_automatically_wires_the_loopback_aigateway() -> None:
    app = _app()

    assert isinstance(app.state.connections, AigatewayConnections)
    assert str(app.state.connections._client.base_url) == LOCAL_AIGATEWAY_BASE_URL  # noqa: SLF001
    # INVARIANT: ONE local default, honoured by BOTH consumers. This used to assert the catalog
    # was None — the fallback was computed after the catalog had already been built from the
    # unsubstituted settings, so `/v1/models` answered 503 on the one deployment shape whose
    # address is known in advance, while `/v1/connections` on the same address answered 200
    # (OME-795).
    assert app.state.catalog is not None


def test_local_app_preserves_an_explicit_aigateway_url() -> None:
    app = _app(aigateway_base_url="http://gateway.test:9876")

    assert isinstance(app.state.connections, AigatewayConnections)
    assert str(app.state.connections._client.base_url) == "http://gateway.test:9876"  # noqa: SLF001


@pytest.mark.asyncio
async def test_local_app_closes_its_connection_client_on_shutdown() -> None:
    app = _app()
    assert isinstance(app.state.connections, AigatewayConnections)
    client = app.state.connections._client  # noqa: SLF001

    async with app.router.lifespan_context(app):
        assert not client.is_closed

    assert client.is_closed


def test_the_local_gateway_address_is_configurable() -> None:
    app = _app(local_aigateway_base_url="http://sidecar.test:9105")

    assert isinstance(app.state.connections, AigatewayConnections)
    assert str(app.state.connections._client.base_url) == "http://sidecar.test:9105"  # noqa: SLF001


def test_an_explicit_aigateway_url_outranks_the_local_default() -> None:
    """INVARIANT: one `URL4_CLOUD_AIGATEWAY_BASE_URL` still points the whole App at one gateway.

    The local default is a fallback, not an override — a developer who states the shared field
    must not have connections quietly diverge from the catalog onto a different address.
    """
    app = _app(
        aigateway_base_url="http://gateway.test:9876",
        local_aigateway_base_url="http://sidecar.test:9105",
    )

    assert isinstance(app.state.connections, AigatewayConnections)
    assert str(app.state.connections._client.base_url) == "http://gateway.test:9876"  # noqa: SLF001


def test_an_explicit_url_points_the_catalog_at_the_same_gateway_as_connections() -> None:
    """INVARIANT: the two consumers never diverge onto different gateways.

    The bug OME-795 fixed was exactly this divergence in the DEFAULT case; this pins the
    explicit case too, so a future refactor cannot restore the split from the other side.
    """
    app = _app(aigateway_base_url="http://gateway.test:9876")

    assert app.state.catalog is not None
    assert isinstance(app.state.connections, AigatewayConnections)
    assert str(app.state.connections._client.base_url) == "http://gateway.test:9876"  # noqa: SLF001


def test_the_local_gateway_address_defaults_to_loopback() -> None:
    """INVARIANT: loopback, like `LOCAL_HOST` — pinned against the literal, not the constant."""
    assert Settings(jwt_secret="s" * 32).local_aigateway_base_url == "http://127.0.0.1:9105"
    assert LOCAL_AIGATEWAY_BASE_URL == "http://127.0.0.1:9105"


def test_local_app_wires_a_mutable_adapter() -> None:
    # INVARIANT (D15, OME-1245): Local mode keeps its BYOK controls, so its adapter may write;
    # the Hosted composition root is the one that passes `mutable=False`.
    app = _app()

    assert app.state.connections._mutable is True  # noqa: SLF001
