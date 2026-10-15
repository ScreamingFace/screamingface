# pyright: reportMissingImports=false
# WHY file-level: IFEval is a local inspect Task (OME-1527), absent in the extra-less install.
"""SDK-compiled combine Candidates graded end to end by IFEval (OME-1289 E4a, units 5 and 6).

FEATURE: a Candidate compiled by ``sf.Fusion(..., synthesizer=sf.Vote(...))`` or ``sf.samples``
runs VERBATIM (``combine_contract/*.url4`` are written by the SDK; its drift guard keeps them
current) against a real Benchmark, so the grader, the abstain rule and the failure path are the
production ones.
STORY: as a researcher, a vote with no usable answer abstains the case (scored 0.0, flagged), a
member failure fails the candidate exactly like a model synthesizer, the grader reads the chosen
member's text byte for byte, and a gateway that rejects a sample's seed fails the case loudly.

These tests ran against the hand-built IFEval in ``test_combine_reducer_candidates.py`` and
``test_samples_seed_contract.py`` (PRD ids VT-5, VT-12, VT-13, SM-10); IFEval became a local
inspect Task (OME-1527), so they moved to the inspect lane unchanged but for the Benchmark they
install.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

pytest.importorskip("inspect_ai")

from local_ifeval_helpers import IFEVAL  # noqa: E402
from test_corrective_loop_e2e import _assets, _chat  # noqa: E402

from screamingface_engine.benchmarks import BenchmarkRegistry, link_candidate  # noqa: E402
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS  # noqa: E402
from screamingface_engine.world.candidate_adapter import (  # noqa: E402
    install_candidate_invocation,
)
from screamingface_engine.world.combine import install_combine_runtime  # noqa: E402
from screamingface_engine.world.config import ModelSpec  # noqa: E402
from screamingface_engine.world.connector import (  # noqa: E402
    AigatewayConfig,
    build_aigateway_world,
)

pytestmark = pytest.mark.asyncio

_CONTRACT = Path(__file__).parent.parent / "data" / "combine_contract"
_MEMBERS = ("prov/member-a", "prov/member-b", "prov/member-c")

type _Replies = Mapping[str, str | httpx.Response]


def _contract(name: str) -> str:
    """One SDK-compiled Candidate, as the drift guard keeps it."""

    # rstrip: the repo's end-of-file hook appends a newline the rendered expression never carries.
    return (_CONTRACT / name).read_text(encoding="utf-8").rstrip("\n")


def _by_model(replies: _Replies) -> Callable[[httpx.Request], httpx.Response]:
    """A fake gateway that answers each model with its canned reply."""

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        reply = replies[body["model"]]
        return _chat(reply) if isinstance(reply, str) else reply

    return respond


async def _ifeval_case(
    tmp_path: Path,
    candidate: str,
    respond: Callable[[httpx.Request], httpx.Response],
    models: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one compiled Candidate over IFEval's one canned Case; the run and its Case."""

    _assets(tmp_path / "ifeval")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(default_model=models[0], models=tuple(ModelSpec(id=m) for m in models)),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        BenchmarkRegistry((IFEVAL,)).install(world.node, assets_root=tmp_path)
        protocol = IFEVAL.resource(1)["url4"]
        assert isinstance(protocol, str)
        result = await world.node.evaluate(link_candidate(candidate, protocol))
    finally:
        await world.aclose()
        await client.aclose()
    payload = json.loads(result.text)
    return payload, payload["cases"][0]


async def _vote_case(
    tmp_path: Path, candidate_file: str, replies: _Replies
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A vote (or model-synthesizer) Candidate over the three members and the synthesizer."""

    return await _ifeval_case(
        tmp_path, _contract(candidate_file), _by_model(replies), (*_MEMBERS, "prov/synth")
    )


async def test_no_votes_abstains_the_case(tmp_path: Path) -> None:
    replies: _Replies = dict.fromkeys(_MEMBERS, "tea has no digits")
    result, case = await _vote_case(tmp_path, "vote_candidate.url4", replies)
    # An abstain is an answer of "no answer": the case is scored 0.0, not failed (GE-1).
    assert case["status"] == "scored"
    assert case["abstained"] is True
    assert case["output"] == ""
    assert case["grade"]["score"] == 0.0
    assert case["failures"] == []
    assert result["score"] == 0.0
    synthesis = {op["operation_id"]: op for op in case["operations"]}["op_synthesis_1"]
    evidence = synthesis["combine"]
    assert evidence["result"] == {
        "member_id": None,
        "value": None,
        "status": "abstain",
        "reason": "no_votes",
    }
    assert evidence["dropped"] == 3


async def test_member_failure_fails_candidate_like_model_synthesizer(tmp_path: Path) -> None:
    replies: dict[str, str | httpx.Response] = {
        "prov/member-a": "tea 1",
        "prov/member-b": httpx.Response(400),
        "prov/member-c": "tea 1",
        "prov/synth": "tea 1",
    }
    shapes = []
    for name in ("vote_candidate.url4", "model_synthesizer_candidate.url4"):
        _, case = await _vote_case(tmp_path / name, name, replies)
        assert case["status"] == "failed"
        shapes.append(
            [(f["stage"], f["code"], f["retryable"], f["message"]) for f in case["failures"]]
        )
    expected = [
        ("candidate", "aigateway_http_400", False, "aigateway request failed with status 400")
    ]
    assert shapes == [expected, expected]


async def test_ifeval_grades_the_chosen_member_text_verbatim(tmp_path: Path) -> None:
    replies: _Replies = {
        "prov/member-a": "tea is warm 2",
        "prov/member-b": "Tea, maybe 3",
        "prov/member-c": "tea calms 2",
    }
    result, case = await _vote_case(tmp_path, "vote_candidate.url4", replies)
    assert case["output"] == "tea is warm 2"
    assert case["status"] == "scored"
    assert result["score"] == 1.0
    operations = {operation["operation_id"]: operation for operation in case["operations"]}
    synthesis = operations["op_synthesis_1"]
    assert synthesis["combine"]["chosen"] == ["member_1"]
    assert synthesis["output"] == replies["prov/member-a"]


async def test_gateway_seed_rejection_fails_the_case(tmp_path: Path) -> None:
    """SM-10: a gateway that rejects ``seed`` fails the case, with the gateway's code kept.

    The PRD said ``model_parameter_invalid``; the code produces ``upstream_error`` because the
    gateway's code is not a declared failure code, so the aggregation folds it and keeps the
    original spelling (aggregation.public_error). Pinned as it is. The spelling now sits in
    ``metadata.source_error.source_code``, where the plugin lane files every Candidate failure;
    the hand-built IFEval filed it at ``metadata.source_code`` (OME-1527).
    """

    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"detail": {"code": "unsupported_parameters", "message": "seed is not supported"}},
        )

    payload, case = await _ifeval_case(
        tmp_path, _contract("samples_vote_candidate.url4"), reject, ("prov/member-a",)
    )

    assert case["status"] == "failed"
    assert payload["score"] is None
    failures = case["failures"]
    assert len(failures) == 1
    failure = failures[0]
    assert (failure["stage"], failure["code"], failure["retryable"]) == (
        "candidate",
        "upstream_error",
        False,
    )
    assert failure["metadata"]["source_error"]["source_code"] == "unsupported_parameters"
