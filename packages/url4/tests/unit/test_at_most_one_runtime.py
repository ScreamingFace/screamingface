"""Executing an ``expand.at_most_one=true`` source in both panels and a code group (C19).

FEATURE: Router Recipe extension, contract C19. Zero elements contribute nothing and no
failure; one element contributes exactly what a plain source holding it contributes, under
the source's own name; two or more fail the source with ``x.expansion_too_many``.

STORY: as a Fusion author, an abstained Router member is absent from the panel rather than
read as an answer, and an answered one keeps its ``member_i`` label.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from url4 import CodeCall, CodeInput, StaticIOLayer, Url4Node
from url4.core.context import Context
from url4.core.errors import ErrorCode, Url4Error
from url4.dag import run
from url4.dag.semantics.code_binding import CodeSlot, expand, pointer_bindings
from url4.observe import NodeFinished, ObservationEvent

MARK = "expand.at_most_one=true"

_BODIES = {
    "https://a": "A",
    "https://b": "B",
    "https://none": "",
    "https://one": '["x"]',
    "https://blank": '[""]',
    "https://two": '["x","y"]',
    "https://scalar": "hello",
}


def _io() -> StaticIOLayer:
    return StaticIOLayer(fetch_map=dict(_BODIES))


class _Calls:
    """A process double: records each call's packed sources, intent and bindings."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, dict[str, object]]] = []

    async def __call__(self, sources: str, intent: str | None, scope: Context) -> str:
        self.calls.append((sources, intent, dict(scope.bindings)))
        return f"{intent}:{sources}"


class _Events:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def on_event(self, event: ObservationEvent) -> None:
        self.events.append(event)

    def failures(self) -> list[NodeFinished]:
        return [e for e in self.events if isinstance(e, NodeFinished) and e.status != "ok"]


def _panel(member: str, *, intent: str = "'go'", tail: str = "") -> str:
    return f"(a:https://a, b:https://b, {member})!{intent}{tail}"


# --- the text panel ---------------------------------------------------------------------


@pytest.mark.parametrize("guard", ["required", "optional"])
@pytest.mark.asyncio
async def test_zero_elements_give_no_position_binding_entry_or_failure(guard: str) -> None:
    process, events = _Calls(), _Events()
    text = _panel(f"*m:https://none;{guard};{MARK}", tail=";quorum=2")
    out = await run(text, _io(), process=process, observer=events)
    assert out == "go:a: A\nb: B"
    [(_, _, bindings)] = process.calls
    assert bindings == {"1": "A", "2": "B", "a": "A", "b": "B"}
    assert events.failures() == []


@pytest.mark.asyncio
async def test_zero_elements_count_zero_for_quorum() -> None:
    process = _Calls()
    text = _panel(f"*m:https://none;required;{MARK}", tail=";quorum=3")
    with pytest.raises(Url4Error) as caught:
        await run(text, _io(), process=process)
    assert caught.value.code == ErrorCode.QUORUM_NOT_MET
    assert process.calls == []


@pytest.mark.parametrize(("url", "element"), [("https://one", "x"), ("https://blank", "")])
@pytest.mark.asyncio
async def test_one_element_packs_and_binds_as_a_plain_named_source(url: str, element: str) -> None:
    process = _Calls()
    out = await run(_panel(f"*m:{url};required;{MARK}", tail=";quorum=3"), _io(), process=process)
    assert out == f"go:a: A\nb: B\nm: {element}"
    [(_, _, bindings)] = process.calls
    assert bindings == {"1": "A", "2": "B", "3": element, "a": "A", "b": "B", "m": element}


@pytest.mark.asyncio
async def test_the_unmarked_expansion_still_packs_bare_and_binds_the_array() -> None:
    # Contrast for the first failing test: only the mark changes the packed entry.
    process = _Calls()
    out = await run(_panel("*m:https://one;required"), _io(), process=process)
    assert out == "go:a: A\nb: B\nx"
    [(_, _, bindings)] = process.calls
    assert bindings["m"] == '["x"]'


# --- failures ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("https://two", "x.expansion_too_many"),
        ("https://scalar", ErrorCode.EXPANSION_NOT_ITERABLE),
    ],
)
@pytest.mark.asyncio
async def test_a_required_marked_source_fails_the_panel(url: str, code: str) -> None:
    process = _Calls()
    with pytest.raises(Url4Error) as caught:
        await run(_panel(f"*m:{url};required;{MARK}"), _io(), process=process)
    assert caught.value.code == code
    assert caught.value.permanent is True
    assert process.calls == []


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("https://two", "x.expansion_too_many"),
        ("https://scalar", ErrorCode.EXPANSION_NOT_ITERABLE),
    ],
)
@pytest.mark.asyncio
async def test_an_optional_marked_source_failure_is_omitted(url: str, code: str) -> None:
    process, events = _Calls(), _Events()
    out = await run(_panel(f"*m:{url};optional;{MARK}"), _io(), process=process, observer=events)
    assert out == "go:a: A\nb: B"
    assert code in {failure.code for failure in events.failures()}


# --- the broadcast panel ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_zero_elements_give_no_part() -> None:
    out = await run(
        _panel(f"*m:https://none;required;{MARK}", intent="*'go'"), _io(), process=_Calls()
    )
    assert json.loads(out) == [
        {"source_position": 1, "source_name": "a", "result": "go:A"},
        {"source_position": 2, "source_name": "b", "result": "go:B"},
    ]


@pytest.mark.asyncio
async def test_broadcast_one_element_is_named_by_its_source() -> None:
    out = await run(
        _panel(f"*m:https://one;required;{MARK}", intent="*'go'"), _io(), process=_Calls()
    )
    assert json.loads(out)[2] == {"source_position": 3, "source_name": "m", "result": "go:x"}


@pytest.mark.parametrize(("quorum", "calls"), [(3, 0), (2, 2)])
@pytest.mark.asyncio
async def test_broadcast_quorum_gate_counts_zero_elements_as_none(quorum: int, calls: int) -> None:
    process = _Calls()
    text = _panel(f"*m:https://none;required;{MARK}", intent="*'go'", tail=f";quorum={quorum}")
    if quorum == 3:
        with pytest.raises(Url4Error) as caught:
            await run(text, _io(), process=process)
        assert caught.value.code == ErrorCode.QUORUM_NOT_MET
    else:
        await run(text, _io(), process=process)
    assert len(process.calls) == calls


# --- the code binding ---------------------------------------------------------------------


def _code_node(code_calls: list[CodeCall]) -> Url4Node:
    node = Url4Node("t", outbound=_io())

    @node.code("/combine")
    def combine(call: CodeCall) -> str:
        code_calls.append(call)
        return "COMBINED"

    return node


@pytest.mark.asyncio
async def test_code_binding_one_element_binds_as_the_name_with_its_weight() -> None:
    code_calls: list[CodeCall] = []
    node = _code_node(code_calls)
    text = f"(a:https://a, *m:0.5:https://one;required;{MARK})!/combine"
    assert await node._run_text(text) == "COMBINED"
    assert [call.inputs for call in code_calls] == [
        (CodeInput(1, "a", "A", None), CodeInput(2, "m", "x", 0.5)),
    ]


@pytest.mark.asyncio
async def test_code_binding_zero_elements_bind_nothing() -> None:
    code_calls: list[CodeCall] = []
    node = _code_node(code_calls)
    text = f"(a:https://a, *m:0.5:https://none;required;{MARK})!/combine"
    assert await node._run_text(text) == "COMBINED"
    assert [call.inputs for call in code_calls] == [(CodeInput(1, "a", "A", None),)]


def test_pointer_bindings_give_a_zero_element_source_no_name() -> None:
    slots = (
        CodeSlot("a", None, True, "text"),
        CodeSlot("m", 0.5, True, "expand", at_most_one=True),
    )
    assert pointer_bindings(slots, ["A", []]) == {"1": "A", "a": "A"}
    assert pointer_bindings(slots, ["A", "x"]) == {"1": "A", "a": "A", "2": "x", "m": "x"}
    assert [entry.name for entry in expand(slots, ["A", []])] == ["a"]


def test_pointer_bindings_keep_the_unmarked_expansion_array() -> None:
    slots = (CodeSlot("m", None, True, "expand"),)
    assert pointer_bindings(slots, [[]]) == {"m": "[]"}


# --- review round: two elements fail like any other source failure --------------------------


class _GatedCalls(_Calls):
    """Opens ``released`` once the process has made ``after`` calls."""

    def __init__(self, after: int) -> None:
        super().__init__()
        self.after = after
        self.released = asyncio.Event()

    async def __call__(self, sources: str, intent: str | None, scope: Context) -> str:
        out = await super().__call__(sources, intent, scope)
        if len(self.calls) >= self.after:
            self.released.set()
        return out


class _GatedIO(StaticIOLayer):
    """Holds the fetch of ``gated`` until the sibling calls are under way; records fetches."""

    def __init__(self, gated: str, process: _GatedCalls) -> None:
        super().__init__(fetch_map=dict(_BODIES))
        self.gated, self.process, self.fetches = gated, process, []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        if target == self.gated:
            # WHY a timeout: if the sibling calls never start, the trace check fails, not hangs.
            await asyncio.wait_for(self.process.released.wait(), timeout=5)
        return await super().fetch(target, relative=relative)


_FAILING_MEMBERS = {
    "x.expansion_too_many": ("https://two", f"*m:https://two;required;{MARK}"),
    ErrorCode.EXPANSION_NOT_ITERABLE: ("https://scalar", "*m:https://scalar;required"),
    ErrorCode.RESOLUTION_FAILED: ("https://missing", "m:https://missing;required"),
}


@pytest.mark.parametrize(
    ("intent", "trace"),
    [
        pytest.param("'outer'", [("A", "inner")], id="text"),
        pytest.param("*'outer'", [("A", "inner"), ("inner:A", "outer")], id="broadcast"),
    ],
)
@pytest.mark.asyncio
async def test_two_elements_fail_the_source_like_any_other_required_failure(
    intent: str, trace: list[tuple[str, str]]
) -> None:
    # WHY: C19 says ;required and ;optional apply to `x.expansion_too_many` as to any other
    # failure. A sibling call already running when a source fails is not undone, for a
    # non-iterable expansion or a missing source alike; the mark adds no barrier (owner
    # decision, 2026-11-21). The failing fetch is held until the sibling calls are made.
    traces = {}
    for code, (url, member) in _FAILING_MEMBERS.items():
        process = _GatedCalls(after=len(trace))
        io = _GatedIO(url, process)
        with pytest.raises(Url4Error) as caught:
            await run(f"(a:('A')!'inner', {member})!{intent}", io, process=process)
        assert caught.value.code == code
        assert io.fetches.count(url) == 1
        traces[code] = [(sources, called) for sources, called, _ in process.calls]
    assert list(traces.values()) == [trace] * len(_FAILING_MEMBERS)


@pytest.mark.asyncio
async def test_broadcast_one_element_makes_one_call_per_source_and_no_more() -> None:
    process = _Calls()
    text = _panel(f"*m:https://one;required;{MARK}", intent="*'go'")
    out = await run(text, _io(), process=process)
    assert json.loads(out) == [
        {"source_position": 1, "source_name": "a", "result": "go:A"},
        {"source_position": 2, "source_name": "b", "result": "go:B"},
        {"source_position": 3, "source_name": "m", "result": "go:x"},
    ]
    assert sorted((sources, intent) for sources, intent, _ in process.calls) == [
        ("A", "go"),
        ("B", "go"),
        ("x", "go"),
    ]


@pytest.mark.parametrize(
    ("routed", "expected"),
    [
        pytest.param("", "go:a: A", id="zero"),
        pytest.param('["x"]', "go:a: A\nm: x", id="one"),
    ],
)
@pytest.mark.asyncio
async def test_an_expression_valued_marked_member_passes_the_envelope_check(
    routed: str, expected: str
) -> None:
    # WHY: the SDK member slot is an expression-valued source; its `;required;<mark>` chain
    # is a source annotation, so the envelope decoder's refusal of the mark as an
    # expression param must not reach it.
    calls: list[tuple[str, str | None]] = []

    async def process(sources: str, intent: str | None, scope: Context) -> str:
        calls.append((sources, intent))
        return routed if intent == "route" else f"{intent}:{sources}"

    text = f"(a:https://a, *m:1.0:(https://b)!'route';required;{MARK})!'go'"
    assert await run(text, _io(), process=process) == expected
    assert calls == [("B", "route"), (expected.removeprefix("go:"), "go")]
