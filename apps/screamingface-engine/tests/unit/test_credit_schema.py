"""Credit clients receive the same provider grammar enforced at runtime."""

from unittest.mock import AsyncMock

import httpx
import pytest

from screamingface_engine.app import create_app
from screamingface_engine.config import Settings


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/v1/credits/{provider}"),
        ("put", "/v1/credits/{provider}/management-key"),
        ("delete", "/v1/credits/{provider}/management-key"),
    ],
)
def test_credit_provider_schema_documents_runtime_grammar(method, path):
    schema = create_app(Settings(jwt_secret="test-secret")).openapi()
    parameter = next(
        item
        for item in schema["paths"][path][method]["parameters"]
        if item["name"] == "provider" and item["in"] == "path"
    )
    assert parameter["required"] is True
    assert parameter["schema"]["type"] == "string"
    assert parameter["schema"]["maxLength"] == 100
    assert parameter["schema"]["pattern"] == "^[a-z0-9][a-z0-9_-]*$"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["Bad!", "a" * 101, "_invalid"])
async def test_documented_provider_rejection_precedes_credit_service(provider):
    credits = AsyncMock()
    app = create_app(Settings(jwt_secret="test-secret"), credits=credits)
    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.ASGITransport(app)
    ) as client:
        for method, suffix in (
            ("GET", ""),
            ("PUT", "/management-key"),
            ("DELETE", "/management-key"),
        ):
            response = await client.request(
                method,
                f"/v1/credits/{provider}{suffix}",
                json={"api_key": "test-key"} if method == "PUT" else None,
            )
            assert response.status_code == 422
    assert credits.mock_calls == []
