"""A model-written Merge field runs end to end in the engine world (OME-1289 E4a, unit 9).

FEATURE: a Merge field written by a model: a projection combine call, a writer model call, and the
final merge combine call that reads the writer's reply as ``signals.writer_<field>``.
STORY: as a researcher, the writer sees only the values of its one field, the Report shows each
step on its own operation, and the merged object holds the writer's text for that field.
INVARIANT defended: the writer's context is exactly the projection text; a writer that fails keeps
its own gateway code and no partial object is returned; the attribution-only ``binding`` param
never reaches the gateway.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from combine_fields_support import merge_spec, project_spec
from combine_support import spec_text

from screamingface_engine.app import create_app
from screamingface_engine.benchmarks.contract import decode_candidate_invocation_record
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.config import Settings
from screamingface_engine.testing import InMemoryEventStream
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, Text, expr, render, src, struct, text
from url4.core.errors import ResolutionError

_ANSWERS = {
    "provider/alpha": '{"confidence": 0.4, "summary": "alpha reasons"}',
    "provider/beta": '{"confidence": 0.9, "summary": "beta says 7"}',
    "provider/gamma": '{"confidence": 0.7, "summary": "gamma agrees"}',
}
_PROJECTION = '{"member_1":"alpha reasons","member_2":"beta says 7","member_3":"gamma agrees"}'
_WRITER_PROMPT = "Write."
_WRITER_REPLY = "A short written summary."
_COMBINE_LOGGER = "screamingface_engine.combine.endpoint"


def _completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


def _is_writer_call(body: dict[str, Any]) -> bool:
    first = body["messages"][0]
    return first["role"] == "system" and first["content"] == _WRITER_PROMPT


def _answering(
    writer: Callable[[], httpx.Response], seen: list[dict[str, Any]]
) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if _is_writer_call(body):
            return writer()
        return _completion(_ANSWERS[body["model"]])

    return respond


def _fusion_context(*, with_signal: bool) -> str:
    body: dict[str, Any] = {
        "input": "$input",
        "outputs": {f"member_{index}": f"$model_{index}" for index in range(1, 4)},
    }
    if with_signal:
        body["signals"] = {"writer_summary": "$writer_1"}
    return render(struct(body))


def _combine(binding: str, spec: dict[str, Any], *, with_signal: bool) -> Any:
    return src(
        RelExpr(
            path=COMBINE_ROUTE,
            context=_fusion_context(with_signal=with_signal),
            intent=Text(spec_text(spec)),
            params=(("binding", binding),),
        ),
        name=binding,
        weight=0.0,
    )


def _expression() -> str:
    """Three members, a projection, a writer on alpha's route, and the final merge."""
    members = [
        src(
            RelExpr(path=f"/{model}", context="$input", intent=text("Answer plainly.")),
            name=f"model_{index}",
            weight=0.0,
        )
        for index, model in enumerate(_ANSWERS, start=1)
    ]
    projection = project_spec(3, "summary")
    merge = merge_spec(
        3,
        [{"field": "confidence", "rule": "max"}, {"field": "summary", "rule": "model"}],
    )
    writer = src(
        RelExpr(
            path="/provider/alpha",
            context="$synthesis_2",
            intent=Text(_WRITER_PROMPT),
            params=(("binding", "writer_1"),),
        ),
        name="writer_1",
        weight=0.0,
    )
    return render(
        expr(
            *members,
            _combine("synthesis_2", projection, with_signal=False),
            writer,
            _combine("synthesis_1", merge, with_signal=True),
            intent=text("$synthesis_1"),
        )
    )


async def _evaluate(responder: Callable[[httpx.Request], httpx.Response]) -> Any:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(responder), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha", models=tuple(ModelSpec(id=m) for m in _ANSWERS)
        ),
        client=client,
    )
    install_combine_runtime(world.node, BUILTIN_OPERATORS)
    try:
        return await evaluate_candidate_recipe(world.node, _expression(), "what is it?")
    finally:
        await world.aclose()
        await client.aclose()


async def _succeed() -> tuple[list[dict[str, Any]], Any]:
    seen: list[dict[str, Any]] = []
    encoded = await _evaluate(_answering(lambda: _completion(_WRITER_REPLY), seen))
    return seen, decode_candidate_invocation_record(encoded)


@pytest.mark.asyncio
async def test_writer_sees_only_the_projection() -> None:
    """PM-H4 and PM-6: the writer's user message is exactly the projection of its one field."""
    seen, decoded = await _succeed()

    writer_calls = [body for body in seen if _is_writer_call(body)]
    assert len(writer_calls) == 1
    assert writer_calls[0]["messages"] == [
        {"role": "system", "content": _WRITER_PROMPT},
        {"role": "user", "content": _PROJECTION},
    ]
    assert decoded.output == '{"confidence":0.9,"summary":"A short written summary."}'
    # No gateway body carried the attribution-only param.
    assert all("binding" not in body for body in seen)


@pytest.mark.asyncio
async def test_writer_on_a_member_route_keeps_every_operation() -> None:
    """EV-H3: the writer shares alpha's route with a member, and each operation keeps its record."""
    _, decoded = await _succeed()

    assert decoded.operations is not None
    by_id = {operation.operation_id: operation for operation in decoded.operations}
    assert list(by_id) == [
        "op_model_1",
        "op_model_2",
        "op_model_3",
        "op_synthesis_2",
        "op_writer_1",
        "op_synthesis_1",
    ]
    assert by_id["op_model_1"].output == _ANSWERS["provider/alpha"]
    assert by_id["op_model_1"].accounting is not None
    assert by_id["op_writer_1"].output == _WRITER_REPLY
    assert by_id["op_writer_1"].accounting is not None
    assert by_id["op_synthesis_2"].output == _PROJECTION
    projection = by_id["op_synthesis_2"].combine
    assert projection is not None
    assert (projection.kind, projection.reducer, projection.built) == (
        "projection",
        "project",
        True,
    )
    merged = by_id["op_synthesis_1"].combine
    assert merged is not None
    assert (merged.kind, merged.reducer, merged.built) == ("answer", "merge", True)
    assert merged.presentation_order is None
    assert merged.fields is not None
    assert [(f.field, f.rule, f.result) for f in merged.fields] == [
        ("confidence", "max", 0.9),
        ("summary", "model", _WRITER_REPLY),
    ]


@pytest.mark.asyncio
async def test_writer_failure_fails_case_without_partial_object(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PM-8: a writer route that answers HTTP 400 fails the case with its gateway code."""
    caplog.set_level(logging.INFO, logger=_COMBINE_LOGGER)
    seen: list[dict[str, Any]] = []
    responder = _answering(lambda: httpx.Response(400, json={"error": {"message": "bad"}}), seen)

    with pytest.raises(ResolutionError) as caught:
        await _evaluate(responder)

    assert caught.value.code == "aigateway_http_400"
    assert any(_is_writer_call(body) for body in seen)
    # The projection ran; the final merge (synthesis_1) never did, so no partial object exists.
    ran = [record.getMessage() for record in caplog.records if record.name == _COMBINE_LOGGER]
    assert len(ran) == 1
    assert "binding=synthesis_2 " in ran[0]
    assert not any("binding=synthesis_1 " in line for line in ran)


async def _get(app: Any, path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://engine.test"
    ) as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_catalog_lists_the_field_operators() -> None:
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())

    listed = (await _get(app, "/v1/operators")).json()["data"]

    stages = {entry["id"]: entry["stage"] for entry in listed}
    assert {
        "json_object@1": "extract",
        "values@1": "reduce",
        "by_field@1": "select",
        "field_rules@1": "reduce",
        "project_field@1": "reduce",
        "built@1": "select",
    }.items() <= stages.items()
