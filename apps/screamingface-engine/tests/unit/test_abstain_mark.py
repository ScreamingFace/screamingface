"""A Candidate Invocation whose final node is an abstained combine carries ``abstained`` (E4a).

FEATURE: the Engine marks a Candidate Invocation as an abstention when the expression's result IS
one attributed combine operation whose evidence says it abstained (OME-1289, erd section 9).
STORY: as a benchmark grader, I see the empty answer of an abstained vote as an abstention, so
the Case can be scored 0.0 instead of being graded as if the model had answered with nothing.
INVARIANT defended: the mark reads only the final operation's own evidence. A prose intent, an
inner abstain that a later model call answers around, and an unattributed name are never marked,
and an envelope with no mark is byte for byte what it was before.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pydantic
import pytest
from combine_golden_support import builtin_vote_spec
from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.benchmarks.contract import (
    CandidateInvocation,
    OperationOutput,
    decode_candidate_invocation_record,
    encode_candidate_invocation,
)
from screamingface_engine.benchmarks.grading_endpoints import candidate_answer
from screamingface_engine.benchmarks.invocation import evaluate_candidate_recipe
from screamingface_engine.benchmarks.operation_outputs import final_operation_abstained
from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.endpoint import COMBINE_ROUTE
from screamingface_engine.combine.evidence import CombineEvidence, ResultRecord
from screamingface_engine.world.combine import install_combine_runtime
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4 import RelExpr, Text, expr, render, src, struct, text

_UNSURE = "I am not sure"


def _reply_by_model(replies: dict[str, str]) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": replies[body["model"]]}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    return respond


def _vote_expression(final: str, *, after: str | None = None) -> str:
    """Three members, a built-in vote, and an optional model call that reads the vote."""
    sources = [
        src(
            RelExpr(path=f"/provider/{name}", context="$input", intent=text("Answer plainly.")),
            name=f"model_{index}",
            weight=0.0,
        )
        for index, name in enumerate(("alpha", "beta", "gamma"), start=1)
    ]
    sources.append(
        src(
            RelExpr(
                path=COMBINE_ROUTE,
                context=render(
                    struct(
                        {
                            "input": "$input",
                            "outputs": {f"member_{n}": f"$model_{n}" for n in range(1, 4)},
                        }
                    )
                ),
                intent=Text(spec_text(builtin_vote_spec(3))),
                params=(("binding", "synthesis_1"),),
            ),
            name="synthesis_1",
            weight=0.0,
        )
    )
    if after is not None:
        sources.append(
            src(
                RelExpr(path="/provider/delta", context=after, intent=text("Finish.")),
                name="model_4",
                weight=0.0,
            )
        )
    return render(expr(*sources, intent=text(final)))


async def _evaluate(expression: str, replies: dict[str, str]) -> str:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_reply_by_model(replies)), base_url="http://aigateway.test"
    )
    world = await build_aigateway_world(
        AigatewayConfig(
            default_model="provider/alpha", models=tuple(ModelSpec(id=m) for m in replies)
        ),
        client=client,
    )
    install_combine_runtime(world.node, BUILTIN_OPERATORS)
    try:
        return await evaluate_candidate_recipe(world.node, expression, "what is the number?")
    finally:
        await world.aclose()
        await client.aclose()


_ALL_UNSURE = {f"provider/{name}": _UNSURE for name in ("alpha", "beta", "gamma")}


@pytest.mark.asyncio
async def test_invocation_record_marks_final_combine_abstain() -> None:
    encoded = await _evaluate(_vote_expression("$synthesis_1"), _ALL_UNSURE)

    decoded = decode_candidate_invocation_record(encoded)

    assert decoded.abstained is True
    assert decoded.output == ""
    assert encoded.endswith(',"abstained":true}')
    assert decoded.operations is not None
    synthesis = {op.operation_id: op for op in decoded.operations}["op_synthesis_1"]
    assert synthesis.combine is not None
    assert synthesis.combine.result == ResultRecord(
        member_id=None, value=None, status="abstain", reason="no_votes"
    )
    assert candidate_answer(encoded).abstained is True


@pytest.mark.asyncio
async def test_inner_abstain_in_pipeline_does_not_mark() -> None:
    """AB#10 (guard): a later model call answers around an inner abstain, so nothing is marked."""
    encoded = await _evaluate(
        _vote_expression("$model_4", after="Question: $input. Draft: $synthesis_1"),
        {**_ALL_UNSURE, "provider/delta": "delta settles on 12"},
    )

    decoded = decode_candidate_invocation_record(encoded)

    assert "abstained" not in json.loads(encoded)
    assert decoded.abstained is False
    assert decoded.output == "delta settles on 12"
    assert decoded.operations is not None
    synthesis = {op.operation_id: op for op in decoded.operations}["op_synthesis_1"]
    assert synthesis.combine is not None
    assert synthesis.combine.result.status == "abstain"


# --- the final-node rule (unit) ---------------------------------------------------------------


def _evidence(outputs: list[str], **overrides: Any) -> CombineEvidence:
    return run(spec_text(vote_spec(3, **overrides)), context_text(outputs)).evidence


def _abstain_evidence() -> CombineEvidence:
    return _evidence(["", " ", "\n"])


def _answered_evidence() -> CombineEvidence:
    return _evidence(["a x", "b y", "c x"])


def _empty_answer_evidence() -> CombineEvidence:
    """Answered, yet the built text is empty (the setup of ``test_empty_concat_is_not_abstain``)."""
    return _evidence(
        ["a", "b", "c"],
        reducer="concat",
        extract=None,
        normalize=None,
        reduce={"op": "fake_all_parts@1", "args": {}},
        select={"op": "fake_empty_join@1", "args": {}},
    )


def _combine_final(final: str) -> str:
    return render(
        expr(
            src(
                RelExpr(path=COMBINE_ROUTE, context="$input", intent=Text("spec")),
                name="synthesis_1",
                weight=0.0,
            ),
            intent=Text(final),
        )
    )


def _operations(evidence: CombineEvidence | None, output: str = "") -> list[OperationOutput]:
    return [
        OperationOutput(
            operation_id="op_synthesis_1",
            output=output,
            finish_reason="stop",
            accounting=None,
            combine=evidence,
        )
    ]


def test_evidence_fixtures_are_what_their_names_say() -> None:
    assert _abstain_evidence().result.status == "abstain"
    assert _answered_evidence().result.status == "answered"
    empty = _empty_answer_evidence()
    assert (empty.result.status, empty.result.reason) == ("answered", None)
    assert empty.built is True


@pytest.mark.parametrize(
    ("expression", "operations", "expected"),
    [
        pytest.param(
            _combine_final("$synthesis_1"), _operations(_abstain_evidence()), True, id="a-abstain"
        ),
        pytest.param(
            _combine_final("$synthesis_1"),
            _operations(_answered_evidence(), "a x"),
            False,
            id="b-answered",
        ),
        pytest.param(
            _combine_final("$synthesis_1"),
            _operations(_empty_answer_evidence()),
            False,
            id="c-answered-with-empty-output",
        ),
        pytest.param(
            _combine_final("$model_2"),
            _operations(_abstain_evidence()),
            False,
            id="d-final-is-another-name",
        ),
        pytest.param(
            _combine_final("Summarize $synthesis_1"),
            _operations(_abstain_evidence()),
            False,
            id="e-prose-intent",
        ),
        pytest.param(_combine_final("$synthesis_1"), None, False, id="f-no-operations"),
        pytest.param(
            _combine_final("$synthesis_1"), _operations(None), False, id="g-no-combine-evidence"
        ),
        pytest.param("(((", _operations(_abstain_evidence()), False, id="h-unparseable"),
        pytest.param(
            _combine_final("$loop_candidate"),
            _operations(_abstain_evidence()),
            False,
            id="i-loop-candidate",
        ),
        # WHY this shape: url4 parses a bare relative call into an Expression with NO intent, so
        # the root is never a `$name` text intent (there is no RelExpr root to receive).
        pytest.param(
            "/x(a)!'$synthesis_1'", _operations(_abstain_evidence()), False, id="j-bare-call-root"
        ),
    ],
)
def test_final_rule_reads_only_the_final_operation_evidence(
    expression: str, operations: list[OperationOutput] | None, expected: bool
) -> None:
    assert final_operation_abstained(expression, operations) is expected


# --- the wire (unit) --------------------------------------------------------------------------


def test_non_abstained_invocation_has_no_abstained_key_and_decoder_is_strict() -> None:
    plain = encode_candidate_invocation("a", "stop", None)
    marked = json.loads(encode_candidate_invocation("", "stop", None, abstained=True))

    assert "abstained" not in plain
    assert decode_candidate_invocation_record(plain).abstained is False
    assert decode_candidate_invocation_record(json.dumps(marked)).abstained is True
    for bad in (False, "yes"):
        with pytest.raises(ValueError, match="invalid shape"):
            decode_candidate_invocation_record(json.dumps({**marked, "abstained": bad}))


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "refused", "output": "", "refusal": "no"},
        {"status": "completed", "output": "x", "refusal": None},
    ],
)
def test_an_abstained_invocation_must_be_a_completed_empty_answer(fields: dict[str, Any]) -> None:
    with pytest.raises(pydantic.ValidationError, match="completed empty answer"):
        CandidateInvocation(finish_reason="stop", execution=None, abstained=True, **fields)
