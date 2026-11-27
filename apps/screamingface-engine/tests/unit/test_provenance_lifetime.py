"""A capture scope's provenance channel ends with the scope (contracts C4, C8; Unit 5.2).

FEATURE: Router Recipe extension. A task started inside a capture scope copies the scope's context,
so it can still hold the scope's channel after `capture_operation_calls` has returned.

INVARIANT: a task that outlives the scope it started in behaves as outside every scope: it sees no
scope, reads none of the ended scope's evidence or calls, and writes no fact, call outcome, claim,
step document or call record into the ended scope or into any scope that encloses it. A Router
step there is refused as outside a capture scope (C4 `router_unsupported`), before any read, call
or file check. A scope the late task opens itself is its own.
WHY: an ended scope's evidence was already read by its projection; a late write would reach a
scope that never awaited the work, and a late Router step could prove its context against evidence
that no longer belongs to any running operation.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from router_join_support import EMPTY, assert_failed, draft, join_context
from router_support import (
    BINDING,
    QUESTION,
    REFUSED,
    ROUTES,
    ClassifierPort,
    case,
    fact,
    fixed_definition,
    refusal,
    router_gateway,
    scoped,
    spec_text,
    text,
)

from screamingface_engine.operation_calls import (
    OperationCall,
    capture_operation_calls,
    current_operation_calls,
    latest_operation_call,
    operation_call_identity,
    record_operation_call,
)
from screamingface_engine.operation_provenance import (
    CallOutcome,
    ProvenanceConflict,
    call_outcome,
    claim_step,
    current_attempt_facts,
    latest_attempt_fact,
    provenance_open,
    record_attempt_fact,
    record_call_outcome,
    record_step,
    recorded_step,
)
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.router_admit import RouterPorts, admit, canonical_models
from screamingface_engine.world.router_join import join
from screamingface_engine.world.router_steps import NOT_RUN, StepCall

_OUTCOME = CallOutcome("model_1", "/acme/m", "answered", "hi")


def _view() -> tuple[object, ...]:
    """Everything a Router step can read from the innermost scope it sees."""
    return (
        provenance_open(),
        recorded_step("admit", "router_1"),
        current_attempt_facts(),
        latest_attempt_fact("model_1"),
        call_outcome("model_1"),
    )


def _write_everything() -> None:
    record_attempt_fact(fact("model_1"))
    record_call_outcome(_OUTCOME)
    claim_step("admit", "router_1")
    record_step("admit", "router_1", {"input": "late"})


def test_a_child_that_outlives_its_scope_sees_no_scope() -> None:
    async def run() -> tuple[tuple[object, ...], tuple[object, ...]]:
        release = asyncio.Event()
        views: list[tuple[object, ...]] = []

        async def child() -> None:
            views.append(_view())
            await release.wait()
            views.append(_view())

        with capture_operation_calls():
            record_step("admit", "router_1", {"input": "q"})
            record_attempt_fact(fact("model_1"))
            record_call_outcome(_OUTCOME)
            task = asyncio.create_task(child())
            await asyncio.sleep(0)
        release.set()
        await task
        return views[0], views[1]

    inside, after = asyncio.run(run())

    assert inside == (True, '{"input":"q"}', (fact("model_1"),), fact("model_1"), _OUTCOME)
    assert after == (False, None, None, None, None)


def test_a_late_router_step_is_refused_as_outside_a_capture_scope() -> None:
    async def run() -> list[str]:
        release = asyncio.Event()
        refusals: list[str] = []

        async def child() -> None:
            await release.wait()
            claim_step("admit", "router_1")
            try:
                record_step("admit", "router_1", {"input": "late"})
            except ProvenanceConflict as refusal:
                refusals.append(str(refusal))

        with capture_operation_calls():
            task = asyncio.create_task(child())
            await asyncio.sleep(0)
        release.set()
        await task
        return refusals

    assert asyncio.run(run()) == ["router admit runs outside a capture scope"]


@pytest.mark.parametrize("isolated", [False, True], ids=["nested", "isolated"])
def test_a_late_child_writes_nothing_into_a_scope_that_is_still_open(isolated: bool) -> None:
    async def run() -> tuple[tuple[object, ...], tuple[object, ...]]:
        release = asyncio.Event()

        async def late() -> None:
            await release.wait()
            record_attempt_fact(fact("model_1"))
            record_call_outcome(_OUTCOME)
            claim_step("admit", "router_1")
            with pytest.raises(ProvenanceConflict, match="outside a capture scope"):
                record_step("admit", "router_1", {"input": "late"})

        async def on_time() -> None:
            record_attempt_fact(fact("model_2"))

        with capture_operation_calls():
            with capture_operation_calls(isolated=isolated):
                task = asyncio.create_task(late())
                await asyncio.create_task(on_time())
            release.set()
            await task
            outer = (current_attempt_facts(), call_outcome("model_1"))
            # INVARIANT: the outer scope can still run its own ADMIT for this binding.
            claim_step("admit", "router_1")
            record_step("admit", "router_1", {"input": "outer"})
            return outer, (recorded_step("admit", "router_1"),)

    (facts, outcome), (step,) = asyncio.run(run())

    assert facts == (() if isolated else (fact("model_2"),))
    assert outcome is None
    assert step == '{"input":"outer"}'


def test_a_child_awaited_inside_its_scope_still_writes() -> None:
    async def run() -> tuple[object, ...]:
        async def child() -> None:
            _write_everything()

        with capture_operation_calls():
            await asyncio.create_task(child())
            return _view()

    assert asyncio.run(run()) == (
        True,
        '{"input":"late"}',
        (fact("model_1"),),
        fact("model_1"),
        _OUTCOME,
    )


def test_two_late_children_share_no_ended_scope() -> None:
    async def run() -> tuple[object, ...]:
        first_done = asyncio.Event()
        release = asyncio.Event()
        seen: list[tuple[object, ...]] = []

        async def writer() -> None:
            await release.wait()
            claim_step("admit", "router_1")
            record_attempt_fact(fact("model_1"))
            record_call_outcome(_OUTCOME)
            first_done.set()

        async def reader() -> None:
            await first_done.wait()
            seen.append(_view())

        with capture_operation_calls():
            tasks = (asyncio.create_task(writer()), asyncio.create_task(reader()))
            await asyncio.sleep(0)
        release.set()
        await asyncio.gather(*tasks)
        return seen[0]

    assert asyncio.run(run()) == (False, None, None, None, None)


def test_a_scope_a_late_child_opens_reaches_no_ended_or_enclosing_scope() -> None:
    async def run() -> tuple[object, object]:
        release = asyncio.Event()
        own: list[object] = []

        async def late() -> None:
            await release.wait()
            with capture_operation_calls():
                record_attempt_fact(fact("model_1"))
                own.append(current_attempt_facts())

        with capture_operation_calls():
            with capture_operation_calls():
                task = asyncio.create_task(late())
                await asyncio.sleep(0)
            release.set()
            await task
            return own[0], current_attempt_facts()

    own, outer = asyncio.run(run())

    assert own == (fact("model_1"),)
    assert outer == ()


def test_a_child_scope_that_outlives_its_starting_scope_keeps_only_itself() -> None:
    async def run() -> tuple[object, object]:
        opened = asyncio.Event()
        release = asyncio.Event()
        own: list[object] = []

        async def child() -> None:
            with capture_operation_calls():
                opened.set()
                await release.wait()
                record_attempt_fact(fact("model_1"))
                own.append((provenance_open(), current_attempt_facts()))

        with capture_operation_calls():
            with capture_operation_calls():
                task = asyncio.create_task(child())
                await opened.wait()
            release.set()
            await task
            return own[0], current_attempt_facts()

    own, outer = asyncio.run(run())

    assert own == (True, (fact("model_1"),))
    assert outer == ()


# --- the operation-call recorders end with the same scope ----------------------------------------


def _call(output: str) -> None:
    """Publish one bound model call's terminal record, as the connector does."""
    with operation_call_identity("/acme/m", {"binding": "model_1"}):
        record_operation_call(output, "stop")


def _outputs(recorder: list[OperationCall]) -> list[str]:
    return [call.output for call in recorder]


@pytest.mark.parametrize("isolated", [False, True], ids=["nested", "isolated"])
def test_a_late_child_reads_and_publishes_no_operation_call(isolated: bool) -> None:
    async def run() -> tuple[object, list[str], list[str]]:
        release = asyncio.Event()
        seen: list[object] = []

        async def late() -> None:
            await release.wait()
            seen.append((current_operation_calls(), latest_operation_call(lambda _call: True)))
            _call("late")

        with capture_operation_calls() as outer:
            _call("outer")
            with capture_operation_calls(isolated=isolated) as inner:
                _call("inner")
                task = asyncio.create_task(late())
                await asyncio.sleep(0)
            release.set()
            await task
        return seen[0], _outputs(outer), _outputs(inner)

    seen, outer, inner = asyncio.run(run())

    assert seen == (None, None)
    assert outer == (["outer"] if isolated else ["outer", "inner"])
    assert inner == ["inner"]


def test_a_late_admit_refuses_before_any_read_call_or_file_check() -> None:
    gateway = router_gateway()
    checked: list[str] = []

    async def files() -> None:
        checked.append("files")

    async def scenario() -> str:
        release = asyncio.Event()
        async with gateway.client() as client:
            models = canonical_models(ROUTES)
            ports = RouterPorts(client=client, models=models, classify=ClassifierPort())
            call = StepCall(text({"input": QUESTION}), spec_text(fixed_definition()), BINDING)

            async def late() -> str:
                await release.wait()
                return await admit(ports, call, files)

            with case():
                task = asyncio.create_task(late())
                await asyncio.sleep(0)
            release.set()
            return await task

    result = scoped(scenario)

    # INVARIANT (C4): the ended scope's recorder would lose the Router's record, so ADMIT refuses
    # exactly as outside every scope: no preflight, no classifier read, no run-file check.
    assert json.loads(result) == refusal("router_unsupported")
    assert gateway.calls() == []
    assert checked == []


def test_a_late_join_publishes_into_no_recorder() -> None:
    context = join_context(REFUSED, draft(REFUSED, NOT_RUN), **EMPTY)

    async def run() -> tuple[object, list[OperationCall], list[OperationCall]]:
        release = asyncio.Event()

        async def late() -> object:
            await release.wait()
            try:
                return join(StepCall(context, "", BINDING))
            except RunnerRequestError as failure:
                return failure

        with case() as outer:
            with case() as inner:
                task = asyncio.create_task(late())
                await asyncio.sleep(0)
            release.set()
            value = await task
            return value, outer, inner

    value, outer, inner = asyncio.run(run())

    # WHY a carried refusal: it is the one JOIN that needs no recorded evidence, so only the
    # recorder lifetime stands between it and the list the ended scope already returned.
    assert_failed(value, "router_definition_invalid", permanent=True)
    assert (outer, inner) == ([], [])


@pytest.mark.parametrize("isolated", [False, True], ids=["nested", "isolated"])
def test_a_scope_a_late_child_opens_records_its_own_calls_only(isolated: bool) -> None:
    async def run() -> tuple[object, list[str], list[str]]:
        release = asyncio.Event()
        own: list[object] = []

        async def late() -> None:
            await release.wait()
            with capture_operation_calls(isolated=isolated) as mine:
                _call("late")
                snapshot = current_operation_calls()
                own.append((None if snapshot is None else _outputs(list(snapshot)), _outputs(mine)))

        with capture_operation_calls() as outer:
            with capture_operation_calls() as inner:
                task = asyncio.create_task(late())
                await asyncio.sleep(0)
            release.set()
            await task
            return own[0], _outputs(outer), _outputs(inner)

    own, outer, inner = asyncio.run(run())

    assert own == (["late"], ["late"])
    assert (outer, inner) == ([], [])
