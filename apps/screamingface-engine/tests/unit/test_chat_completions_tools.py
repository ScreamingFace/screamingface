"""The route side of tools on POST /v1/chat/completions: TC-18, TC-19, TC-23, TC-S7 and TC-S11.

FEATURE: chat-completions with tools (prd/tool-calls.md). With `tools` in the request, the route
checks the recipe with tools, refuses a final step that asks for a search it cannot do (TC-S11),
and asks the caller's catalogue (GET /v1/models) whether each final model lists `tools` in its
`supported_parameters` (TC-S10). Each refusal comes before the input write and the run.
`tools: []` is no tools (TC-S13). A malformed tool is 400 `invalid_request` with param `tools`.
"""

from __future__ import annotations

from typing import Any

import pytest
from _chat_app import (
    ChatApp,
    ToolCatalog,
    answered,
    body,
    chat_app,
    error,
    post,
    stored_record,
)
from _chat_corpus import corpus
from _chat_tools_reachable import tools_reachable  # noqa: F401

from screamingface_engine.catalog.port import CatalogUnavailable
from screamingface_engine.chat.recipe import (
    FINAL_SEARCH_MESSAGE,
    FINAL_STEP_NOT_MODEL_MESSAGE,
    UNKNOWN_FINAL_MESSAGE,
    RepointError,
    one_model_recipe,
)
from screamingface_engine.rest import chat_tools
from screamingface_engine.rest.chat_model import CATALOG_RETRY_AFTER_S, catalog_unavailable
from url4 import RelExpr, expr, render, src, text

pytestmark = pytest.mark.asyncio

TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "The weather of a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}
_REDUCER_FINAL = "surface_parity:S1"
_SEARCH_MESSAGE = "with tools, a final step cannot search on this model route"


def _fusion(
    member: str = "/prov/b",
    synthesis: str = "/prov/a",
    params: tuple[tuple[str, str], ...] = (),
) -> str:
    """Two members on `member` and a model synthesis on `synthesis` with `params`."""
    return render(
        expr(
            src(
                RelExpr(path=member, context="$input", intent=text("Answer A")),
                name="model_1",
                weight=0.0,
            ),
            src(
                RelExpr(path=member, context="$input", intent=text("Answer B")),
                name="model_2",
                weight=0.0,
            ),
            src(
                RelExpr(
                    path=synthesis,
                    context="$model_1 $model_2",
                    intent=text("Merge"),
                    params=params,
                ),
                name="synthesis_1",
                weight=0.0,
            ),
            intent=text("$synthesis_1"),
        )
    )


def _catalog(ca: ChatApp) -> ToolCatalog:
    catalog = ca.app.state.catalog
    if not isinstance(catalog, ToolCatalog):
        raise AssertionError("the App has no fake catalogue")
    return catalog


def _tools_app(**supported: list[str]) -> ChatApp:
    return chat_app(
        answered(),
        known=("prov/a", "prov/b", "prov/c"),
        catalog=ToolCatalog(
            {"prov/a": ["tools", "temperature"], "prov/b": ["temperature"], **supported}
        ),
    )


def _assert_refused_before_run(ca: ChatApp) -> None:
    assert ca.runner.attempted == []
    assert ca.objects.objects == {}


async def _assert_no_tool_support(model: str, named: str) -> None:
    """A request with tools on `model` is 400 model_does_not_support_tools naming `named`."""
    ca = _tools_app()
    resp = await post(ca.app, body(model, tools=[TOOL]))
    assert resp.status_code == 400
    assert resp.headers["x-should-retry"] == "false"
    envelope = error(resp)
    assert envelope["code"] == "model_does_not_support_tools"
    assert envelope["param"] == "model"
    assert envelope["type"] == "invalid_request_error"
    assert named in envelope["message"]
    _assert_refused_before_run(ca)
    assert len(_catalog(ca).calls) == 1


async def test_model_without_tool_support_is_400_before_the_run() -> None:
    """TC-18: the catalogue check at the route, on the final model steps only."""
    await _assert_no_tool_support("prov/b", "prov/b")
    await _assert_no_tool_support(_fusion(member="/prov/a", synthesis="/prov/b"), "prov/b")
    await _assert_no_tool_support("prov/c", "prov/c")

    ca = _tools_app()
    resp = await post(ca.app, body("prov/a", tools=[TOOL]))
    assert resp.status_code == 200
    assert ca.runner.scheduled[0]["url4"] == one_model_recipe("prov/a")

    ca = _tools_app()
    fusion = _fusion(member="/prov/b", synthesis="/prov/a")
    resp = await post(ca.app, body(fusion, tools=[TOOL]))
    assert resp.status_code == 200
    assert ca.runner.scheduled[0]["url4"] == fusion


async def test_model_id_with_colon_is_checked_in_route_form() -> None:
    """The catalogue lists the route form (`~` for `:`); the message names the gateway id."""
    ca = chat_app(
        answered(),
        known=("prov/a:free", "prov/b~free"),
        catalog=ToolCatalog({"prov/a:free": ["tools"], "prov/b:free": []}),
    )
    assert (await post(ca.app, body("prov/a:free", tools=[TOOL]))).status_code == 200
    resp = await post(ca.app, body("prov/b~free", tools=[TOOL]))
    assert resp.status_code == 400
    assert error(resp)["code"] == "model_does_not_support_tools"
    assert "prov/b:free" in error(resp)["message"]


async def test_no_catalogue_with_tools_is_503_catalog_unavailable() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body("prov/a", tools=[TOOL]))
    assert resp.status_code == 503
    assert "retry-after" not in resp.headers
    assert resp.headers["x-should-retry"] == "false"
    assert error(resp)["code"] == "catalog_unavailable"
    _assert_refused_before_run(ca)


async def test_catalogue_failure_with_tools_is_503_with_retry_after() -> None:
    ca = chat_app(
        answered(), catalog=ToolCatalog({"prov/a": ["tools"]}, error=CatalogUnavailable())
    )
    resp = await post(ca.app, body("prov/a", tools=[TOOL]))
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "5"
    assert resp.headers["x-should-retry"] == "true"
    assert error(resp)["code"] == "catalog_unavailable"
    _assert_refused_before_run(ca)


def test_catalog_unavailable_gives_the_two_outage_answers() -> None:
    """One rule for a catalogue outage: no catalogue is final, a failed fetch can be retried."""
    final = catalog_unavailable(retry=False)
    assert (final.status, final.code, final.retry_after, final.should_retry) == (
        503,
        "catalog_unavailable",
        None,
        False,
    )
    transient = catalog_unavailable(retry=True)
    assert (transient.status, transient.code, transient.retry_after, transient.should_retry) == (
        503,
        "catalog_unavailable",
        CATALOG_RETRY_AFTER_S,
        True,
    )


async def test_the_catalogue_is_fetched_once_per_request() -> None:
    ca = chat_app(
        answered(),
        catalog=ToolCatalog({"prov/math": ["tools"], "prov/coder": ["tools"], "prov/general": []}),
    )
    resp = await post(ca.app, body(corpus()["keyword_router.url4"], tools=[TOOL]))
    assert resp.status_code == 400
    assert error(resp)["code"] == "model_does_not_support_tools"
    assert "prov/general" in error(resp)["message"]
    assert len(_catalog(ca).calls) == 1
    _assert_refused_before_run(ca)


async def test_streamed_request_is_refused_as_json_before_the_stream() -> None:
    ca = _tools_app()
    resp = await post(ca.app, body("prov/b", tools=[TOOL], stream=True))
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/json")
    assert error(resp)["code"] == "model_does_not_support_tools"
    _assert_refused_before_run(ca)


async def test_empty_tools_list_follows_no_tools_path() -> None:
    """TC-19: `tools: []` is no tools: a reducer final runs, and no catalogue is asked."""
    ca = chat_app(answered(), catalog=ToolCatalog({}))
    resp = await post(ca.app, body(corpus()[_REDUCER_FINAL], tools=[]))
    assert resp.status_code == 200
    assert _catalog(ca).calls == []
    assert len(ca.runner.scheduled) == 1
    assert "tools" not in stored_record(ca.runner.inputs[0])


@pytest.mark.parametrize(
    "tools",
    [
        pytest.param([{"type": "function", "function": {"description": "x"}}], id="no-name"),
        pytest.param([{"type": "function", "function": {"name": ""}}], id="empty-name"),
        pytest.param([TOOL, TOOL], id="name-twice"),
        pytest.param([{"type": "retrieval", "function": {"name": "read"}}], id="not-function"),
        pytest.param([{"type": "function"}], id="no-function"),
    ],
)
async def test_malformed_tools_are_400_with_param(tools: list[dict[str, Any]]) -> None:
    """TC-23 (TC-S12): each malformed tool list is 400 invalid_request with param `tools`."""
    ca = _tools_app()
    resp = await post(ca.app, body("prov/a", tools=tools))
    assert resp.status_code == 400
    envelope = error(resp)
    assert envelope["code"] == "invalid_request"
    assert envelope["param"] == "tools"
    _assert_refused_before_run(ca)
    assert _catalog(ca).calls == []


async def test_reducer_final_with_tools_is_400_final_step_not_model() -> None:
    """TC-S7: a recipe that ends in a reducer is refused with tools, with the hint."""
    ca = chat_app(answered(), catalog=ToolCatalog({}))
    resp = await post(ca.app, body(corpus()[_REDUCER_FINAL], tools=[TOOL]))
    assert resp.status_code == 400
    envelope = error(resp)
    assert envelope["code"] == "final_step_not_model"
    assert envelope["message"] == FINAL_STEP_NOT_MODEL_MESSAGE
    assert envelope["param"] == "model"
    _assert_refused_before_run(ca)
    assert _catalog(ca).calls == []


async def test_explicit_web_search_on_engine_tool_route_is_refused() -> None:
    """TC-S11: the final step asks for a search that only the Engine tool loop can do."""
    ca = _tools_app()
    search = _fusion(synthesis="/prov/a", params=(("web_search", "true"),))
    resp = await post(ca.app, body(search, tools=[TOOL]))
    assert resp.status_code == 400
    envelope = error(resp)
    assert envelope["code"] == "recipe_not_supported"
    assert envelope["message"] == _SEARCH_MESSAGE
    assert envelope["message"] == FINAL_SEARCH_MESSAGE
    assert envelope["param"] == "model"
    assert _catalog(ca).calls == []
    _assert_refused_before_run(ca)


@pytest.mark.parametrize(
    ("synthesis", "params"),
    [
        pytest.param("/openrouter/prov/x", (("web_search", "true"),), id="native-search"),
        pytest.param("/prov/a", (), id="no-web-search"),
        pytest.param("/prov/a", (("web_search", "false"),), id="search-off"),
    ],
)
async def test_final_step_search_that_the_route_can_do_is_not_refused(
    synthesis: str, params: tuple[tuple[str, str], ...]
) -> None:
    """TC-S11, the other half: provider search, or no search asked, runs with client tools."""
    ca = _tools_app(**{"openrouter/prov/x": ["tools"]})
    member_search = _fusion(member="/prov/b", synthesis=synthesis, params=params)
    resp = await post(ca.app, body(member_search, tools=[TOOL]))
    assert resp.status_code == 200
    assert ca.runner.scheduled[0]["url4"] == member_search


async def test_recipe_that_fails_the_repoint_proof_is_400_before_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The App runs the re-point proof of the worker, so a recipe that fails it gets no blob and
    no run: 400 recipe_not_supported, not a 502 internal_error from the worker."""

    def _fails(*_args: Any) -> str:
        raise RepointError("the re-point changed the shape of the recipe")

    monkeypatch.setattr(chat_tools, "repoint_final_steps", _fails)
    ca = _tools_app()
    resp = await post(ca.app, body("prov/a", tools=[TOOL]))
    assert resp.status_code == 400
    assert resp.headers["x-should-retry"] == "false"
    envelope = error(resp)
    assert envelope["code"] == "recipe_not_supported"
    assert envelope["message"] == UNKNOWN_FINAL_MESSAGE
    assert envelope["param"] == "model"
    assert ca.runner.scheduled == []
    assert _catalog(ca).calls == []
    _assert_refused_before_run(ca)


async def test_member_web_search_is_not_a_final_step_search() -> None:
    """Only final steps are checked: a member that searches on an Engine tool route runs."""
    ca = _tools_app()
    recipe = render(
        expr(
            src(
                RelExpr(
                    path="/prov/b",
                    context="$input",
                    intent=text("Find"),
                    params=(("web_search", "true"),),
                ),
                name="model_1",
                weight=0.0,
            ),
            src(
                RelExpr(path="/prov/a", context="$model_1", intent=text("Answer")),
                name="model_2",
                weight=0.0,
            ),
            intent=text("$model_2"),
        )
    )
    resp = await post(ca.app, body(recipe, tools=[TOOL]))
    assert resp.status_code == 200
