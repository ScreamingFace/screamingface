"""Property tests for code-group binding, the gate and the call count (contracts C3, C4).

STORY: a code-pointer group hands its code exactly the inputs the Lean model binds, calls it
once for the aggregate or once per resolved source under broadcast, and opens its gate by the
quorum rule, over random source lists.

FEATURE: code-pointer intents run as RDS calls. The oracle below is a direct transcription of
``docs/spec/2026-10-10-url4-rds-code-pointer/formal/Url4Rds/{Binding,Gate,Expansion}.lean``.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

import pytest

from url4.core.code import CodeCall, CodeValue, CodeWeight
from url4.core.errors import ParseError
from url4.dag.semantics.code_binding import (
    CodeSlot,
    Quorum,
    Settled,
    SlotKind,
    SlotResult,
    bind,
    broadcast_calls,
    code_quorum,
    expand,
    gate_open,
    needed,
    pointer_bindings,
)

_SEED = 20261010
_SAMPLES = 300

_NAME_POOL = ("a", "b", "member_1", "src")
_NAMES: tuple[str | None, ...] = (None, *_NAME_POOL)
_WEIGHTS: tuple[CodeWeight | None, ...] = (None, 0.0, 0.5, 1.0, {"accuracy": 0.6})
_KINDS: tuple[SlotKind, ...] = ("text", "json", "expand")
_CHARS = "ab \n\t\"'%&()\\éü✓{}[]:,0123"
_JSON_LIKE = ("", '{"k": "v"}', "[1, 2]")

type _Bound = tuple[int, str | None, CodeWeight | None, CodeValue]


@dataclass(frozen=True, slots=True)
class _Entry:
    """A source after expansion: the fields of Lean ``Binding.Source`` and its value."""

    name: str | None
    weight: CodeWeight | None
    required: bool
    resolved: bool
    payload: CodeValue


def _model_share(weight: CodeWeight | None, count: int) -> CodeWeight | None:
    """Spec B §5.3.12.6: each of ``count`` elements carries ``declared / count``."""
    if weight is None:
        return None
    if isinstance(weight, Mapping):
        return {key: value / count for key, value in weight.items()}
    return weight / count


def _model_value(kind: SlotKind, text: SlotResult) -> CodeValue:
    """C3 value typing: ``text`` keeps the string, ``json`` decodes it, and an expansion
    element decodes when it is an object (the generator makes no other structured element)."""
    if text is None:
        return None
    assert isinstance(text, str)
    if kind == "json" or (kind == "expand" and text.startswith("{")):
        return json.loads(text)
    return text


def _model_expand(slots: Sequence[CodeSlot], results: Sequence[SlotResult]) -> list[_Entry]:
    """Lean ``Expansion.expandAll``: an expansion of N elements becomes N entries named
    ``name[i]`` (``src[i]`` unnamed, 0-based) with weight ``declared / N``; a failed
    expansion stays ONE failed entry."""
    entries: list[_Entry] = []
    for slot, result in zip(slots, results, strict=True):
        if slot.kind == "expand" and isinstance(result, list):
            for i, element in enumerate(result):
                name = f"{slot.name or 'src'}[{i}]"
                share = _model_share(slot.weight, len(result))
                entries.append(
                    _Entry(name, share, slot.required, True, _model_value("expand", element))
                )
        else:
            resolved = result is not None
            value = _model_value(slot.kind, result)
            entries.append(_Entry(slot.name, slot.weight, slot.required, resolved, value))
    return entries


def _model_bind(entries: Sequence[_Entry]) -> list[_Bound]:
    """Lean ``Binding.bind`` = ``bindFrom 1``: the entry at index k (1-based) gives the input
    ``(k, name, weight, payload)`` when resolved; a failed entry gives no input at all."""
    return [(k, e.name, e.weight, e.payload) for k, e in enumerate(entries, start=1) if e.resolved]


def _model_gate(entries: Sequence[_Entry], quorum: Quorum) -> bool:
    """Lean ``Gate.gate`` = ``requiredOk && quorumOk``: every required entry resolved, and the
    resolved count meets the floor (``all`` adds nothing, ``N`` is N, ``majority`` is
    ``length / 2 + 1`` over the post-expansion total)."""
    resolved = sum(e.resolved for e in entries)
    required_ok = all(e.resolved for e in entries if e.required)
    if quorum is None:
        quorum_ok = True
    elif quorum == "majority":
        quorum_ok = len(entries) // 2 + 1 <= resolved
    else:
        quorum_ok = quorum <= resolved
    return required_ok and quorum_ok


def _model_texts(results: Sequence[SlotResult]) -> list[str | None]:
    """The text of each post-expansion source, in order (None when failed): an expansion
    contributes its elements, any other source its one text."""
    texts: list[str | None] = []
    for result in results:
        if isinstance(result, list):
            texts.extend(result)
        else:
            texts.append(result)
    return texts


def _model_call(model: Sequence[_Bound], head: _Bound, refs: set[str]) -> list[_Bound]:
    """Lean ``calls`` for ``!*``: the call's own source first, then every other resolved
    source that the pointer names (by name or position), in position order."""
    rest = [t for t in model if t[0] != head[0] and (t[1] in refs or str(t[0]) in refs)]
    return [head, *rest]


def _random_text(rng: random.Random) -> str:
    """Text with newlines, quotes, ``%``, ``&``, parens, backslashes, non-ASCII, JSON-like."""
    if rng.random() < 0.2:
        return rng.choice(_JSON_LIKE)
    return "".join(rng.choice(_CHARS) for _ in range(rng.randint(0, 12)))


def _json_text(rng: random.Random) -> str:
    """Valid JSON for a ``json`` source: an object or an array."""
    if rng.random() < 0.5:
        return json.dumps({"k": _random_text(rng), "n": rng.randint(0, 9)})
    return json.dumps([rng.randint(0, 9), _random_text(rng)])


def _elements(rng: random.Random) -> list[str]:
    """Expansion elements: ``{"a": 1}`` objects, or plain text that never opens with ``[``
    or ``{``, so each element's typed value is known."""
    elements: list[str] = []
    for _ in range(rng.randint(0, 3)):
        if rng.random() < 0.3:
            elements.append('{"a": 1}')
        else:
            plain = _random_text(rng)
            elements.append("x" + plain if plain[:1] in ("[", "{") else plain)
    return elements


def _result(rng: random.Random, kind: SlotKind) -> SlotResult:
    """A settled source: None (failed), its text, or for an expansion its elements."""
    if kind == "expand":
        return None if rng.random() < 0.25 else _elements(rng)
    if rng.random() < 0.25:
        return None
    return _json_text(rng) if kind == "json" else _random_text(rng)


def _weight(rng: random.Random) -> CodeWeight | None:
    return rng.choice(_WEIGHTS)


def _other_weight(rng: random.Random, current: CodeWeight | None) -> CodeWeight | None:
    """A weight different from ``current``, so every weight really changes."""
    return rng.choice([w for w in _WEIGHTS if w != current])


def _case(
    rng: random.Random, required: bool | None = None
) -> tuple[list[CodeSlot], list[SlotResult]]:
    """A random source list: 0-8 slots, random names (with duplicates), weights, kinds and
    results. ``required`` pins every slot's flag when given."""
    slots: list[CodeSlot] = []
    results: list[SlotResult] = []
    for _ in range(rng.randint(0, 8)):
        kind = rng.choice(_KINDS)
        is_required = rng.random() < 0.5 if required is None else required
        slots.append(CodeSlot(rng.choice(_NAMES), _weight(rng), is_required, kind))
        results.append(_result(rng, kind))
    return slots, results


def _quorums(total: int) -> list[Quorum]:
    """Every quorum the gate can take over ``total`` sources."""
    return [None, "majority", *range(total + 2)]


def _flip(settled: Sequence[Settled], index: int) -> list[Settled]:
    """The same list with the source at ``index`` resolved (Lean ``Improves``: flags and
    order are kept)."""
    return [replace(s, text="x", value="x") if k == index else s for k, s in enumerate(settled)]


def _check_gate(settled: Sequence[Settled], entries: Sequence[_Entry]) -> None:
    total = len(settled)
    failed_required = any(e.required and not e.resolved for e in entries)
    for quorum in _quorums(total):
        opened = gate_open(settled, quorum)
        assert opened == _model_gate(entries, quorum), quorum
        assert not failed_required or not opened, quorum
        if opened:
            for index, entry in enumerate(entries):
                if not entry.resolved:
                    assert gate_open(_flip(settled, index), quorum), (index, quorum)
    assert needed(total, "majority") == total // 2 + 1
    assert needed(total, None) is None


def _refs(rng: random.Random, total: int) -> set[str]:
    """A ``$``-reference set: some pool names and some positions (some are absent)."""
    refs = {name for name in _NAME_POOL if rng.random() < 0.3}
    refs |= {str(p) for p in range(1, total + 2) if rng.random() < 0.3}
    return refs


def test_binding_matches_model() -> None:
    """Lean ``find?_pos_bind``, ``length_bind`` and ``pairwise_pos_bind``: positions are 1..T
    after expansion; ``bind`` equals the oracle; each input finds itself at its position; a
    failed position finds nothing; inputs are in strictly increasing position order."""
    rng = random.Random(_SEED)
    for _ in range(_SAMPLES):
        slots, results = _case(rng)
        settled = expand(slots, results)
        entries = _model_expand(slots, results)
        total = len(entries)
        inputs = bind(settled)
        assert [s.position for s in settled] == list(range(1, total + 1))
        assert [(i.position, i.name, i.weight, i.value) for i in inputs] == _model_bind(entries)
        assert len(inputs) == sum(e.resolved for e in entries)
        for p in range(0, total + 2):
            hits = [i.value for i in inputs if i.position == p]
            resolved_here = 1 <= p <= total and entries[p - 1].resolved
            assert hits == ([entries[p - 1].payload] if resolved_here else [])
        positions = [i.position for i in inputs]
        assert all(a < b for a, b in zip(positions, positions[1:]))


def test_weight_never_filters_delivery() -> None:
    """Lean ``payload_bind_reweigh``: changing every weight changes no input's position, name
    or value; with every weight 0.0, each resolved source is still delivered, weight 0.0."""
    rng = random.Random(_SEED)
    for _ in range(_SAMPLES):
        slots, results = _case(rng)
        before = bind(expand(slots, results))
        changed = [replace(slot, weight=_other_weight(rng, slot.weight)) for slot in slots]
        after = bind(expand(changed, results))
        assert [(i.position, i.name, i.value) for i in after] == [
            (i.position, i.name, i.value) for i in before
        ]
        zeroed = bind(expand([replace(slot, weight=0.0) for slot in slots], results))
        assert len(zeroed) == len(before)
        assert all(i.weight == 0.0 for i in zeroed)


def test_gate_matches_model() -> None:
    """Lean ``gate_eq_false_of_required_failed``, ``gate_mono`` and
    ``gate_all_of_all_optional``, with the ``needed`` floor: over random settled lists and
    every quorum (None, 0..T+1, majority), ``gate_open`` equals the oracle; a failed required
    source always closes the gate; resolving one more failed source never closes an open gate;
    an all-optional group with quorum None is open even when every source failed."""
    rng = random.Random(_SEED)
    for _ in range(_SAMPLES):
        slots, results = _case(rng)
        _check_gate(expand(slots, results), _model_expand(slots, results))
        optional_slots, optional_results = _case(rng, required=False)
        assert gate_open(expand(optional_slots, optional_results), None)


def test_expansion_shape() -> None:
    """Lean ``resolvedCount_expandWith_expand``: a resolved expansion of N elements gives N
    resolved entries named ``name[i]`` (``src[i]`` unnamed, 0-based) with weight ``declared /
    N``. A failed expansion stays ONE failed entry under the slot's own name and weight
    (Spec B §5.3.12.4-6)."""
    rng = random.Random(_SEED)
    for _ in range(_SAMPLES):
        name = rng.choice(_NAMES)
        weight = _weight(rng)
        required = rng.random() < 0.5
        slot = CodeSlot(name, weight, required, "expand")
        elements = _elements(rng)
        count = len(elements)
        out = expand([slot], [elements])
        assert len(out) == count
        assert all(s.resolved for s in out)
        assert [s.name for s in out] == [f"{name or 'src'}[{i}]" for i in range(count)]
        assert [s.position for s in out] == list(range(1, count + 1))
        assert [s.weight for s in out] == [_model_share(weight, count) for _ in range(count)]
        failed = expand([slot], [None])
        assert [(s.name, s.weight, s.required, s.resolved) for s in failed] == [
            (name, weight, required, False)
        ]


def test_unnamed_expansions_collide() -> None:
    """Lean ``unnamed_expansions_collide``: two unnamed non-empty expansions both produce
    ``src[0]``, so a name is not a key. ``CodeCall.input`` refuses the name (ValueError) while
    the position still finds each input (open question Q4)."""
    slots = [CodeSlot(None, None, False, "expand"), CodeSlot(None, None, False, "expand")]
    settled = expand(slots, [["a", "b"], ["c"]])
    assert [s.name for s in settled] == ["src[0]", "src[1]", "src[0]"]
    call = CodeCall(pointer="/x", params={}, inputs=bind(settled))
    with pytest.raises(ValueError):
        call.input("src[0]")
    assert call.input(1).value == "a"
    assert call.input(3).value == "c"
    assert call.input("src[1]").value == "b"


def test_value_typing_by_form() -> None:
    """C3 value typing comes from the source form: text keeps the exact string (even JSON
    text); json decodes; an expansion element decodes when it is an object and stays str
    otherwise; a rows source with a list payload gives a list."""
    body = '{"k": "v", "n": 3}'
    (text,) = expand([CodeSlot("t", None, False, "text")], [body])
    assert text.value == body
    assert isinstance(text.value, str)
    (decoded,) = expand([CodeSlot("j", None, False, "json")], [body])
    assert decoded.value == {"k": "v", "n": 3}
    exact = 'line one\n"quoted" 100% & (x) \\ naïve ✓'
    (raw,) = expand([CodeSlot(None, None, False, "text")], [exact])
    assert raw.value == exact
    elements = expand([CodeSlot("e", None, False, "expand")], [['{"a": 1}', "plain"]])
    assert [s.value for s in elements] == [{"a": 1}, "plain"]
    (rows,) = expand([CodeSlot("r", None, False, "rows")], [['{"a": 1}', "x"]])
    # WHY exact strings: a row is the per-element result text (B §5.3.8), never content-typed.
    assert rows.value == ['{"a": 1}', "x"]


def test_broadcast_calls_model() -> None:
    """Lean ``length_calls_broadcast``, ``head?_inputs_of_mem_calls_broadcast`` and
    ``length_inputs_of_mem_calls_broadcast``: one call per resolved source, in order; each
    call's first input is its own source; the rest are the other resolved sources that the
    pointer names (by name or position), in position order. With no reference, every call has
    exactly one input (Spec B §6.1.2)."""
    rng = random.Random(_SEED)
    for _ in range(_SAMPLES):
        slots, results = _case(rng)
        settled = expand(slots, results)
        model = _model_bind(_model_expand(slots, results))
        refs = _refs(rng, len(settled))
        calls = broadcast_calls(settled, refs)
        assert len(calls) == len(model)
        assert [cur.position for cur, _ in calls] == [head[0] for head in model]
        got = [[(i.position, i.name, i.weight, i.value) for i in inputs] for _, inputs in calls]
        assert got == [_model_call(model, head, refs) for head in model]
        assert all(len(inputs) == 1 for _, inputs in broadcast_calls(settled, set()))


def test_code_quorum_values() -> None:
    """The ``quorum=`` param of a code group: ``all`` or no value is None, ``majority`` is
    ``"majority"``, an integer is that int, and anything else is a ParseError (C §12.2)."""
    assert code_quorum(()) is None
    assert code_quorum((("quorum", "all"),)) is None
    assert code_quorum((("quorum", None),)) is None
    assert code_quorum((("quorum", "majority"),)) == "majority"
    assert code_quorum((("quorum", "2"),)) == 2
    with pytest.raises(ParseError):
        code_quorum((("quorum", "x"),))


def test_pointer_bindings_named_and_failed() -> None:
    """``pointer_bindings`` mirrors the group's gather: positions after expansion; a named
    expansion binds the JSON array of its elements; a failed source binds nothing but still
    takes its position."""
    slots = [
        CodeSlot(None, None, False),
        CodeSlot("m", None, False, "expand"),
        CodeSlot("b", None, False),
        CodeSlot("e", None, False, "expand"),
        CodeSlot("c", None, False),
    ]
    results: list[SlotResult] = ["a", ["x", "y"], None, None, "c"]
    bindings = pointer_bindings(slots, results)
    assert json.loads(bindings.pop("m")) == ["x", "y"]
    assert bindings == {"1": "a", "2": "x", "3": "y", "6": "c", "c": "c"}


def test_pointer_bindings_follow_positions() -> None:
    """``pointer_bindings`` over random sources: every resolved post-expansion position maps to
    its text, and a failed position has no key (it takes its position and binds nothing)."""
    rng = random.Random(_SEED)
    for _ in range(_SAMPLES):
        slots, results = _case(rng)
        bindings = pointer_bindings(slots, results)
        texts = _model_texts(results)
        positional = {k: v for k, v in bindings.items() if k.isdigit()}
        assert positional == {str(p): t for p, t in enumerate(texts, start=1) if t is not None}
