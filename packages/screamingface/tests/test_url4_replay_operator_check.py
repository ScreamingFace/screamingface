"""A raw url4 replay checks the operator catalog before any spend (OME-1289, unit 12 H1).

`Client.evaluate("<url4>")` never built a Recipe, so the catalog gate that Recipes pass through
did not run. A replayed reducer url4 that pins an operator this Engine lacks paid every member
call and then failed with `combine_operator_unknown`.
"""

from __future__ import annotations

from typing import NoReturn

import httpx
import pytest
from _reducer_fixtures import fixture_operators, operators_response, reducer_fusion
from test_client_run import _AsyncReplayTransport, _ReplayTransport
from url4 import expr, render, src, text

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import Candidate

_BASE = "https://engine.example"


def _replay(candidate_url4: str) -> str:
    return render(
        expr(
            src(text(candidate_url4), name="candidate", weight=0.0),
            src("fixture", name="result", weight=0.0),
            intent=text("$result"),
        )
    )


_REDUCER = compile_candidate(reducer_fusion(), operators=fixture_operators()).url4
_PLAIN = compile_candidate(sf.Model("provider/opus", prompt="Answer.")).url4
assert _REDUCER is not None
assert _PLAIN is not None
assert "mode@1" in _REDUCER
VALID_REDUCER_REPLAY = _replay(_REDUCER)
UNKNOWN_OPERATOR_REPLAY = _replay(_REDUCER.replace("mode@1", "mode@9"))
UNPINNED_OPERATOR_REPLAY = _replay(_REDUCER.replace("mode@1", "mode"))
WRONG_STAGE_REPLAY = _replay(_REDUCER.replace("mode@1", "numeric@1"))
PLAIN_REPLAY = _replay(_PLAIN)


class _ForbiddenTransport:
    called = False

    def run(self, candidate: Candidate, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("an unknown operator must fail before execution")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


class _AsyncForbiddenTransport(_ForbiddenTransport):
    async def run(self, candidate: Candidate, on_event: object) -> NoReturn:
        return super().run(candidate, on_event)

    async def cancel_active(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _engine(paths: list[str], *, catalog: httpx.Response | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/operators":
            return catalog if catalog is not None else operators_response()
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_replaying_an_unknown_pinned_operator_fails_before_the_run() -> None:
    paths: list[str] = []
    transport = _ForbiddenTransport()

    with (
        sf.Client(
            engine_url=_BASE, http_transport=_engine(paths), run_transport=transport
        ) as client,
        pytest.raises(ValueError, match="reduce operator 'mode@9' is not in this SF Engine's"),
    ):
        client.evaluate(UNKNOWN_OPERATOR_REPLAY, progress=False)

    assert transport.called is False
    assert paths == ["/v1/operators"]


def test_replaying_an_unpinned_operator_name_fails_before_the_run() -> None:
    transport = _ForbiddenTransport()

    with (
        sf.Client(engine_url=_BASE, http_transport=_engine([]), run_transport=transport) as client,
        pytest.raises(ValueError, match="names operator 'mode' without a version"),
    ):
        client.evaluate(UNPINNED_OPERATOR_REPLAY, progress=False)

    assert transport.called is False


def test_replaying_an_operator_pinned_in_the_wrong_stage_fails_before_the_run() -> None:
    transport = _ForbiddenTransport()

    with (
        sf.Client(engine_url=_BASE, http_transport=_engine([]), run_transport=transport) as client,
        pytest.raises(ValueError, match="operator 'numeric@1' is a normalize operator, not a"),
    ):
        client.evaluate(WRONG_STAGE_REPLAY, progress=False)

    assert transport.called is False


def test_replaying_against_an_engine_without_a_catalog_is_a_capability_error() -> None:
    transport = _ForbiddenTransport()

    with (
        sf.Client(
            engine_url=_BASE,
            http_transport=_engine([], catalog=httpx.Response(404)),
            run_transport=transport,
        ) as client,
        pytest.raises(sf.EngineCapabilityError) as caught,
    ):
        client.evaluate(VALID_REDUCER_REPLAY, progress=False)

    assert caught.value.code == "engine_capability_missing"
    assert caught.value.details == {"path": "/v1/operators"}
    assert transport.called is False


def test_replaying_a_plain_url4_never_requests_the_catalog() -> None:
    paths: list[str] = []
    transport = _ReplayTransport()

    with sf.Client(
        engine_url=_BASE, http_transport=_engine(paths), run_transport=transport
    ) as client:
        client.evaluate(PLAIN_REPLAY, progress=False)

    assert transport.candidate is not None
    assert paths == []


def test_replaying_a_valid_reducer_url4_checks_the_catalog_once_then_runs() -> None:
    paths: list[str] = []
    transport = _ReplayTransport()

    with sf.Client(
        engine_url=_BASE, http_transport=_engine(paths), run_transport=transport
    ) as client:
        client.evaluate(VALID_REDUCER_REPLAY, progress=False)
        client.evaluate(VALID_REDUCER_REPLAY, progress=False)

    assert transport.candidate is not None
    assert transport.candidate.url4 == VALID_REDUCER_REPLAY
    assert paths == ["/v1/operators"]


@pytest.mark.asyncio
async def test_async_replaying_an_unknown_pinned_operator_fails_before_the_run() -> None:
    paths: list[str] = []
    transport = _AsyncForbiddenTransport()
    client = sf.AsyncClient(
        engine_url=_BASE, http_transport=_engine(paths), run_transport=transport
    )

    with pytest.raises(ValueError, match="reduce operator 'mode@9' is not in this SF Engine's"):
        await client.evaluate(UNKNOWN_OPERATOR_REPLAY, progress=False)
    await client.aclose()

    assert transport.called is False
    assert paths == ["/v1/operators"]


@pytest.mark.asyncio
async def test_async_replaying_an_unpinned_operator_name_fails_before_the_run() -> None:
    transport = _AsyncForbiddenTransport()
    client = sf.AsyncClient(engine_url=_BASE, http_transport=_engine([]), run_transport=transport)

    with pytest.raises(ValueError, match="names operator 'mode' without a version"):
        await client.evaluate(UNPINNED_OPERATOR_REPLAY, progress=False)
    await client.aclose()

    assert transport.called is False


@pytest.mark.asyncio
async def test_async_replaying_against_an_engine_without_a_catalog_is_a_capability_error() -> None:
    transport = _AsyncForbiddenTransport()
    client = sf.AsyncClient(
        engine_url=_BASE,
        http_transport=_engine([], catalog=httpx.Response(404)),
        run_transport=transport,
    )

    with pytest.raises(sf.EngineCapabilityError) as caught:
        await client.evaluate(VALID_REDUCER_REPLAY, progress=False)
    await client.aclose()

    assert caught.value.code == "engine_capability_missing"
    assert transport.called is False


@pytest.mark.asyncio
async def test_async_replaying_a_valid_reducer_url4_checks_the_catalog_then_runs() -> None:
    paths: list[str] = []
    transport = _AsyncReplayTransport()
    client = sf.AsyncClient(
        engine_url=_BASE, http_transport=_engine(paths), run_transport=transport
    )

    await client.evaluate(VALID_REDUCER_REPLAY, progress=False)
    await client.aclose()

    assert transport.candidate is not None
    assert paths == ["/v1/operators"]
