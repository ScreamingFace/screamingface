"""The composed ContractEval expression, RESOLVED in-process — not merely parsed.

WHY this file exists (review of PR #984): every other test proves a piece. Nothing proved that
the assembled url4 expression actually binds its names, and url4's resolver answers an unknown
`$name` with EMPTY TEXT rather than an error. That is OME-1126 exactly: MedXpertQA's unit suite
was green while the composed expression shipped a blank prompt to a paid model, and the bill
arrived before the bug did.

This drives the whole pipeline — cases route, candidate invocation, check, case-evaluation,
aggregate — against a mocked gateway, so it costs nothing and still fails if any binding slips.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from screamingface_engine.benchmarks.builtins import BUILTIN_DEPLOYMENT
from screamingface_engine.benchmarks.contracteval import definition as board
from screamingface_engine.benchmarks.contracteval.prepare import emit
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, build, text

pytestmark = pytest.mark.asyncio

_GOLD = "This Agreement is governed by Delaware law."
_CONTRACT = f"1. Term. Five years. 2. Governing Law. {_GOLD}"


def _assets(tmp_path: Path) -> Path:
    """Bake one real Case under the layout `install_contracteval` expects."""

    bundle = tmp_path / board.ASSET_BUNDLE_ID
    bundle.mkdir(parents=True)
    emit(
        [
            {
                "id": "Doc__Governing Law",
                "title": "Doc",
                "context": _CONTRACT,
                "question": "Which state's law governs?",
                "answers": {"text": [_GOLD], "answer_start": [0]},
            }
        ],
        bundle,
    )
    return tmp_path


def _reply(text_out: str):
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text_out}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    return respond


async def _run(tmp_path: Path, model_reply: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve the board's own expression at limit=1 and return (result, gateway requests)."""

    seen: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _reply(model_reply)(request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(default_model="provider/model", models=(ModelSpec(id="provider/model"),)),
        client=client,
    )
    install_candidate_invocation(world.node)
    registry = BenchmarkRegistry((board.CONTRACTEVAL,))
    registry.install(world.node, assets_root=_assets(tmp_path))
    candidate = RelExpr(path="/provider/model", context="$input", intent=text("Answer."))
    try:
        result = await world.node.evaluate(
            link_candidate(candidate, build(str(board.CONTRACTEVAL.resource(1)["url4"])))
        )
    finally:
        await world.aclose()
        await client.aclose()
    return json.loads(result.text), seen


async def test_the_candidate_receives_the_real_contract_and_not_empty_text(
    tmp_path: Path,
) -> None:
    """THE OME-1126 GUARD. If `$item.input` slipped its binding the user message would be
    empty, every gate would stay green, and the run would still be billed."""

    _, seen = await _run(tmp_path, f"The clause reads: {_GOLD}")

    assert len(seen) == 1
    user = next(m["content"] for m in seen[0]["messages"] if m["role"] == "user")
    assert _CONTRACT in user
    assert "Which state's law governs?" in user
    # The baked input also carries the instructions — prompt bytes are exam identity here.
    assert "Do not rephrase or summarize" in user


async def test_a_verbatim_quote_resolves_all_the_way_to_a_true_positive(
    tmp_path: Path,
) -> None:
    """Cases -> candidate -> check -> case-evaluation -> aggregate, every binding intact."""

    result, _ = await _run(tmp_path, f"The clause reads: {_GOLD}")

    assert result["score"] == pytest.approx(1.0)
    assert result["metrics"]["true_positives"] == 1
    assert result["metrics"]["scored_cases"] == 1
    assert result["cases"][0]["grade"]["score"] == 1.0
    assert result["cases"][0]["grade"]["method"] == "containment"


async def test_a_paraphrase_resolves_to_a_false_negative(tmp_path: Path) -> None:
    """The same pipeline, the other verdict — so a test that passes by always returning 1.0
    cannot hide here."""

    result, _ = await _run(tmp_path, "Delaware law governs this agreement.")

    assert result["score"] == pytest.approx(0.0)
    assert result["metrics"]["false_negatives"] == 1
    assert result["metrics"]["true_positives"] == 0
    assert result["cases"][0]["grade"]["score"] == 0.0


async def test_the_board_resolves_the_same_way_from_the_real_deployment(
    tmp_path: Path,
) -> None:
    """The registry the Engine actually ships must carry this board with working routes —
    `_run` builds its own registry, so without this the production composition is untested."""

    assert board.CONTRACTEVAL in tuple(BUILTIN_DEPLOYMENT.benchmarks)
    result, _ = await _run(tmp_path, "No related clause.")

    # Abstaining on a row that HAS a clause: graded, wrong, and counted as laziness.
    assert result["metrics"]["false_no_related_clause_rate"] == pytest.approx(1.0)
    assert result["metrics"]["false_negatives"] == 1
