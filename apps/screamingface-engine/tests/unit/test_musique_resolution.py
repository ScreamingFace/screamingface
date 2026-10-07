"""The composed MuSiQue-Ans expression, RESOLVED in-process — not merely parsed.

WHY this file exists: url4's resolver answers an unknown `$name` with EMPTY TEXT rather than an
error (OME-1126: a green unit suite shipped a blank prompt to a paid model). This drives the
whole pipeline — Cases route, Candidate call, check, case-evaluation, aggregate — against a
mocked gateway, so it costs nothing and still fails if any binding slips.

Stand-in: the gateway is an `httpx.MockTransport` that returns a fixed reply. It proves the
Benchmark's own routes and bindings; it proves nothing about a real model or provider.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from screamingface_engine.benchmarks.builtins import BUILTIN_DEPLOYMENT
from screamingface_engine.benchmarks.definition import link_candidate
from screamingface_engine.benchmarks.musique import definition as benchmark
from screamingface_engine.benchmarks.musique.prepare import case_records, emit, parse_rows
from screamingface_engine.benchmarks.registry import BenchmarkRegistry
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, build, text

pytestmark = pytest.mark.asyncio

_FIXTURE: Path = Path(__file__).parents[1] / "fixtures/musique/dev_two_rows.jsonl"
_FIXTURE_CASES = 2

#: The spec's first reply for Case 1, `2hop__460946_294723`.
_COMMITTED_REPLY = "Supporting paragraphs: 10, 5\nAnswer: Miquette Giraudy"


def _assets(tmp_path: Path) -> Path:
    """Prepare the two fixture Cases under the layout `install_musique` expects.

    Shared with the enumerating built-in tests (stage parity, early-score timing), which need
    a real two-Case bundle for every registered Benchmark.
    """

    bundle: Path = tmp_path / benchmark.ASSET_BUNDLE_ID
    bundle.mkdir(parents=True)
    cases, answers = case_records(parse_rows(_FIXTURE.read_bytes(), expected_count=_FIXTURE_CASES))
    emit(bundle, cases, answers)
    return tmp_path


async def _run(tmp_path: Path, model_reply: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Resolve the Benchmark's own expression at limit=1; return (result, gateway requests)."""

    seen: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": model_reply}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(default_model="provider/model", models=(ModelSpec(id="provider/model"),)),
        client=client,
    )
    install_candidate_invocation(world.node)
    BenchmarkRegistry((benchmark.MUSIQUE_ANS,)).install(world.node, assets_root=_assets(tmp_path))
    candidate = RelExpr(path="/provider/model", context="$input", intent=text("Answer."))
    try:
        result = await world.node.evaluate(
            link_candidate(candidate, build(str(benchmark.MUSIQUE_ANS.resource(1)["url4"])))
        )
    finally:
        await world.aclose()
        await client.aclose()
    return json.loads(result.text), seen


async def test_the_candidate_receives_the_real_paragraphs_and_question(tmp_path: Path) -> None:
    """THE OME-1126 GUARD: a slipped `$item.input` binding would send an empty user message,
    every gate would stay green, and the run would still be billed."""

    _, seen = await _run(tmp_path, _COMMITTED_REPLY)

    assert len(seen) == 1
    user: str = next(m["content"] for m in seen[0]["messages"] if m["role"] == "user")
    assert user.startswith("Answer the question using the numbered paragraphs below.")
    assert "[10] Green (Steve Hillage album)" in user
    assert "Question: Who is the spouse of the Green performer?" in user
    assert user.endswith("Answer: <the answer, in as few words as possible>")


async def test_a_committed_reply_resolves_to_three_full_marks(tmp_path: Path) -> None:
    """Cases -> Candidate -> check -> case-evaluation -> aggregate, every binding intact."""

    result, _ = await _run(tmp_path, _COMMITTED_REPLY)

    assert result["score"] == pytest.approx(1.0)
    assert result["scores"] == {"f1": 1.0, "exact": 1.0, "support_f1": 1.0}
    assert result["cases"][0]["grade"]["scores"] == {"f1": 1.0, "exact": 1.0, "support_f1": 1.0}
    assert result["cases"][0]["metadata"] == {
        "musique_id": "2hop__460946_294723",
        "hop_type": "2hop",
    }


async def test_a_sentence_reply_resolves_to_the_spec_s_partial_credit(tmp_path: Path) -> None:
    """The same pipeline, the other end of the spec table — so a test passing by always
    returning 1.0 cannot hide here. F1 4/11, no exact match, no support line."""

    result, _ = await _run(
        tmp_path, "The performer is Steve Hillage, whose partner is Miquette Giraudy."
    )

    assert result["score"] == pytest.approx(0.3636, abs=1e-4)
    assert result["scores"] == pytest.approx(
        {"f1": 0.3636, "exact": 0.0, "support_f1": 0.0}, abs=1e-4
    )
    assert result["cases"][0]["grade"]["metrics"] == {
        "answer_line_found": False,
        "support_line_found": False,
    }


async def test_the_benchmark_resolves_the_same_way_from_the_real_deployment(
    tmp_path: Path,
) -> None:
    """The registry the Engine ships must carry this Benchmark with working routes — `_run`
    builds its own registry, so without this the production composition is untested."""

    assert benchmark.MUSIQUE_ANS in tuple(BUILTIN_DEPLOYMENT.benchmarks)
    result, _ = await _run(tmp_path, _COMMITTED_REPLY)

    assert result["benchmark_id"] == "musique-ans"
    assert result["benchmark_revision"] == benchmark.REVISION
