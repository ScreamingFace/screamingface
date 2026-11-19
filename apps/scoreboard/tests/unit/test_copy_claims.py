"""The frozen copy claim port and its gateway adapter (OME-1947).

Covers K-8 (the mapping fails closed), K-17 (the pair of gateway settings), and the layering of the
port (prd/score-claim.md, contracts.md K4 and K10).
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

import scoreboard.core.copy_claims as port_module
from scoreboard.config import Settings
from scoreboard.core.copy_claims import KEPT, ClaimResult
from scoreboard.gateway_copy_claims import GatewayCopyClaims, build_copy_claims

COPY = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5b"
OTHER = "ffeeddcc-bbaa-4998-8776-655443322110"
ACTOR = "claims@example.test"
BASE = "http://gateway.test"


@pytest.fixture(autouse=True)
def _no_gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SCOREBOARD_GATEWAY_URL",
        "SCOREBOARD_GATEWAY_ACTOR",
        "SCOREBOARD_GATEWAY_TIMEOUT_S",
    ):
        monkeypatch.delenv(name, raising=False)


def _sealed(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "id": COPY,
        "status": "sealed",
        "claimed_at": "2026-11-17T10:00:00+00:00",
        "already": False,
    }
    body.update(overrides)
    return body


def _coded(code: str, **extra: str) -> dict[str, object]:
    return {"detail": {"code": code, "message": "text", **extra}}


async def _claim_with(handler: Callable[[httpx.Request], httpx.Response]) -> ClaimResult:
    claims = GatewayCopyClaims(
        base_url=BASE,
        actor=ACTOR,
        timeout_s=5.0,
        transport=httpx.MockTransport(handler),
    )
    try:
        return await claims.claim(COPY)
    finally:
        await claims.aclose()


async def _answer(status: int, body: object) -> ClaimResult:
    return await _claim_with(lambda _request: httpx.Response(status, json=body))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, _sealed(), ClaimResult.CLAIMED),
        (200, _sealed(already=True), ClaimResult.ALREADY),
        (200, {key: value for key, value in _sealed().items() if key != "id"}, ClaimResult.CLAIMED),
        (404, _coded("frozen_copy_not_found"), ClaimResult.NOT_FOUND),
        (409, _coded("frozen_copy_not_sealed"), ClaimResult.NOT_SEALED),
        (410, _coded("frozen_copy_expired", state="expired"), ClaimResult.EXPIRED),
        (410, _coded("frozen_copy_expired", state="abandoned"), ClaimResult.ABANDONED),
    ],
)
async def test_each_exact_answer_maps_to_one_result(
    status: int, body: object, expected: ClaimResult
) -> None:
    assert await _answer(status, body) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, {}),
        (200, _sealed(status="open")),
        (200, _sealed(already="yes")),
        (200, _sealed(id=OTHER)),
        (200, [_sealed()]),
        (200, _sealed(already=None)),
        (200, {key: value for key, value in _sealed().items() if key != "already"}),
        (404, {"detail": "Not Found"}),
        (404, _coded("some_other_code")),
        (409, _coded("frozen_copy_not_found")),
        (410, _coded("frozen_copy_expired", state="purged")),
        (410, _coded("frozen_copy_expired")),
        (401, {"detail": "missing identity"}),
        (403, {"detail": "forbidden"}),
        (500, {"detail": "boom"}),
        (503, {}),
    ],
    ids=[
        "200-empty-body",
        "200-status-open",
        "200-already-not-bool",
        "200-other-id",
        "200-list-body",
        "200-already-null",
        "200-already-missing",
        "404-plain-detail",
        "404-other-code",
        "409-wrong-code",
        "410-unknown-state",
        "410-no-state",
        "401",
        "403",
        "500",
        "503",
    ],
)
async def test_each_other_answer_is_unavailable(status: int, body: object) -> None:
    assert await _answer(status, body) == ClaimResult.UNAVAILABLE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "text"),
    [(200, "sealed"), (500, "<html>")],
    ids=["200-text", "500-html"],
)
async def test_a_body_that_is_not_json_is_unavailable(status: int, text: str) -> None:
    result = await _claim_with(lambda _request: httpx.Response(status, text=text))
    assert result == ClaimResult.UNAVAILABLE


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ConnectTimeout, httpx.ConnectError])
async def test_a_timeout_and_a_connection_error_are_unavailable(
    error_type: type[httpx.TransportError],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("no answer", request=request)

    assert await _claim_with(handler) == ClaimResult.UNAVAILABLE


@pytest.mark.asyncio
async def test_the_request_names_the_copy_and_the_actor_and_has_no_body() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_sealed())

    claims = GatewayCopyClaims(
        base_url=BASE,
        actor=ACTOR,
        timeout_s=2.5,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert await claims.claim(COPY) == ClaimResult.CLAIMED
    finally:
        await claims.aclose()

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{BASE}/v1/frozen-copies/{COPY}/claim"
    assert request.headers["X-User-Email"] == ACTOR
    assert request.content == b""
    assert request.extensions["timeout"]["read"] == 2.5


def test_the_port_names_seven_results_and_keeps_two() -> None:
    assert {result.value for result in ClaimResult} == {
        "claimed",
        "already",
        "not_sealed",
        "abandoned",
        "expired",
        "not_found",
        "unavailable",
    }
    assert KEPT == {ClaimResult.CLAIMED, ClaimResult.ALREADY}


def test_the_port_imports_no_adapter_model_or_route() -> None:
    tree = ast.parse(Path(port_module.__file__).read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")

    forbidden = (
        "httpx",
        "fastapi",
        "tortoise",
        "scoreboard.scores",
        "scoreboard.routes",
        "scoreboard.gateway_copy_claims",
    )
    for name in imported:
        assert not name.startswith(forbidden), name


@pytest.mark.parametrize("actor", ["", "   "])
def test_a_gateway_url_with_no_actor_stops_the_start(actor: str) -> None:
    with pytest.raises(ValidationError, match="SCOREBOARD_GATEWAY_ACTOR"):
        Settings.model_validate({"gateway_url": BASE, "gateway_actor": actor})


def test_a_gateway_url_with_an_actor_is_accepted() -> None:
    settings = Settings.model_validate({"gateway_url": BASE + "/", "gateway_actor": ACTOR})

    assert settings.gateway_url == BASE
    assert settings.gateway_actor == ACTOR
    assert settings.gateway_timeout_s == 5.0


def test_a_blank_gateway_url_is_no_url_and_a_padded_one_is_trimmed() -> None:
    blank = Settings.model_validate({"gateway_url": "  "})

    assert blank.gateway_url == ""

    padded = Settings.model_validate(
        {"gateway_url": " http://gateway.test/ ", "gateway_actor": ACTOR}
    )

    assert padded.gateway_url == BASE


def test_no_gateway_url_is_the_default_and_builds_no_client() -> None:
    settings = Settings.model_validate({})

    assert settings.gateway_url == ""
    assert settings.gateway_actor == ""
    assert build_copy_claims(settings) is None


def test_the_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCOREBOARD_GATEWAY_URL", BASE)
    monkeypatch.setenv("SCOREBOARD_GATEWAY_ACTOR", ACTOR)
    monkeypatch.setenv("SCOREBOARD_GATEWAY_TIMEOUT_S", "2.5")

    settings = Settings()

    assert settings.gateway_url == BASE
    assert settings.gateway_actor == ACTOR
    assert settings.gateway_timeout_s == 2.5


def test_a_timeout_of_zero_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"gateway_timeout_s": 0})


@pytest.mark.asyncio
async def test_a_gateway_url_builds_the_gateway_client() -> None:
    settings = Settings.model_validate({"gateway_url": BASE, "gateway_actor": ACTOR})

    claims = build_copy_claims(settings)

    assert claims is not None
    assert isinstance(claims, GatewayCopyClaims)
    await claims.aclose()
