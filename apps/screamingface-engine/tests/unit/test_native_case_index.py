"""Native iteration numbering preserves candidate input and pre-inference validation."""

import json

import pytest

from screamingface_engine.benchmarks.case_context import current_case_position
from screamingface_engine.benchmarks.protocol import attempt_steps, evaluation_protocol
from url4 import CodeCall, render
from url4.core.errors import CollectionError
from url4.peer.server import Url4Node


@pytest.mark.asyncio
async def test_native_index_supplies_one_based_position_without_selector(monkeypatch):
    from screamingface_engine.benchmarks.case_selection import install_cases
    from screamingface_engine.world import candidate_adapter

    seen = []

    async def evaluate(node, expression, input_text, **kwargs):
        seen.append((input_text, current_case_position()))
        return json.dumps({"answer": input_text})

    monkeypatch.setattr(candidate_adapter, "evaluate_candidate_recipe", evaluate)
    node = Url4Node()
    candidate_adapter.install_candidate_invocation(node)
    install_cases(node, "/cases", lambda: '[{"id":42,"input":"a"},{"id":"007","input":"b"}]')

    # WHY code terminals (spec R1/R4): the Case and run terminals are code pointers.
    @node.code("/case")
    def case(call: CodeCall) -> str:
        value = call.input("attempt_1").value
        assert isinstance(value, str)
        return value

    node.code("/aggregate")(lambda call: json.dumps(call.input("evaluations").value))
    protocol = evaluation_protocol(
        cases_route="/cases",
        steps=attempt_steps("$item.input", attempts=1, case_count=2, web_search=False),
        case_terminal="/case",
        run_terminal="/aggregate",
        selected_case_count=2,
        available_case_count=2,
    )
    try:
        await node.evaluate(render(protocol), env={"candidate": "recipe"})
        assert seen == [("a", (1, 2)), ("b", (2, 2))]
        assert "/benchmarks/selected-cases" not in node.processor_routes()
        assert "_sf_case_" not in render(protocol)
        assert "iteration.slice=0:2" in render(protocol)
    finally:
        await node.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["{}", "42", "invalid"])
async def test_cases_validate_selected_collection_before_any_model_calls(raw):
    # WHY narrower (spec R3): the cases are a data reference now, so url4 parses the
    # collection (§5.3.7) and refuses a non-array before any row runs. The retired cases
    # endpoint also refused short or non-object arrays; that check is gone (see the
    # spec's runtime facts).
    from screamingface_engine.benchmarks.case_selection import install_cases

    node = Url4Node()
    install_cases(node, "/cases", lambda: raw)
    seen = []
    node.endpoint("/answer")(lambda request: seen.append(request.context) or "answer")
    node.code("/case")(lambda call: "case")
    try:
        with pytest.raises(CollectionError, match="malformed|not valid JSON"):
            await node.evaluate(
                "(e:0.0:/cases*(c:0.0:$item, r:0.0:/answer?q=($item)!'a')"
                "!/case;iteration.slice=0:2)!/case"
            )
        assert seen == []
    finally:
        await node.aclose()


def test_every_shipped_benchmark_installs_cases_as_a_data_route(tmp_path):
    # WHY a data route (spec R3): the case set is data, not an intent processor.
    from screamingface_engine.benchmarks.medxpert.definition import MEDXPERT

    for benchmark in (MEDXPERT,):
        node = Url4Node()
        benchmark.install(node, tmp_path)
        route = f"/benchmarks/{benchmark.id}/{benchmark.revision}/cases"
        assert node.has_data(route)
        assert route not in node.processor_routes()
