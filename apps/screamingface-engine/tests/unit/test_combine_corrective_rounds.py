"""A corrective loop whose member is a reducer Fusion runs on the Engine (OME-1289 E4a, unit 11).

FEATURE: ``sf.CorrectiveLoop([sf.Fusion([...], synthesizer=sf.Vote()), "prov/member-d"], ...)``
compiled by the SDK (``combine_contract/corrective_vote_candidate.url4``, kept current by its drift
guard) runs VERBATIM next to the IFEval check surface.
STORY: as a researcher, I put a vote inside a corrective loop. The vote is one member; the judge
coaches after a failed round; the passing member's text is the case output.

PRD id: EV-10 (decision D-8: a CHAR test). The PRD asks for "evidence from the last round". That
cannot be observed today: the outer expression's only top-level source is ``loop_candidate`` (not a
model/synthesis/judge/writer binding), and the loop runs each member isolated, so a corrective case
carries no ``operations`` at all. This test pins that fact. Lifting member operations (and so the
last-round evidence) out of a corrective loop is a follow-up, NOT part of E4a. It passes on its
first run by design: units 1-3 already deliver the behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from test_corrective_loop_e2e import _assets, _chat

from screamingface_engine.benchmarks import BenchmarkRegistry, link_candidate
from screamingface_engine.benchmarks.ifeval.definition import IFEVAL
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.corrective import install_corrective_runtime

pytestmark = pytest.mark.asyncio

_CONTRACT = Path(__file__).parent / "data" / "combine_contract"
_VOTERS = ("prov/member-a", "prov/member-b", "prov/member-c")
_MODELS = (*_VOTERS, "prov/member-d", "prov/judge")
# Graded against the two-constraint spec of test_corrective_loop_e2e (no_comma + english_lowercase):
_FAIL_ANSWER = "Tea, is nice."  # comma + capital -> fails
_PASS_ANSWER = "tea is warm and calming"  # passes both
# Coached voters: a and b hold the SAME vote ("text" drops one trailing period) in different
# bytes, so the first-holder choice must give back a's bytes; c passes with another text and loses.
_COACHED = {
    "prov/member-a": _PASS_ANSWER,
    "prov/member-b": _PASS_ANSWER + ".",
    "prov/member-c": "tea is calm and warm",
}


def _respond(calls: list[tuple[str, str]]):
    """The three voters fail in round 1 and pass once coached; member-d never passes."""

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body["model"]
        content = " ".join(str(message["content"]) for message in body["messages"])
        calls.append((model, content))
        if model == "prov/judge":
            return _chat("Remove the comma and write everything in lowercase.")
        if model in _VOTERS and "Judge feedback:" in content:
            return _chat(_COACHED[model])
        return _chat(_FAIL_ANSWER)

    return respond


async def test_corrective_loop_with_a_reducer_member_reports_no_operation_evidence_yet(
    tmp_path: Path,
) -> None:
    _assets(tmp_path / "ifeval")
    calls: list[tuple[str, str]] = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_respond(calls)), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(default_model=_MODELS[0], models=tuple(ModelSpec(id=m) for m in _MODELS)),
        client=client,
    )
    try:
        install_candidate_invocation(world.node)
        install_corrective_runtime(world.node)
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        BenchmarkRegistry((IFEVAL,)).install(world.node, assets_root=tmp_path)
        # rstrip: the repo's end-of-file hook appends a newline the expression never carries.
        candidate_url4 = (
            (_CONTRACT / "corrective_vote_candidate.url4").read_text(encoding="utf-8").rstrip("\n")
        )
        protocol = IFEVAL.resource(1)["url4"]
        assert isinstance(protocol, str)
        result = await world.node.evaluate(link_candidate(candidate_url4, protocol))
    finally:
        await world.aclose()
        await client.aclose()

    case = json.loads(result.text)["cases"][0]
    # The loop works: round 1 fails, one coaching call, round 2's vote passes and is submitted
    # word for word (the vote returns the FIRST holder's text verbatim: a's bytes, not b's).
    assert case["status"] == "scored"
    assert case["output"] == _COACHED["prov/member-a"] != _COACHED["prov/member-b"]
    assert case["stop_reason"] == "passed"
    assert case["rounds_executed"] == 2
    models = [model for model, _ in calls]
    assert [models.count(model) for model in _MODELS] == [2, 2, 2, 2, 1]
    # CHAR (EV-10, decision D-8): no `operations` at all. If this ever turns into a list, the
    # last-round evidence became observable and EV-10 should be rewritten as the PRD asks.
    assert case.get("operations") is None, (
        "EV-10: corrective member operations are now lifted; "
        "rewrite as corrective_rounds_keep_last_evidence"
    )
