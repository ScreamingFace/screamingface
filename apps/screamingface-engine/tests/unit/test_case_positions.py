"""Selection order, not observation arrival order, owns display positions."""

import asyncio
import json

import pytest

from screamingface_engine.benchmarks.case_context import current_case_id, current_case_position
from screamingface_engine.benchmarks.case_selection import install_cases
from screamingface_engine.benchmarks.definition import candidate_invocation
from screamingface_engine.benchmarks.protocol import evaluation_protocol
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from url4 import CodeCall, render, src
from url4.peer.server import Url4Node


def _answer(call: CodeCall) -> str:
    value = call.input("answer").value
    assert isinstance(value, str)
    return value


def _rows(call: CodeCall) -> str:
    value = call.input("evaluations").value
    return value if isinstance(value, str) else json.dumps(value)


@pytest.mark.asyncio
async def test_selected_positions_repeat_per_candidate_without_changing_input(monkeypatch):
    from screamingface_engine.world import candidate_adapter

    seen = []

    async def evaluate(node, expression, input_text, **kwargs):
        await asyncio.sleep(0)
        seen.append((expression, input_text, current_case_id(), current_case_position()))
        return json.dumps({"answer": input_text})

    monkeypatch.setattr(candidate_adapter, "evaluate_candidate_recipe", evaluate)
    node = Url4Node()
    install_candidate_invocation(node)
    install_cases(
        node,
        "/cases",
        lambda: json.dumps(
            [
                {"id": 42, "input": "first"},
                {"id": "007", "input": "second"},
                {"id": 900, "input": "not selected"},
            ]
        ),
    )
    # WHY (spec 2026-10-20 R1/R3): the per-Case and per-run steps are code mounts.
    node.code("/case")(_answer)
    node.code("/aggregate")(_rows)

    protocol = evaluation_protocol(
        cases_route="/cases",
        steps=(
            src(
                candidate_invocation("$item.input", web_search=False, case_count=2),
                name="answer",
                weight=0.0,
            ),
        ),
        case_terminal="/case",
        run_terminal="/aggregate",
        selected_case_count=2,
        available_case_count=3,
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
    [(-1, 2), (2, 2), (True, 2), (1, False), (1.5, 2), ("1.0", "2"), (1, 9007199254740992)],
)
def test_invalid_positions_are_rejected(position, count):
    from screamingface_engine.benchmarks.case_request import candidate_request
    from url4.core.errors import ResolutionError
    from url4.peer.server import Request

    # WHY (spec 2026-10-20 R2): the facts arrive as the packed source lines of the call.
    context = f"case_id: 42\ncase_index: {position}\ncase_count: {count}\nrecipe: recipe"
    with pytest.raises(ResolutionError, match="Invalid Candidate Invocation sources"):
        candidate_request(Request("/benchmarks/candidate", context, "question", {}))


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


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", ['{"private": "row"}', '"private text"'])
async def test_selection_rejects_invalid_rows_without_payload_leaks(rows):
    # WHY (spec 2026-10-20 R3): the cases are a data reference; URL4 parses the collection,
    # so a body that is not a JSON array of rows fails the run before any Candidate call.
    from url4.core.errors import Url4Error

    node = Url4Node()
    called = []
    install_cases(node, "/cases", lambda: rows)
    node.code("/case")(lambda call: called.append(call) or "")
    node.code("/aggregate")(_rows)
    protocol = evaluation_protocol(
        cases_route="/cases",
        steps=(),
        case_terminal="/case",
        run_terminal="/aggregate",
        selected_case_count=1,
        available_case_count=1,
    )
    with pytest.raises(Url4Error) as caught:
        await node.evaluate(render(protocol))
    await node.aclose()
    assert called == []
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "values",
    [{"case_count": 0}, {"case_count": True}, {"case_count": -1}, {"attempt": 0}],
)
def test_numbering_requires_a_positive_count_and_attempt(values):
    # WHY (spec 2026-10-20 R2): the identity and position sources come together from the
    # iteration (`$item.id`, `$index`), so only the count and the Attempt can be malformed.
    with pytest.raises(ValueError, match="positive integer"):
        candidate_invocation("question", web_search=False, **values)


def test_numbering_is_all_or_nothing():
    numbered = candidate_invocation("question", web_search=False, case_count=2).context
    plain = candidate_invocation("question", web_search=False).context

    assert numbered == "case_id=$item.id, case_index=$index, case_count='2', recipe=$candidate"
    assert plain == "recipe=$candidate"


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", ["[1]", '[{"id": 1}, "private text"]', '[{"id": 1}, null]'])
async def test_a_non_object_row_fails_before_any_candidate_call(rows):
    # INVARIANT (restores the retired cases handler's row check): validation finishes before
    # inference — a row that is not an object fails the run with `benchmark_contract_error`
    # and no paid call.
    from url4.core.errors import Url4Error

    node = Url4Node()
    called = []
    install_cases(node, "/cases", lambda: rows)
    node.code("/case")(lambda call: called.append(call) or "")
    node.code("/aggregate")(_rows)
    protocol = evaluation_protocol(
        cases_route="/cases",
        steps=(),
        case_terminal="/case",
        run_terminal="/aggregate",
        selected_case_count=1,
        available_case_count=1,
    )
    with pytest.raises(Url4Error) as caught:
        await node.evaluate(render(protocol))
    await node.aclose()
    assert called == []
    assert caught.value.code == "benchmark_contract_error"
    assert "private" not in str(caught.value)
