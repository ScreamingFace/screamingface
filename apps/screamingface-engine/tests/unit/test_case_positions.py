"""Selection order, not observation arrival order, owns display positions."""

import asyncio
import json

import pytest

from screamingface_engine.benchmarks.candidate_adapter import install_candidate_invocation
from screamingface_engine.benchmarks.case_context import current_case_id, current_case_position
from screamingface_engine.benchmarks.definition import candidate
from screamingface_engine.benchmarks.protocol import build_evaluation_protocol
from url4 import render
from url4.peer.server import Url4Node


@pytest.mark.asyncio
async def test_selected_positions_repeat_per_candidate_without_changing_input(monkeypatch):
    from screamingface_engine.benchmarks import candidate_adapter

    seen = []

    async def evaluate(node, expression, input_text, **kwargs):
        await asyncio.sleep(0)
        seen.append((expression, input_text, current_case_id(), current_case_position()))
        return json.dumps({"answer": input_text})

    monkeypatch.setattr(candidate_adapter, "evaluate_candidate_recipe", evaluate)
    node = Url4Node()
    install_candidate_invocation(node)
    node.data(
        "/cases",
        json.dumps(
            [
                {"id": 42, "input": "first"},
                {"id": "007", "input": "second"},
                {"id": 900, "input": "not selected"},
            ]
        ),
        media_type="application/json",
    )

    @node.endpoint("/aggregate")
    def aggregate(request):
        return request.context

    protocol = build_evaluation_protocol(
        cases_route="/cases",
        case_evaluation=candidate(
            "$item.input",
            case_id="$item.id",
            case_position="$item._sf_case_position",
            case_count="$item._sf_case_count",
            web_search=False,
        ),
        selected_case_count=2,
        available_case_count=3,
        aggregate_route="/aggregate",
    )
    await asyncio.gather(
        *(node.evaluate(render(protocol), env={"candidate": name}) for name in ("A", "B"))
    )
    await node.aclose()
    for name in ("A", "B"):
        assert [item[1:] for item in seen if item[0] == name] == [
            ("first", "42", (1, 2)),
            ("second", "007", (2, 2)),
        ]
    assert current_case_position() is None


@pytest.mark.parametrize(
    "position,count",
    [(0, 2), (3, 2), (True, 2), (1, False), (1.5, 2), ("1.0", "2"), (1, 9007199254740992)],
)
def test_invalid_positions_are_rejected(position, count):
    from screamingface_engine.benchmarks.case_request import candidate_position
    from url4.core.errors import ResolutionError
    from url4.peer.server import Request

    with pytest.raises(ResolutionError, match="Invalid candidate case position"):
        candidate_position(
            Request(
                "/benchmarks/candidate",
                json.dumps(
                    {
                        "input": "question",
                        "case_id": "42",
                        "case_position": position,
                        "case_count": count,
                    }
                ),
                "recipe",
                {"context_format": "case-v1"},
            )
        )


def test_position_scope_masks_nested_runs_and_unlabelled_calls():
    from screamingface_engine.benchmarks.case_context import case_scope
    from screamingface_engine.observations import RunObservations

    with case_scope("42", position=(1, 100)):
        assert current_case_position() == (1, 100)
        with RunObservations(()).bind():
            assert current_case_position() is None
        with case_scope(None):
            assert current_case_position() is None
        assert current_case_position() == (1, 100)
    assert current_case_position() is None


@pytest.mark.parametrize(
    "rows,count",
    [("{}", "1"), ("[]", "1"), ("[{}]", "2"), ("[{}]", "0"), ("[1]", "1"), ("[]", "invalid")],
)
def test_selection_rejects_invalid_rows_without_payload_leaks(rows, count):
    from screamingface_engine.benchmarks.case_selection import _select
    from url4.core.errors import ResolutionError
    from url4.peer.server import Request

    with pytest.raises(ResolutionError, match="Invalid benchmark case selection"):
        _select(Request("/benchmarks/selected-cases", rows, count, {}))


def test_numbering_requires_case_identity_and_a_complete_pair():
    from screamingface_engine.benchmarks.definition import candidate_call

    for values in (
        {"case_position": "1", "case_count": "2"},
        {"case_id": "$item.id", "case_position": "1"},
    ):
        with pytest.raises(ValueError, match="Case"):
            candidate_call("question", web_search=False, **values)
