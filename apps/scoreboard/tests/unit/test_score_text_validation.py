"""OME-1658: malformed text is a field-specific 422, never persisted or returned as 500."""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from tortoise import Tortoise
from tortoise.backends.base import executor

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent

OWNER = "alice@example.test"
PAYLOAD = {
    "benchmark_id": "text-validation",
    "spec_id": "candidate",
    "url4_expression": "url4://candidate",
    "score": 0.75,
    "total_questions": 4,
    "ran_with_providers": ["openrouter"],
}


async def _seed() -> None:
    await Tortoise.generate_schemas()
    await Benchmark.create(id="text-validation", display_name="Text validation")


@pytest.fixture(params=["sqlite", "postgres"])
def text_client(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    database_url = f"sqlite://{tmp_path / 'text.sqlite3'}"
    if request.param == "postgres":
        if not os.getenv("SCOREBOARD_TEST_DATABASE_URL"):
            pytest.skip("requires PostgreSQL")
        # WHY synchronous: resolve the fixture's asyncio.run before TestClient's loop.
        database_url = request.getfixturevalue("postgres_schema_database_url")
    # WHY: Tortoise keys cached SQL by connection/table, not database backend.
    monkeypatch.setattr(executor, "EXECUTOR_CACHE", {})
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    settings = Settings.model_validate(
        {
            "database_url": database_url,
            "cors_origins": [],
            "auth_mode": "cloudflare_headers",
            "allowed_networks": "127.0.0.1/32",
        }
    )
    with TestClient(
        create_app(settings), raise_server_exceptions=False, client=("127.0.0.1", 50000)
    ) as client:
        assert client.portal is not None
        client.portal.call(_seed)
        yield client


def _send(client: TestClient, method: str, url: str, body: object) -> Response:
    # WHY: ASCII JSON escapes carry surrogates; httpx's json= encoder rejects them locally.
    return client.request(
        method,
        url,
        content=json.dumps(body),
        headers={
            "X-User-Email": OWNER,
            "Content-Type": "application/json",
        },
    )


async def _snapshot() -> tuple[list[dict[str, Any]], int]:
    return await Score.all().values(), await ScoreMetadataEvent.all().count()


BAD_FIELDS = [
    pytest.param("authors", ["a\x00b@example.test"], id="nul-author"),
    pytest.param("authors", ["a\ud800b@example.test"], id="high-surrogate-author"),
    pytest.param("authors", ["a\udfffb@example.test"], id="low-surrogate-author"),
    pytest.param("paper_url", "https://example.test/a\x00b", id="nul-paper-url"),
    pytest.param("paper_url", "https://example.test/a\ud800b", id="surrogate-paper-url"),
    pytest.param("authors_metadata", "\ud800", id="wrong-author-metadata-shape"),
    pytest.param("paper_metadata", ["\ud800"], id="wrong-paper-metadata-shape"),
    pytest.param("authors", [{"nested": "\ud800"}], id="wrong-author-shape"),
    pytest.param("paper_metadata", {"title": "\ud800"}, id="existing-credit-validation"),
]


@pytest.mark.parametrize("field,value", BAD_FIELDS)
@pytest.mark.parametrize("method", ["submit", "resubmit", "patch"])
def test_unsafe_credit_fields_are_rejected_without_writes(
    text_client: TestClient, field: str, value: object, method: str
) -> None:
    url = "/v1/scores"
    if method != "submit":
        created = _send(text_client, "POST", url, PAYLOAD)
        assert created.status_code == 201, created.text
        if method == "patch":
            url += "/" + created.json()["id"]
    assert text_client.portal is not None
    before = text_client.portal.call(_snapshot)
    body = {field: value} if method == "patch" else {**PAYLOAD, field: value}
    response = _send(text_client, "PATCH" if method == "patch" else "POST", url, body)
    assert response.status_code == 422, response.text
    assert any(error["loc"][:2] == ["body", field] for error in response.json()["detail"])
    assert text_client.portal.call(_snapshot) == before


@pytest.mark.parametrize(
    "metadata",
    [
        {"value": "a\x00b"},
        {"value": "a\ud800b"},
        {"nested": [{"a\x00b": "value"}]},
        {"nested": [{"a\udfffb": "value"}]},
        {"nested": [["a\ud800b"]]},
        "\ud800",
    ],
)
def test_unsafe_metadata_values_keys_and_wrong_shape_are_rejected(
    text_client: TestClient, metadata: object
) -> None:
    response = _send(text_client, "POST", "/v1/scores", {**PAYLOAD, "metadata": metadata})
    assert response.status_code == 422, response.text
    assert any(error["loc"][:2] == ["body", "metadata"] for error in response.json()["detail"])
    assert text_client.portal is not None
    assert text_client.portal.call(_snapshot) == ([], 0)


@pytest.mark.parametrize("field", ["score", "unknown", "\ud800"])
def test_validation_error_can_echo_surrogates_outside_the_checked_fields(
    text_client: TestClient, field: str
) -> None:
    response = _send(text_client, "POST", "/v1/scores", {**PAYLOAD, field: {"\udfff": "\ud800"}})
    assert response.status_code == 422, response.text
    # WHY: Pydantic reports an invalid Unicode field name at the body root.
    expected_location = ["body"] if field == "\ud800" else ["body", field]
    expected_input = "\ud800" if field == "\ud800" else {"\udfff": "\ud800"}
    # WHY: strict decoding proves the response is UTF-8; matching parsed input
    # proves the rejected value survived, rather than an escape appearing elsewhere.
    detail = json.loads(response.content.decode("utf-8"))["detail"]
    [error] = [item for item in detail if item["loc"] == expected_location]
    assert error["input"] == expected_input


def test_valid_unicode_and_allowed_metadata_controls_round_trip(text_client: TestClient) -> None:
    metadata = {"é😱": ["\n\t\r\b\f", {"中文": "e\u0301"}], "flag": True, "null": None}
    created = _send(
        text_client,
        "POST",
        "/v1/scores",
        {
            **PAYLOAD,
            "authors": ["élise@example.test"],
            "paper_url": "https://example.test/论文",
            "metadata": metadata,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["metadata"] == metadata
    score_id = created.json()["id"]
    edited = _send(
        text_client,
        "PATCH",
        f"/v1/scores/{score_id}",
        {
            "authors": ["zoë@example.test"],
            "paper_url": "https://example.test/😱",
        },
    )
    assert edited.status_code == 200, edited.text
    read = text_client.get(f"/v1/public/scores/{score_id}")
    assert read.status_code == 200, read.text
    assert read.json()["paper_url"] == "https://example.test/😱"
    assert read.json()["metadata"] == metadata


def test_normal_validation_response_matches_fastapi_default() -> None:
    async def probe(count: int) -> dict[str, int]:
        return {"count": count}

    default = FastAPI()
    actual = create_app(Settings(cors_origins=[]))
    for app in (default, actual):
        app.get("/probe")(probe)
        app.router.routes.insert(0, app.router.routes.pop())
    expected = TestClient(default).get("/probe", params={"count": "é中文😱"})
    response = TestClient(actual).get("/probe", params={"count": "é中文😱"})
    assert response.status_code == expected.status_code == 422
    assert response.content == expected.content
    assert response.headers["content-type"] == expected.headers["content-type"]
