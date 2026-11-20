"""The model stage of POST /v1/chat/completions: CC-5..CC-9, CC-32, CC-40 and CC-43.

FEATURE: chat-completions. A `model` value that starts with "(" after white space is a URL4: it runs
as sent, with no catalogue lookup (CC-6), or it is refused (CC-8, CC-9, CC-32). Any other value is a
gateway model id: it becomes the one-model recipe (CC-5), it is looked up with the value as sent
(CC-7, CC-40), and a positive answer is kept for 60 s per caller (CC-43).
Owner decisions: Q5 (a lookup that is not 2xx is 404 model_not_found; no source is a 503 without
Retry-After) and Q6 (a URL4 runs as built; no catalogue lookup of its routes in U4).
"""

from __future__ import annotations

import pytest
from _chat_app import (
    MODEL,
    ChatApp,
    LookupSource,
    answered,
    body,
    chat_app,
    error,
    post,
)
from _chat_corpus import corpus

from screamingface_engine.catalog.port import (
    CatalogBadResponse,
    CatalogUnavailable,
    ModelNotInstalled,
)
from screamingface_engine.chat.recipe import LINKED_EXPRESSION_MESSAGE, one_model_recipe
from url4 import RelExpr, expr, render, src, text

pytestmark = pytest.mark.asyncio

_OTHER_USER = {"X-User-Email": "other@example.com"}
_CORRECTIVE_LOOP = (
    "(loop_candidate:0.0:(model_1:0.0:/prov/a($input)!'x')!'$model_1')!'$loop_candidate'"
)


def _fusion() -> str:
    """A benchmark-style URL4: two members on one route, then a synthesis over both."""
    return render(
        expr(
            src(
                RelExpr(path="/prov/a", context="$input", intent=text("Answer A")),
                name="model_1",
                weight=0.0,
            ),
            src(
                RelExpr(path="/prov/a", context="$input", intent=text("Answer B")),
                name="model_2",
                weight=0.0,
            ),
            src(
                RelExpr(path="/prov/b", context="$model_1 $model_2", intent=text("Merge")),
                name="synthesis_1",
                weight=0.0,
            ),
            intent=text("$synthesis_1"),
        )
    )


def _source(ca: ChatApp) -> LookupSource:
    """The fake model-parameter source of `ca`; every test here builds the App with one."""
    if ca.source is None:
        raise AssertionError("the App has no model-parameter source")
    return ca.source


async def test_gateway_model_id_becomes_one_model_recipe_without_instruction() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body())
    assert resp.status_code == 200
    expected = "(model_1:0.0:/prov/a($input)!'')!'$model_1'"
    assert one_model_recipe("prov/a") == expected
    assert ca.runner.scheduled[0]["url4"] == expected
    assert _source(ca).calls == ["prov/a"]


async def test_candidate_url4_is_used_unchanged() -> None:
    value = "  " + _fusion()
    ca = chat_app(answered())
    resp = await post(ca.app, body(value))
    assert resp.status_code == 200
    assert ca.runner.scheduled[0]["url4"] == value
    assert _source(ca).calls == []


@pytest.mark.parametrize(
    ("model", "known", "catalog_error", "unknown_status", "calls"),
    [
        pytest.param("prov/zzz", (MODEL,), None, 404, ["prov/zzz"], id="not-in-catalogue"),
        pytest.param(MODEL, (MODEL,), ModelNotInstalled(), 404, [MODEL], id="not-installed"),
        pytest.param("prov/zzz", (MODEL,), None, 500, ["prov/zzz"], id="lookup-status-500"),
        pytest.param("/prov/a", (MODEL,), None, 404, [], id="leading-slash"),
        pytest.param("prov//a", (MODEL,), None, 404, [], id="empty-segment"),
    ],
)
async def test_unknown_model_is_404_model_not_found(
    model: str,
    known: tuple[str, ...],
    catalog_error: Exception | None,
    unknown_status: int,
    calls: list[str],
) -> None:
    ca = chat_app(answered(), known=known)
    source = _source(ca)
    source.error = catalog_error
    source.unknown_status = unknown_status
    resp = await post(ca.app, body(model))
    assert resp.status_code == 404
    assert resp.headers["x-should-retry"] == "false"
    envelope = error(resp)
    assert envelope["code"] == "model_not_found"
    assert envelope["param"] == "model"
    assert envelope["type"] == "invalid_request_error"
    assert source.calls == calls
    assert ca.runner.scheduled == []
    assert ca.objects.objects == {}


async def test_corrective_loop_recipe_is_400_recipe_not_supported() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body(_CORRECTIVE_LOOP))
    assert resp.status_code == 400
    envelope = error(resp)
    assert envelope["code"] == "recipe_not_supported"
    assert envelope["param"] == "model"
    assert ca.runner.scheduled == []
    assert _source(ca).calls == []


async def test_linked_expression_is_400_with_hint() -> None:
    linked = render(
        expr(
            src(
                text("(model_1:0.0:/prov/a($input)!'x')!'$model_1'"),
                name="candidate",
                weight=0.0,
            ),
            src(
                RelExpr(path="/prov/b", context="$candidate", intent=text("judge")),
                name="model_1",
                weight=0.0,
            ),
            intent=text("$model_1"),
        )
    )
    ca = chat_app(answered())
    resp = await post(ca.app, body(linked))
    assert resp.status_code == 400
    envelope = error(resp)
    assert envelope["code"] == "recipe_invalid"
    assert envelope["message"] == LINKED_EXPRESSION_MESSAGE
    assert "Candidate URL4" in envelope["message"]
    assert ca.runner.scheduled == []


async def test_corpus_linked_recipe_is_400_recipe_invalid() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body(corpus()["lowering:pair-synthesize-evaluation"]))
    assert resp.status_code == 400
    assert error(resp)["code"] == "recipe_invalid"
    assert ca.runner.scheduled == []


async def test_unparsable_url4_is_400_recipe_invalid() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body("(model_1:0.0:/prov/a($input)!'"))
    assert resp.status_code == 400
    envelope = error(resp)
    assert envelope["code"] == "recipe_invalid"
    assert envelope["param"] == "model"
    assert "/prov/a" not in envelope["message"]
    assert ca.runner.scheduled == []


async def test_model_id_with_colon_resolves_through_model_parameters_lookup() -> None:
    known = ("prov/a:free", "prov/a~free")
    ca = chat_app(answered(), known=known)
    resp = await post(ca.app, body("prov/a:free"))
    assert resp.status_code == 200
    url4 = ca.runner.scheduled[0]["url4"]
    assert url4 == one_model_recipe("prov/a:free")
    assert "/prov/a~free(" in url4
    assert _source(ca).calls == ["prov/a:free"]

    ca = chat_app(answered(), known=known)
    resp = await post(ca.app, body("prov/a~free"))
    assert resp.status_code == 200
    assert ca.runner.scheduled[0]["url4"] == one_model_recipe("prov/a:free")
    assert _source(ca).calls == ["prov/a~free"]


@pytest.mark.parametrize(
    "catalog_error",
    [
        pytest.param(CatalogUnavailable(), id="unavailable"),
        pytest.param(CatalogBadResponse(), id="bad-response"),
    ],
)
async def test_catalog_lookup_failure_is_503_catalog_unavailable(
    catalog_error: Exception,
) -> None:
    """CC-43, the 503 half: a catalogue that cannot answer is retryable, and nothing runs."""
    ca = chat_app(answered())
    _source(ca).error = catalog_error
    resp = await post(ca.app, body())
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "5"
    assert resp.headers["x-should-retry"] == "true"
    envelope = error(resp)
    assert envelope["code"] == "catalog_unavailable"
    assert envelope["type"] == "server_error"
    assert ca.runner.scheduled == []


async def test_no_model_parameter_source_is_503_without_retry() -> None:
    ca = chat_app(answered(), with_source=False)
    resp = await post(ca.app, body())
    assert resp.status_code == 503
    assert "retry-after" not in resp.headers
    assert resp.headers["x-should-retry"] == "false"
    envelope = error(resp)
    assert envelope["code"] == "catalog_unavailable"
    assert envelope["type"] == "server_error"
    assert ca.runner.scheduled == []


async def test_catalog_lookups_are_kept_60_s() -> None:
    """CC-43, the keep half: a positive answer is kept 60 s for the same caller and id only."""
    from screamingface_engine.rest.chat_model import ModelLookupCache

    now = [1000.0]
    ca = chat_app(answered())
    ca.app.state.chat_model_cache = ModelLookupCache(clock=lambda: now[0])
    source = _source(ca)
    assert (await post(ca.app, body())).status_code == 200
    now[0] += 59.5
    assert (await post(ca.app, body())).status_code == 200
    assert source.calls == [MODEL]

    assert (await post(ca.app, body(), headers=_OTHER_USER)).status_code == 200
    assert len(source.calls) == 2
    assert source.callers[0] != source.callers[1]

    now[0] += 0.5
    assert (await post(ca.app, body())).status_code == 200
    assert len(source.calls) == 3

    source.known.clear()
    now[0] += 60
    assert (await post(ca.app, body())).status_code == 404
    source.known.add(MODEL)
    assert (await post(ca.app, body())).status_code == 200
    assert len(source.calls) == 5
