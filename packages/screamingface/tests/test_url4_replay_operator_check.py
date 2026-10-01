"""A raw url4 replay checks the operator catalog before any spend (OME-1289, unit 12 H1).

`Client.evaluate("<url4>")` never built a Recipe, so the catalog gate that Recipes pass through
did not run. A replayed reducer url4 that pins an operator this Engine lacks paid every member
call and then failed with `combine_operator_unknown`.
"""

from __future__ import annotations

from typing import NoReturn

import httpx
import pytest
from _combine_contract import requires_engine_app
from _reducer_fixtures import fixture_operators, operators_response, reducer_fusion
from test_client_run import _AsyncReplayTransport, _ReplayTransport
from test_corrective_vote_contract_fixture import corrective_vote_url4
from url4 import expr, render, src, text

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import Candidate

_BASE = "https://engine.example"
_UNPINNED = ["mode", "mode@01", "Mode@1"]


def _replay(candidate_url4: str | None) -> str:
    assert candidate_url4 is not None
    return render(
        expr(
            src(text(candidate_url4), name="candidate", weight=0.0),
            src("fixture", name="result", weight=0.0),
            intent=text("$result"),
        )
    )


def _reducer_replay(operator: str = "mode@1") -> str:
    """A Fusion reducer replay whose reduce operator is ``operator`` (hand-edited when changed)."""
    url4 = compile_candidate(reducer_fusion(), operators=fixture_operators()).url4
    assert url4 is not None and "mode@1" in url4
    return _replay(url4.replace("mode@1", operator))


def _corrective_replay(operator: str = "mode@1") -> str:
    url4 = corrective_vote_url4()
    assert "mode@1" in url4
    return _replay(url4.replace("mode@1", operator))


def _plain_replay() -> str:
    return _replay(compile_candidate(sf.Model("provider/opus", prompt="Answer.")).url4)


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


def _engine(
    paths: list[str], *, catalog: httpx.Response | None = None, unreachable: bool = False
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path != "/v1/operators":
            return httpx.Response(404)
        if unreachable:
            raise httpx.ConnectError("refused", request=request)
        return catalog if catalog is not None else operators_response()

    return httpx.MockTransport(handler)


def _client(
    paths: list[str],
    transport: _ForbiddenTransport | _ReplayTransport,
    **engine: object,
) -> sf.Client:
    return sf.Client(
        engine_url=_BASE,
        http_transport=_engine(paths, **engine),  # type: ignore[arg-type]
        run_transport=transport,
    )


def _async_client(
    paths: list[str],
    transport: _AsyncForbiddenTransport | _AsyncReplayTransport,
    **engine: object,
) -> sf.AsyncClient:
    return sf.AsyncClient(
        engine_url=_BASE,
        http_transport=_engine(paths, **engine),  # type: ignore[arg-type]
        run_transport=transport,
    )


def test_replaying_an_unknown_pinned_operator_fails_before_the_run() -> None:
    paths: list[str] = []
    transport = _ForbiddenTransport()

    with (
        _client(paths, transport) as client,
        pytest.raises(ValueError, match="reduce operator 'mode@9' is not in this SF Engine's"),
    ):
        client.evaluate(_reducer_replay("mode@9"), progress=False)

    assert transport.called is False
    assert paths == ["/v1/operators"]


@requires_engine_app
def test_replaying_a_corrective_loop_with_an_unknown_pinned_operator_fails_before_the_run() -> None:
    paths: list[str] = []
    transport = _ForbiddenTransport()

    with (
        _client(paths, transport) as client,
        pytest.raises(ValueError, match="reduce operator 'mode@9' is not in this SF Engine's"),
    ):
        client.evaluate(_corrective_replay("mode@9"), progress=False)

    assert transport.called is False
    assert paths == ["/v1/operators"]


@pytest.mark.parametrize("operator", _UNPINNED)
def test_replaying_an_unpinned_operator_fails_before_any_request(operator: str) -> None:
    paths: list[str] = []
    transport = _ForbiddenTransport()

    with (
        _client(paths, transport) as client,
        pytest.raises(ValueError, match=f"reduce operator '{operator}' is not a pinned id"),
    ):
        client.evaluate(_reducer_replay(operator), progress=False)

    assert transport.called is False
    assert paths == []


# WHY no `Mode@1` here: the corrective vote spec is rebuilt first and refuses it earlier, with its
# own message; the claim is only that the pinned form is refused alike, before any request.
@requires_engine_app
@pytest.mark.parametrize("operator", ["mode", "mode@01"])
def test_a_corrective_loop_and_a_fusion_refuse_an_unpinned_operator_alike(operator: str) -> None:
    paths: list[str] = []
    transport = _ForbiddenTransport()

    with (
        _client(paths, transport) as client,
        pytest.raises(ValueError, match=f"reduce operator '{operator}' is not a pinned id"),
    ):
        client.evaluate(_corrective_replay(operator), progress=False)

    assert transport.called is False
    assert paths == []


def test_replaying_an_operator_pinned_in_the_wrong_stage_fails_before_the_run() -> None:
    transport = _ForbiddenTransport()

    with (
        _client([], transport) as client,
        pytest.raises(ValueError, match="operator 'numeric@1' is a normalize operator, not a"),
    ):
        client.evaluate(_reducer_replay("numeric@1"), progress=False)

    assert transport.called is False


def test_replaying_against_an_engine_without_a_catalog_is_a_capability_error() -> None:
    transport = _ForbiddenTransport()

    with (
        _client([], transport, catalog=httpx.Response(404)) as client,
        pytest.raises(sf.EngineCapabilityError) as caught,
    ):
        client.evaluate(_reducer_replay(), progress=False)

    assert caught.value.code == "engine_capability_missing"
    assert caught.value.details == {"path": "/v1/operators"}
    assert transport.called is False


def test_replaying_while_the_catalog_is_unreachable_is_an_engine_unavailable_error() -> None:
    transport = _ForbiddenTransport()

    with (
        _client([], transport, unreachable=True) as client,
        pytest.raises(sf.EngineUnavailableError) as caught,
    ):
        client.evaluate(_reducer_replay(), progress=False)

    assert "operator catalog" in caught.value.message
    assert transport.called is False


def test_replaying_a_plain_url4_never_requests_the_catalog() -> None:
    paths: list[str] = []
    transport = _ReplayTransport()

    with _client(paths, transport) as client:
        client.evaluate(_plain_replay(), progress=False)

    assert transport.candidate is not None
    assert paths == []


def test_replaying_a_valid_reducer_url4_checks_the_catalog_once_then_runs() -> None:
    paths: list[str] = []
    transport = _ReplayTransport()
    replay = _reducer_replay()

    with _client(paths, transport) as client:
        client.evaluate(replay, progress=False)
        client.evaluate(replay, progress=False)

    assert transport.candidate is not None
    assert transport.candidate.url4 == replay
    assert paths == ["/v1/operators"]


@pytest.mark.asyncio
async def test_async_replaying_an_unknown_pinned_operator_fails_before_the_run() -> None:
    paths: list[str] = []
    transport = _AsyncForbiddenTransport()

    async with _async_client(paths, transport) as client:
        with pytest.raises(ValueError, match="reduce operator 'mode@9' is not in this SF Engine's"):
            await client.evaluate(_reducer_replay("mode@9"), progress=False)

    assert transport.called is False
    assert paths == ["/v1/operators"]


@pytest.mark.asyncio
async def test_async_replaying_an_unpinned_operator_fails_before_any_request() -> None:
    paths: list[str] = []
    transport = _AsyncForbiddenTransport()

    async with _async_client(paths, transport) as client:
        with pytest.raises(ValueError, match="reduce operator 'mode' is not a pinned id"):
            await client.evaluate(_reducer_replay("mode"), progress=False)

    assert transport.called is False
    assert paths == []


@pytest.mark.asyncio
async def test_async_replaying_against_an_engine_without_a_catalog_is_a_capability_error() -> None:
    transport = _AsyncForbiddenTransport()

    async with _async_client([], transport, catalog=httpx.Response(404)) as client:
        with pytest.raises(sf.EngineCapabilityError) as caught:
            await client.evaluate(_reducer_replay(), progress=False)

    assert caught.value.code == "engine_capability_missing"
    assert transport.called is False


@pytest.mark.asyncio
async def test_async_replaying_while_the_catalog_is_unreachable_is_unavailable() -> None:
    transport = _AsyncForbiddenTransport()

    async with _async_client([], transport, unreachable=True) as client:
        with pytest.raises(sf.EngineUnavailableError):
            await client.evaluate(_reducer_replay(), progress=False)

    assert transport.called is False


@pytest.mark.asyncio
async def test_async_replaying_a_valid_reducer_url4_checks_the_catalog_then_runs() -> None:
    paths: list[str] = []
    transport = _AsyncReplayTransport()

    async with _async_client(paths, transport) as client:
        await client.evaluate(_reducer_replay(), progress=False)

    assert transport.candidate is not None
    assert paths == ["/v1/operators"]
