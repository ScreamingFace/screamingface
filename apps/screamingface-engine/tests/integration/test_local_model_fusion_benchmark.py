from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from screamingface_engine.benchmarks import BenchmarkRegistry, link_candidate
from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT
from screamingface_engine.benchmarks.medxpert.prepare import emit
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world

pytestmark = pytest.mark.asyncio

_CONTRACT = (
    Path(__file__).parents[1]
    / "unit"
    / "data"
    / "combine_contract"
    / "model_synthesizer_candidate.url4"
)


def _assets(root: Path) -> None:
    emit(
        [
            {
                "id": "Text-0",
                "question": "Pick B",
                "options": {"A": "alpha", "B": "beta"},
                "label": "B",
            }
        ],
        root,
    )


def _chat(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


def _raw_models(provider: str) -> tuple[str, ...]:
    return (
        f"{provider}/member-a:v1",
        f"{provider}/member-b:v1",
        f"{provider}/member-c:v1",
        f"{provider}/synth:v1",
    )


def _candidate(provider: str) -> str:
    value = _CONTRACT.read_text(encoding="utf-8").rstrip("\n")
    replacements = {
        "/prov/member-a": f"/{provider}/member-a~v1",
        "/prov/member-b": f"/{provider}/member-b~v1",
        "/prov/member-c": f"/{provider}/member-c~v1",
        "/prov/synth": f"/{provider}/synth~v1",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


async def _world(provider: str):
    seen: list[str] = []
    raw_models = _raw_models(provider)
    route_models = tuple(model.replace(":", "~") for model in raw_models)

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["model"])
        replies = dict.fromkeys(raw_models, "B")
        return _chat(replies[body["model"]])

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
        base_url="http://127.0.0.1:9105",
        trust_env=False,
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model=route_models[0],
            models=tuple(ModelSpec(id=model) for model in route_models),
        ),
        client=client,
    )
    return world, client, seen, raw_models


@pytest.mark.parametrize("provider", ["local", "ollama"])
async def test_local_models_run_as_fusion_members_and_synthesizer_in_a_benchmark(
    tmp_path: Path,
    provider: str,
) -> None:
    _assets(tmp_path / "medxpert")
    world, client, seen, raw_models = await _world(provider)
    install_candidate_invocation(world.node)
    BenchmarkRegistry((MEDXPERT,)).install(world.node, assets_root=tmp_path)

    try:
        result = await world.node.evaluate(link_candidate(_candidate(provider), MEDXPERT.build(1)))
    finally:
        await world.aclose()
        await client.aclose()

    payload = json.loads(result.text)
    case = payload["cases"][0]
    operations = {row["operation_id"]: row for row in case["operations"]}
    assert payload["score"] == 1.0
    assert payload["coverage"] == 1.0
    assert case["status"] == "scored"
    assert set(operations) == {"op_model_1", "op_model_2", "op_model_3", "op_synthesis_1"}
    assert set(seen) == set(raw_models)
    assert all(operation["output"] == "B" for operation in operations.values())
    assert all(operation["accounting"] is not None for operation in operations.values())
