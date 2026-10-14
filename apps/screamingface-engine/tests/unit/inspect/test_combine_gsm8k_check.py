"""A Vote candidate's chosen member text reaches the GSM8K check verbatim (OME-1289, VT-13).

FEATURE: ``sf.Vote`` over three members on the imported ``inspect-gsm8k`` benchmark.
STORY: as a researcher, the grader reads the chosen member's own text, not a paraphrase.
INVARIANT defended: the combine route's output is the plain member text, so the downstream
``/check`` sees exactly it (PRD VT-D8). A contract pin: it passes on its first run by design.

Runs only with the ``inspect`` extra installed (``uv run --extra inspect pytest ...``); the plain
gate skips it. The IFEval twin in ``test_combine_reducer_candidates.py`` runs in the plain gate.
WHY the candidate is read by path and ``combine_support`` is not imported: this directory is the
inspect CI lane's whole test tree, so it cannot import helpers from ``tests/unit``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from test_inspect_gsm8k_benchmark import GSM8K_BENCHMARK, _prepare  # noqa: E402

from screamingface_engine.benchmarks import BenchmarkRegistry, link_candidate  # noqa: E402
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS  # noqa: E402
from screamingface_engine.world.candidate_adapter import install_candidate_invocation  # noqa: E402
from screamingface_engine.world.combine import install_combine_runtime  # noqa: E402
from screamingface_engine.world.config import ModelSpec  # noqa: E402
from screamingface_engine.world.connector import (  # noqa: E402
    AigatewayConfig,
    build_aigateway_world,
)

pytestmark = pytest.mark.asyncio

_CANDIDATE = Path(__file__).parents[1] / "data" / "combine_contract" / "vote_candidate.url4"
_REPLIES = {
    "prov/member-a": "6 * 7 = 42\nANSWER: 42",
    "prov/member-b": "I get 41\nANSWER: 41",
    "prov/member-c": "Product is 42. ANSWER: 42",
}


def _chat(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        },
    )


async def test_gsm8k_check_receives_chosen_member_text(tmp_path: Path) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return _chat(_REPLIES[json.loads(request.content)["model"]])

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="prov/member-a", models=tuple(ModelSpec(id=m) for m in _REPLIES)
        ),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        benchmark = GSM8K_BENCHMARK.benchmark
        BenchmarkRegistry((benchmark,)).install(world.node, assets_root=_prepare(tmp_path))
        protocol = benchmark.resource(limit=1)["url4"]
        assert isinstance(protocol, str)
        candidate = _CANDIDATE.read_text(encoding="utf-8").rstrip("\n")
        result = await world.node.evaluate(link_candidate(candidate, protocol))
    finally:
        await world.aclose()
        await client.aclose()

    case = json.loads(result.text)["cases"][0]
    assert case["output"] == _REPLIES["prov/member-a"]
    assert case["status"] == "scored"
    assert case["grade"]["score"] == 1.0
