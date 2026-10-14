"""A corrective round's record carries the abstain mark; the loop's own record never does (E4a).

FEATURE: each corrective round evaluates its own Recipe in isolation, so a round whose final
node is an abstained combine is marked in its own Candidate Invocation record (OME-1289, AB-D7).
STORY: as a corrective-loop author, a round that abstained is still a checkable draft: IFEval's
check surface accepts the marked record and fails it (pinned beside IFEval, a local inspect Task
since OME-1527, in ``inspect/test_local_task_ifeval.py``), and the loop can try another round.
INVARIANT defended: the outer record's final name is ``loop_candidate``, which is not an
attributed operation, so the loop's own Candidate Invocation is never marked.
"""

from __future__ import annotations

import json

import httpx
import pytest
from test_abstain_mark import _ALL_UNSURE, _reply_by_model, _vote_expression

from screamingface_engine.benchmarks.contract import decode_candidate_invocation_record
from screamingface_engine.benchmarks.ensemble.policy import MEMBER_ROUTE, RESULT_ROUTE
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.world.corrective import install_corrective_runtime
from url4 import RelExpr, Text, expr, render, src, text

_CASE_PROMPT = "Describe tea without commas."


def _round_member(inner: str) -> str:
    """The loop's member source around one abstaining Recipe (``corrective.py`` names)."""
    return render(
        expr(
            src(
                RelExpr(path=MEMBER_ROUTE, context="$input", intent=Text(inner)),
                name="loop_member_1_a",
                weight=0.0,
            ),
            intent=Text("$loop_member_1_a"),
        )
    )


def _loop_result(outcome: dict[str, object]) -> str:
    """The loop's final ``$loop_candidate`` over the result route, as the compiler shapes it."""
    return render(
        expr(
            src(
                expr(
                    src(text(json.dumps(outcome)), name="loop_answer_1", weight=0.0),
                    src(
                        RelExpr(path=RESULT_ROUTE, context="$loop_answer_1", intent=Text("result")),
                        name="loop_result",
                        weight=0.0,
                    ),
                    intent=text("$loop_result"),
                ),
                name="loop_candidate",
                weight=0.0,
            ),
            intent=text("$loop_candidate"),
        )
    )


@pytest.mark.asyncio
async def test_corrective_loop_round_records_mark_but_the_loop_record_does_not() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_reply_by_model(_ALL_UNSURE)),
        base_url="http://aigateway.test",
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha", models=tuple(ModelSpec(id=m) for m in _ALL_UNSURE)
        ),
        client=client,
    )
    try:
        install_combine_runtime(world.node, BUILTIN_OPERATORS)
        install_corrective_runtime(world.node)
        install_candidate_invocation(world.node)
        inner = _vote_expression("$synthesis_1").replace("$input", "$_sf_recipe_input")

        # (a) the round's own record is marked; the record around it is not.
        outer = decode_candidate_invocation_record(
            await evaluate_candidate_recipe(world.node, _round_member(inner), _CASE_PROMPT)
        )
        assert outer.abstained is False
        inner_record = outer.output
        marked = decode_candidate_invocation_record(inner_record)
        assert (marked.abstained, marked.output) == (True, "")

        # (b) the loop's final record, built from that round, is an unmarked empty answer.
        outcome = {
            "schema": "screamingface.corrective-outcome.v1",
            "invocation": inner_record,
            "round": 2,
            "passed": False,
        }
        final = decode_candidate_invocation_record(
            await evaluate_candidate_recipe(world.node, _loop_result(outcome), _CASE_PROMPT)
        )
    finally:
        await world.aclose()
        await client.aclose()

    assert (final.output, final.abstained) == ("", False)
    assert final.execution is not None
    assert final.execution.model_dump(by_alias=True) == {
        "schema": "screamingface.corrective-execution.v1",
        "stop_reason": "max_rounds",
        "rounds_executed": 2,
    }
