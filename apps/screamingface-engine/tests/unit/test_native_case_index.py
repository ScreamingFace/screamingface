"""Native iteration numbering preserves candidate input and pre-inference validation."""

import json

import pytest

from screamingface_engine.benchmarks.case_context import current_case_position
from screamingface_engine.benchmarks.definition import candidate
from screamingface_engine.benchmarks.protocol import build_evaluation_protocol
from url4 import render
from url4.core.errors import ResolutionError
from url4.peer.server import Url4Node


@pytest.mark.asyncio
async def test_native_index_supplies_one_based_position_without_selector(monkeypatch):
    from screamingface_engine.benchmarks import candidate_adapter
    from screamingface_engine.benchmarks.case_selection import install_cases

    seen = []

    async def evaluate(node, expression, input_text, **kwargs):
        seen.append((input_text, current_case_position()))
        return json.dumps({"answer": input_text})

    monkeypatch.setattr(candidate_adapter, "evaluate_candidate_recipe", evaluate)
    node = Url4Node()
    candidate_adapter.install_candidate_invocation(node)
    install_cases(node, "/cases", lambda: '[{"id":42,"input":"a"},{"id":"007","input":"b"}]')
    node.endpoint("/aggregate")(lambda request: request.context)
    protocol = build_evaluation_protocol(
        cases_route="/cases",
        case_evaluation=candidate(
            "$item.input", case_id="$item.id", case_index="$index", case_count="2", web_search=False
        ),
        selected_case_count=2,
        available_case_count=2,
        aggregate_route="/aggregate",
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
@pytest.mark.parametrize("raw", ["{}", "[]", "[{}]", "[{},42]", "invalid"])
async def test_cases_validate_selected_collection_before_any_model_calls(raw):
    from screamingface_engine.benchmarks.case_selection import install_cases

    node = Url4Node()
    install_cases(node, "/cases", lambda: raw)
    seen = []
    node.endpoint("/answer")(lambda request: seen.append(request.context) or "answer")
    try:
        with pytest.raises(ResolutionError, match="Invalid benchmark case selection"):
            await node.evaluate("/cases()!'2'*(r:0.0:/answer($item)!'answer')!'$r'")
        assert seen == []
    finally:
        await node.aclose()


def test_every_shipped_board_installs_cases_as_validated_processor(tmp_path):
    from screamingface_engine.benchmarks.draco.definition import DRACO_3PASS
    from screamingface_engine.benchmarks.gdpval.definition import GDPVAL_TEXT
    from screamingface_engine.benchmarks.healthbench.definition import HEALTHBENCH_WORST30

    for board in (DRACO_3PASS, GDPVAL_TEXT, HEALTHBENCH_WORST30):
        node = Url4Node()
        board.install(node, tmp_path)
        assert f"/benchmarks/{board.id}/{board.revision}/cases" in node.processor_routes()
