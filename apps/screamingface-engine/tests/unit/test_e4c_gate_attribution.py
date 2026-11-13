"""Operations inside an sf.Gate's branches are attributed; the Gate's record sits on its JOIN.

FEATURE: E4c (OME-1291) branch-core D3, D12; rows BC#2, #7, #8, #11 (unit half), #14 (unit half),
#29, #30.
STORY: as a reader of a Case result, I see the operations of the branch that ran, each with its
own output and evidence, and one gate-decision record on ``op_gate_N``; the operations of a
branch that did not run are absent, and a corrective loop stays opaque as before.
"""

from __future__ import annotations

import json
import random
import string

import pytest

from screamingface_engine.benchmarks import operation_outputs
from screamingface_engine.benchmarks.contract import OperationOutput
from screamingface_engine.benchmarks.operation_outputs import (
    attribute_operation_outputs,
    final_operation_abstained,
)
from screamingface_engine.combine.decision import GateDecision
from screamingface_engine.combine.evidence import GateRecord
from screamingface_engine.operation_calls import (
    OperationCall,
    capture_operation_calls,
    current_operation_calls,
    record_gate_call,
    record_pending_combine_call,
)
from url4 import Iteration, RelExpr, Source, expr, iterate, ref, render, src, text

_JOIN = "/ensemble/branch/v1/join"
_DECIDE = "/ensemble/branch/v1/decide"
_OPEN = "/ensemble/branch/v1/open"


def _model(binding: str, path: str, *, context: str = "$input") -> Source:
    params = (("binding", binding),) if binding.startswith("model") else ()
    model = src(
        RelExpr(path=path, context=context, intent=text("Answer"), params=params),
        name=binding,
        weight=0.0,
    )
    assert isinstance(model, Source)
    return model


def _gated(name: str, gate: str, body: tuple[Source, ...], intent: str) -> Source:
    iteration = iterate(ref(gate), body=body, intent=text(intent), on_error="fail")
    gated = src(iteration, name=name, weight=0.0)
    assert isinstance(gated, Source)
    return gated


def _gate_block(n: int, then: tuple[Source, ...], then_ref: str, otherwise, else_ref: str):
    decide = src(
        RelExpr(path=_DECIDE, context="{}", intent=text("decide"), params=(("gate", f"gate_{n}"),)),
        name=f"gate_{n}_decide",
        weight=0.0,
    )
    open_then = src(
        RelExpr(path=_OPEN, context=f"$gate_{n}_decide", intent=text("then")),
        name=f"gate_{n}_open_then",
        weight=0.0,
    )
    open_else = src(
        RelExpr(path=_OPEN, context=f"$gate_{n}_decide", intent=text("otherwise")),
        name=f"gate_{n}_open_else",
        weight=0.0,
    )
    join = src(
        RelExpr(
            path=_JOIN,
            context=(
                f"{{decision: $gate_{n}_decide, then: $gate_{n}_then, otherwise: $gate_{n}_else}}"
            ),
            intent=text("join"),
            params=(("binding", f"gate_{n}"),),
        ),
        name=f"gate_{n}",
        weight=0.0,
    )
    sources = (
        decide,
        open_then,
        _gated(f"gate_{n}_then", f"gate_{n}_open_then", then, then_ref),
        open_else,
        _gated(f"gate_{n}_else", f"gate_{n}_open_else", otherwise, else_ref),
        join,
    )
    return src(expr(*sources, intent=text(f"$gate_{n}")), name=f"gate_{n}_block", weight=0.0)


def _decision(n: int, branch: str, *, result: dict | None) -> GateDecision:
    other = "otherwise" if branch == "then" else "then"
    return GateDecision.model_validate(
        {
            "schema": "screamingface.gate-decision.v1",
            "gate_id": f"gate_{n}",
            "kind": "input",
            "when": {"observe": "label:sel_1", "cmp": "eq", "value": "math"},
            "observed": "math" if branch == "then" else None,
            "passed": branch == "then",
            "wanted": branch,
            "branch": branch,
            "selectors": [],
            "not_run": [
                {"branch": other, "reason": "not_selected", "model_calls": {"min": 1, "max": 1}}
            ],
            "budget": None,
            "result": result,
            "panel": None,
        }
    )


def _nested_candidate() -> str:
    inner = _gate_block(
        2, (_model("model_2", "/b"),), "$model_2", (_model("model_3", "/c"),), "$model_3"
    )
    outer = _gate_block(1, (_model("model_1", "/a"),), "$model_1", (inner,), "$gate_2_block")
    return render(expr(outer, intent=text("$gate_1_block")))


def _ids(operations: list[OperationOutput] | None) -> dict[str, OperationOutput]:
    assert operations is not None
    return {op.operation_id: op for op in operations}


def test_attribution_walks_gate_blocks_and_their_iterate_bodies() -> None:
    # BC#7: the taken branch's model call and the inner Gate's JOIN are found inside the outer
    # block's parsed `otherwise` body; the not-run branch's model has no recorded call.
    record_outer = _decision(1, "otherwise", result={"status": "answered", "reason": None})
    record_inner = _decision(2, "otherwise", result={"status": "answered", "reason": None})
    calls = [
        OperationCall("/c", (("binding", "model_3"),), "C", "stop", None),
        OperationCall(_JOIN, (("binding", "gate_2"),), "C", "stop", None, decision=record_inner),
        OperationCall(_JOIN, (("binding", "gate_1"),), "C", "stop", None, decision=record_outer),
    ]

    operations = _ids(attribute_operation_outputs(_nested_candidate(), calls))

    # BC-16: an operation of a branch that did not run has no recorded call and no output entry.
    assert set(operations) == {"op_model_3", "op_gate_1", "op_gate_2"}
    assert operations["op_model_3"].output == "C"
    assert operations["op_gate_1"].decision == record_outer
    assert operations["op_gate_2"].decision == record_inner
    assert operations["op_model_3"].decision is None


def test_an_iterate_body_parses_as_the_text_mapnode_spawns() -> None:
    # BC#7: MapNode spawns `(body)!intent`; the bare `(body)` of an AST-only iterate with no
    # intent is not url4 text, so such a body stays opaque (the "does not parse" rule).
    body = "model_1:0.0:/a?binding=model_1&q=($input)!'Answer'"
    parsed = operation_outputs.parsed_iterate_body(
        Iteration(ref("gate_1_open_then"), body, "'$model_1'")
    )
    assert parsed is not None
    assert [getattr(source, "name", None) for source in parsed.sources] == ["model_1"]
    assert (
        operation_outputs.parsed_iterate_body(Iteration(ref("gate_1_open_then"), body, None))
        is None
    )


def test_attribution_keeps_the_corrective_loop_candidate_opaque() -> None:
    # CHAR BC#2: only Gate blocks are walked; a corrective loop's gated iterate is never parsed.
    body = (_model("model_9", "/hidden"),)
    loop = expr(
        _gated("loop_next_1", "loop_continue_gate_1", body, "$model_9"),
        intent=text("$loop_next_1"),
    )
    candidate = render(
        expr(
            _model("model_1", "/a"),
            src(loop, name="loop_candidate", weight=0.0),
            intent=text("$loop_candidate"),
        )
    )
    calls = [
        OperationCall("/a", (("binding", "model_1"),), "A", "stop", None),
        OperationCall("/hidden", (("binding", "model_9"),), "H", "stop", None),
    ]

    operations = _ids(attribute_operation_outputs(candidate, calls))

    assert set(operations) == {"op_model_1"}


def test_gate_call_record_last_write_wins() -> None:
    # BC#8: DECIDE and JOIN publish under the JOIN fingerprint; JOIN's record wins when JOIN ran,
    # DECIDE's record stays when a body failed before JOIN.
    decided = _decision(1, "then", result=None)
    joined = _decision(1, "then", result={"status": "answered", "reason": None})
    candidate = render(
        expr(
            _gate_block(1, (_model("model_1", "/a"),), "$model_1", (), "''"),
            intent=text("$gate_1_block"),
        )
    )
    with capture_operation_calls() as recorder:
        record_gate_call(_JOIN, {"binding": "gate_1"}, "", decided)
        failed_before_join = list(recorder)
        record_gate_call(_JOIN, {"binding": "gate_1"}, "A", joined)

    assert (
        _ids(attribute_operation_outputs(candidate, failed_before_join))["op_gate_1"].decision
        == decided
    )
    after = _ids(attribute_operation_outputs(candidate, recorder))["op_gate_1"]
    assert after.decision == joined
    assert after.output == "A"
    assert recorder[-1].params == (("binding", "gate_1"),)


def test_gate_decision_is_left_out_of_the_wire_when_absent() -> None:
    plain = OperationOutput(
        operation_id="op_model_1", output="A", finish_reason="stop", accounting=None
    )
    assert "decision" not in plain.model_dump(by_alias=True)
    gated = OperationOutput(
        operation_id="op_gate_1",
        output="A",
        finish_reason="stop",
        accounting=None,
        decision=_decision(1, "then", result={"status": "answered", "reason": None}),
    )
    dumped = gated.model_dump(by_alias=True, mode="json")
    assert dumped["decision"]["schema"] == "screamingface.gate-decision.v1"
    assert list(dumped["decision"]) == [
        "schema", "gate_id", "kind", "when", "observed", "passed", "wanted", "branch",
        "selectors", "not_run", "budget", "result", "panel",
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("result", "abstained"),
    [
        ({"status": "abstain", "reason": "gate_not_met"}, True),
        ({"status": "answered", "reason": None}, False),
        (None, False),
    ],
)
def test_final_reference_follows_the_gate_block_to_its_join(result, abstained) -> None:
    # BC#14 / BC#11 (unit half): a root `$gate_1_block` names the Gate's JOIN `op_gate_1`.
    candidate = render(
        expr(
            _gate_block(1, (_model("model_1", "/a"),), "$model_1", (), "''"),
            intent=text("$gate_1_block"),
        )
    )
    operations = [
        OperationOutput(
            operation_id="op_gate_1",
            output="",
            finish_reason="stop",
            accounting=None,
            decision=_decision(1, "then", result=result),
        )
    ]
    assert final_operation_abstained(candidate, operations) is abstained


def test_a_pending_combine_record_is_not_a_provider_call() -> None:
    # BC#30: a phase=decide pending outcome gives output "" and no evidence; the accounting index
    # of the combine route skips it (asserted in test_combine_route_accounting below).
    gate = GateRecord(
        observe="agreement",
        observed=0.5,
        cmp=">=",
        threshold=0.7,
        passed=False,
        branch="fallback",
        otherwise="judge",
    )
    candidate = render(
        expr(
            _model("synthesis_1", "/ensemble/combine/v1"),
            intent=text("$synthesis_1"),
        )
    )
    with capture_operation_calls():
        record_pending_combine_call("/ensemble/combine/v1", {}, gate, "A")
        calls = current_operation_calls()
    assert calls is not None
    assert calls[0].pending and calls[0].gate_record == gate
    operation = _ids(attribute_operation_outputs(candidate, calls))["op_synthesis_1"]
    assert (operation.output, operation.combine, operation.accounting) == ("", None, None)


def test_decision_record_holds_no_prompt_or_answer_text() -> None:
    # BC#29 / GD-I5: the record builder takes no text; random answers never reach its bytes.
    rng = random.Random(1291)
    for _ in range(50):
        answer = "".join(rng.choices(string.ascii_letters + " ", k=40))
        record = _decision(1, "then", result={"status": "answered", "reason": None})
        operation = OperationOutput(
            operation_id="op_gate_1",
            output=answer,
            finish_reason="stop",
            accounting=None,
            decision=record,
        )
        decision_bytes = json.dumps(operation.model_dump(by_alias=True, mode="json")["decision"])
        assert answer not in decision_bytes
