"""The url4 rebuild and replay of a consistency recipe (E4b part 7, unit 5: CB#1-9).

FEATURE: ``sf.Url4(url4).to_python()`` gives back ``signals={'cons': sf.Consistency(n=3,
temperature=1.0)}`` and the members as written, without the sample calls; a replay of the url4
shows the compile's operations (kind ``sample``) and pins the match operators before any spend.
STORY: as a researcher who gets the url4 of a consistency recipe, I read, edit and run the method
again; a hand-edited url4 (a changed seed, a missing sample) fails with an existing "cannot
rebuild" error and never rebuilds as something else.
INVARIANT defended: a url4 without consistency rebuilds as before (CB-D1); every consistency url4
takes the byte-for-byte recompile (C5); a sample seed is never a fixed-seed call (P18).
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from dataclasses import replace
from typing import Any, NoReturn, cast

import pytest
from _combine_contract import engine_operators, read_contract, requires_engine_app
from _nodes import FusionNode
from test_consistency_contract_fixtures import BUILDERS
from url4 import Binding, Expression, RelExpr, Source, Text, build, expr, render, src, text

import screamingface as sf
from screamingface._evaluation.candidate import _CompiledCandidate, compile_candidate
from screamingface._evaluation.combine_spec import (
    canonical_json,
    decode_combine_spec,
    spec_operator_pairs,
)
from screamingface._evaluation.model import Candidate
from screamingface._evaluation.operators import _OperatorCatalog
from screamingface._evaluation.topology import _topology_bindings, _topology_from_expression
from screamingface._evaluation.url4 import (
    _candidate_from_url4,
    _replayed_url4,
    _stamped_sitting,
    evaluate_url4_sync,
)
from screamingface._surface.lowering import lower
from screamingface.signal_sources import declared_from_spec
from screamingface.url4 import _calls, _candidate_expression, _combine_operator_pairs

_MEMBERS = ["prov/alpha", "prov/beta", "prov/gamma"]
_PICK = "consistency_pick_candidate.url4"
_MEDIAN = "consistency_median_candidate.url4"
# The four C5 texts (contracts C5), written out: the oracle is not read from the code.
_TOPOLOGY = "URL4 Candidate Recipe topology does not match its model calls"
_METADATA = "URL4 Candidate does not match its Recipe metadata"
_REDUCER = "URL4 Candidate has invalid Reducer topology metadata"
_CANNOT_REBUILD = "URL4 Candidate has a signals declaration this SDK version cannot rebuild"
_MATCH: dict[str, Any] = {
    "extract": {"args": {}, "op": "last_line@1"},
    "normalize": {"args": {}, "op": "text@1"},
}
# Test-plan §6 list L5, taken on 633fec3a1. A FIXED tuple, never a glob (test-plan §2).
_L5: tuple[str, ...] = (
    "vote_candidate.url4",
    "quorum_vote_candidate.url4",
    "logprob_pick_mean_candidate.url4",
    "gate_judge_vote_candidate.url4",
    "samples_vote_candidate.url4",
)


def _f1() -> sf.Recipe:
    """F1 (consistency-api §3): the recipe of consistency_pick_candidate.url4."""
    return sf.Fanout(_MEMBERS, signals={"cons": sf.Consistency(n=3)}, name="pick") >> sf.ArgMax(
        "cons"
    )


def _f2() -> sf.Recipe:
    """F2 (consistency-api §3): the recipe of consistency_median_candidate.url4."""
    return (
        sf.Fanout(_MEMBERS, signals={"cons": sf.Consistency(n=2, temperature=0.7)}, name="median")
        >> sf.Median()
    )


def _f3() -> sf.Recipe:
    """F3 (CB-3): a judge-weighted vote (one signal call judge_1) with one sample per member.

    WHY weights=: sf.Vote reads its judge only through weights=sf.signal('score:judge') (D-1).
    """
    return (
        sf.Fanout(_MEMBERS, signals={"cons": sf.Consistency(n=1)})
        >> sf.Judge("prov/judge", rubric="Score each answer from 0 to 10.")
        >> sf.Vote(weights=sf.signal("score:judge"))
    )


_RECIPES: dict[str, Callable[[], sf.Recipe]] = {"F1": _f1, "F2": _f2}
_FIXTURES: dict[str, str] = {"F1": _PICK, "F2": _MEDIAN}
_HEAD = (
    "import screamingface as sf\n"
    "\n"
    "candidate = (\n"
    "    sf.Fanout(['prov/alpha', 'prov/beta', 'prov/gamma'], "
)
_PYTHON: dict[str, str] = {
    "F1": _HEAD
    + "signals={'cons': sf.Consistency(n=3, temperature=1.0)}, name='pick')\n"
    + "    >> sf.ArgMax('cons')\n"
    + ")",
    "F2": _HEAD
    + "signals={'cons': sf.Consistency(n=2, temperature=0.7)}, name='median')\n"
    + "    >> sf.Median(over='last_number@1')\n"
    + ")",
}


def _compiled(recipe: sf.Recipe) -> _CompiledCandidate:
    return compile_candidate(recipe, operators=engine_operators())


def _url4(recipe: sf.Recipe) -> str:
    url4 = _compiled(recipe).url4
    assert url4 is not None
    return url4


def _root(url4: str) -> Expression:
    root = build(url4)
    assert isinstance(root, Expression)
    return root


def _linked(candidate: str) -> str:
    return render(
        expr(
            src(text(candidate), name="candidate", weight=0.0),
            src("/benchmarks/ifeval/revision-1/cases", name="rows", weight=0.0),
            intent=text("$rows"),
        )
    )


def _rebuilt(url4: str) -> Any:
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    return namespace["candidate"]


def _declared(recipe: sf.Recipe) -> dict[str, Any]:
    """The signals the block of ``recipe`` declares, read on its lowered value."""

    lowered = lower(recipe)
    assert isinstance(lowered, FusionNode)
    return dict(lowered.signals or {})


def _recompiled(url4: str) -> str | None:
    """Rebuild ``url4`` as Python, then compile it with the operator ids the url4 pins."""
    candidate, _ = _candidate_expression(build(url4))
    operators = _OperatorCatalog.from_pinned(_combine_operator_pairs(_calls(candidate)))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # duplicate-member and judge-writer warnings: not tested
        return compile_candidate(_rebuilt(url4), operators=operators).url4


def _error_text(action: Callable[[], object]) -> str:
    with pytest.raises(ValueError) as caught:
        action()
    return str(caught.value)


def _spec_of(url4: str) -> dict[str, Any]:
    return cast(dict[str, Any], decode_combine_spec(_calls(_root(url4))["synthesis_1"].raw_intent))


# ---- hand edits: each one starts from a fresh F1 (or F2) url4 ----


def _replace_source(url4: str, name: str, change: Callable[[Source], Source]) -> str:
    """Render ``url4`` with its one top-level source ``name`` changed by ``change``."""
    root = _root(url4)
    names = [node.name for node in root.sources if isinstance(node, Source)]
    assert names.count(name) == 1, names
    sources = tuple(
        change(node) if isinstance(node, Source) and node.name == name else node
        for node in root.sources
    )
    return render(replace(root, sources=sources))


def _replaced(old: str, new: str) -> Callable[[str], str]:
    def edit(url4: str) -> str:
        assert url4.count(old) == 1, old
        return url4.replace(old, new)

    return edit


def _drop_sample_3(panel: Source) -> Source:
    value = panel.value
    assert isinstance(value, Expression)
    last = value.sources[-1]
    assert isinstance(last, Source | Binding) and last.name == "sample_3"
    return replace(panel, value=replace(value, sources=value.sources[:-1]))


def _with_rider(edit: Callable[[dict[str, Any]], None]) -> Callable[[Source], Source]:
    """Change the rider's Fusion synthesizer node, then encode it as the compiler does."""

    def change(rider: Source) -> Source:
        assert isinstance(rider.value, Text)
        payload = json.loads(rider.value.value)
        edit(payload["recipe"]["synthesizer"])
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return replace(rider, value=Text(encoded))

    return change


def _with_spec(edit: Callable[[dict[str, Any]], None]) -> Callable[[Source], Source]:
    """Change the combine call's spec, then write it as canonical JSON again."""

    def change(combine: Source) -> Source:
        call = combine.value
        assert isinstance(call, RelExpr) and isinstance(call.intent, Text)
        spec = json.loads(call.intent.value)
        edit(spec)
        return replace(combine, value=replace(call, intent=Text(canonical_json(spec))))

    return change


def _role_of_model_4_is_model(synthesizer: dict[str, Any]) -> None:
    node = synthesizer["samples"][0]["sources"][0]
    assert node["binding"] == "model_4"
    node["role"] = "model"


def _spec_n_is_4(spec: dict[str, Any]) -> None:
    assert spec["signals"]["cons"]["n"] == 3
    spec["signals"]["cons"]["n"] = 4


def _match_has_flags(spec: dict[str, Any]) -> None:
    spec["signals"]["cons"]["match"]["flags"] = 1


# case -> (edit of the F1 url4, the exact C5 text). PRD CB-E1..CB-E6.
_HAND_EDITS: dict[str, tuple[Callable[[str], str], str]] = {
    "E1_binding_removed_from_model_4": (_replaced("?binding=model_4&", "?"), _TOPOLOGY),
    "E2_seed_of_model_5_changed_to_1": (_replaced("&seed=10968804&", "&seed=1&"), _METADATA),
    "E3_sample_3_removed_from_panel_1": (
        lambda url4: _replace_source(url4, "panel_1", _drop_sample_3),
        _TOPOLOGY,
    ),
    "E4_role_of_model_4_changed_to_model": (
        lambda url4: _replace_source(url4, "_sf_recipe", _with_rider(_role_of_model_4_is_model)),
        _REDUCER,
    ),
    "E5_spec_n_changed_from_3_to_4": (
        lambda url4: _replace_source(url4, "synthesis_1", _with_spec(_spec_n_is_4)),
        _METADATA,
    ),
    "E6_match_with_an_extra_key": (
        lambda url4: _replace_source(url4, "synthesis_1", _with_spec(_match_has_flags)),
        _CANNOT_REBUILD,
    ),
}


def _samples_empty(node: dict[str, Any]) -> None:
    node["samples"] = []


def _samples_not_a_list(node: dict[str, Any]) -> None:
    node["samples"] = {}


def _entry_with_extra_key(node: dict[str, Any]) -> None:
    node["samples"][0]["extra"] = 1


def _members_swapped(node: dict[str, Any]) -> None:
    node["samples"][0]["member"] = "member_2"
    node["samples"][1]["member"] = "member_1"


def _members_start_at_2(node: dict[str, Any]) -> None:
    for index, entry in enumerate(node["samples"], start=2):
        entry["member"] = f"member_{index}"


def _sources_empty(node: dict[str, Any]) -> None:
    for entry in node["samples"]:
        entry["sources"] = []


def _sources_of_two_lengths(node: dict[str, Any]) -> None:
    node["samples"][2]["sources"].pop()


def _sample_node_with_extra_key(node: dict[str, Any]) -> None:
    node["samples"][0]["sources"][0]["extra"] = 1


def _sample_node_kind_reducer(node: dict[str, Any]) -> None:
    node["samples"][0]["sources"][0]["kind"] = "reducer"


def _sample_node_named_text(node: dict[str, Any]) -> None:
    node["samples"][0]["sources"][0]["named"] = "no"


def _sample_node_name_blank(node: dict[str, Any]) -> None:
    node["samples"][0]["sources"][0]["name"] = " "


def _sample_binding_judge(node: dict[str, Any]) -> None:
    node["samples"][0]["sources"][0]["binding"] = "judge_9"


def _sample_binding_twice(node: dict[str, Any]) -> None:
    node["samples"][1]["sources"][0]["binding"] = "model_4"


_BAD_SAMPLES: dict[str, Callable[[dict[str, Any]], None]] = {
    "samples_empty": _samples_empty,
    "samples_not_a_list": _samples_not_a_list,
    "entry_with_extra_key": _entry_with_extra_key,
    "members_swapped": _members_swapped,
    "members_start_at_2": _members_start_at_2,
    "sources_empty": _sources_empty,
    "sources_of_two_lengths": _sources_of_two_lengths,
    "sample_node_with_extra_key": _sample_node_with_extra_key,
    "sample_node_kind_reducer": _sample_node_kind_reducer,
    "sample_node_named_text": _sample_node_named_text,
    "sample_node_name_blank": _sample_node_name_blank,
    "sample_binding_judge": _sample_binding_judge,
    "sample_binding_twice": _sample_binding_twice,
}


class _ForbiddenTransport:
    called = False

    def run(self, candidate: Candidate, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("an unknown match operator must fail before execution")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


# --- CB#1: a url4 without consistency rebuilds as before (CHAR, list L5) ---


@requires_engine_app
@pytest.mark.parametrize("name", _L5)
def test_url4_without_consistency_rebuilds_as_before(name: str) -> None:
    url4 = read_contract(name)
    assert _recompiled(url4) == url4


# --- CB#2: to_python gives back sf.Consistency and leaves out the sample calls ---


@pytest.mark.parametrize("name", ["F1", "F2"])
def test_to_python_rebuilds_sf_consistency_and_drops_the_sample_calls(name: str) -> None:
    recipe = _RECIPES[name]()
    url4 = _url4(recipe)
    assert url4 == BUILDERS[_FIXTURES[name]]()

    source = sf.Url4(url4).to_python()

    assert source == _PYTHON[name]
    for word in ("seed", "binding", "params="):
        assert word not in source, word
    rebuilt = _rebuilt(url4)
    assert isinstance(rebuilt, sf.Pipeline)
    fanout = rebuilt.steps[0]
    assert isinstance(fanout, sf.Fanout)
    assert dict(fanout.signals or {}) == _declared(recipe)
    assert _url4(rebuilt) == url4


# --- CB#3: the replay shows the compile's operations, in order ---


def test_replay_recovers_the_compiled_operations() -> None:
    compiled = _compiled(_f1())
    assert compiled.url4 is not None

    replayed = _candidate_from_url4(_linked(compiled.url4)).operations

    assert replayed == compiled.operations
    assert [operation.kind for operation in replayed] == ["model"] * 3 + ["sample"] * 9 + [
        "combine"
    ]
    assert [operation.label for operation in replayed] == [
        "alpha answer",
        "beta answer",
        "gamma answer",
        *["alpha sample"] * 3,
        *["beta sample"] * 3,
        *["gamma sample"] * 3,
        "pick combine",
    ]
    assert [operation.depends_on for operation in replayed[:12]] == [()] * 12
    assert replayed[12].depends_on == tuple(f"op_model_{index}" for index in range(1, 13))


# --- CB#4: a judge signal and the samples keep both dependency orders (erd §7) ---


def test_a_judge_signal_and_samples_keep_both_dependency_orders() -> None:
    compiled = _compiled(_f3())
    url4 = compiled.url4
    assert url4 is not None

    bindings = _topology_bindings(_topology_from_expression(_root(url4)))
    combine = bindings["synthesis_1"]

    assert combine.context_dependencies == (
        "model_1",
        "model_2",
        "model_3",
        "model_4",
        "model_5",
        "model_6",
        "judge_1",
    )
    assert combine.operation_dependencies == (
        "model_1",
        "model_2",
        "model_3",
        "judge_1",
        "model_4",
        "model_5",
        "model_6",
    )
    assert _calls(_root(url4))["synthesis_1"].dependencies == combine.context_dependencies
    assert [bindings[f"model_{index}"].node.role for index in (4, 5, 6)] == ["sample"] * 3
    assert _url4(_rebuilt(url4)) == url4
    assert _candidate_from_url4(_linked(url4)).operations == compiled.operations


def test_samples_in_a_later_stage_read_the_stage_input() -> None:
    compiled = _compiled(sf.Pipeline([sf.Model("prov/delta"), _f1()]))
    url4 = compiled.url4
    assert url4 is not None

    bindings = _topology_bindings(_topology_from_expression(_root(url4)))
    samples = [name for name, binding in bindings.items() if binding.node.role == "sample"]

    assert len(samples) == 9
    for name in samples:
        assert bindings[name].context_dependencies == ("model_1",), name
        assert bindings[name].operation_dependencies == ("model_1",), name
    assert _url4(_rebuilt(url4)) == url4
    assert _candidate_from_url4(_linked(url4)).operations == compiled.operations


# --- CB#5: a hand-edited consistency url4 fails with one exact C5 text ---


@pytest.mark.parametrize("case", sorted(_HAND_EDITS))
def test_hand_edited_consistency_url4_cannot_rebuild(case: str) -> None:
    edit, expected = _HAND_EDITS[case]
    url4 = BUILDERS[_PICK]()
    sf.Url4(url4).to_python()  # control: the untouched F1 url4 rebuilds

    tampered = edit(url4)

    assert tampered != url4
    assert _error_text(lambda: sf.Url4(tampered).to_python()) == expected
    assert _error_text(lambda: _candidate_from_url4(_linked(tampered))) == expected


@pytest.mark.parametrize("case", sorted(_BAD_SAMPLES))
def test_a_malformed_samples_topology_is_invalid_reducer_metadata(case: str) -> None:
    url4 = BUILDERS[_PICK]()
    sf.Url4(url4).to_python()  # control: the untouched F1 url4 rebuilds

    tampered = _replace_source(url4, "_sf_recipe", _with_rider(_BAD_SAMPLES[case]))

    assert tampered != url4
    assert _error_text(lambda: sf.Url4(tampered).to_python()) == _REDUCER


# --- CB#6: the replay lists no sample as a fixed-seed call (P18) ---


def _fixed_seed(recorded: list[warnings.WarningMessage]) -> list[warnings.WarningMessage]:
    return [item for item in recorded if issubclass(item.category, sf.FixedSeedSittingWarning)]


def test_replay_lists_no_sample_as_a_fixed_seed_call() -> None:
    replay = _replayed_url4(_linked(BUILDERS[_PICK]()))

    assert replay.seeded == ()
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        stamped = _stamped_sitting(replay, 5)
    assert _fixed_seed(recorded) == []
    assert stamped.answer_seed == 5

    # control: a member that sets its own seed is still a fixed-seed call
    seeded = sf.Fanout(
        [sf.Model("prov/alpha", params={"seed": 7}), "prov/beta", "prov/gamma"],
        signals={"cons": sf.Consistency(n=3)},
        name="pick",
    ) >> sf.ArgMax("cons")
    replay = _replayed_url4(_linked(_url4(seeded)))
    assert replay.seeded == ("op_model_1 (alpha answer)",)
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        _stamped_sitting(replay, 5)
    assert len(_fixed_seed(recorded)) == 1


# --- CB#7: the match operators are pinned operators ---


def test_the_match_operators_are_pinned_operators() -> None:
    spec = _spec_of(BUILDERS[_PICK]())

    assert spec_operator_pairs(spec) == (
        ("reduce", "by_signal@1"),
        ("select", "best_holder@1"),
        ("extract", "last_line@1"),
        ("normalize", "text@1"),
    )
    # F2: the median's match is its own steps, so each pair is listed once
    assert spec_operator_pairs(_spec_of(BUILDERS[_MEDIAN]())) == (
        ("extract", "last_number@1"),
        ("normalize", "numeric@1"),
        ("reduce", "median@1"),
        ("select", "nearest@1"),
    )
    entry = spec["signals"]["cons"]
    no_normalize = {
        **spec,
        "signals": {"cons": {**entry, "match": {**entry["match"], "normalize": None}}},
    }
    assert spec_operator_pairs(no_normalize) == (
        ("reduce", "by_signal@1"),
        ("select", "best_holder@1"),
        ("extract", "last_line@1"),
    )
    plain = {key: value for key, value in spec.items() if key != "signals"}
    assert spec_operator_pairs(plain) == (("reduce", "by_signal@1"), ("select", "best_holder@1"))

    # a replay pins them against the Engine before it spends
    catalog = _OperatorCatalog(
        entries=tuple(item for item in engine_operators().entries if item.id != "text@1")
    )
    transport = _ForbiddenTransport()
    with pytest.raises(
        ValueError,
        match=r"^normalize operator 'text@1' is not in this SF Engine's operator catalog; ",
    ):
        evaluate_url4_sync(
            transport, _linked(BUILDERS[_PICK]()), None, False, load_operators=lambda: catalog
        )
    assert transport.called is False


# --- CB#8: _from_spec rebuilds the _entry and refuses every other entry (CN-I6) ---


def test_consistency_from_spec_refuses_foreign_entries() -> None:
    source = sf.Consistency(n=3)
    other = sf.Consistency(n=2, temperature=0.7)
    entry = source._entry(_MATCH)

    assert sf.Consistency._from_spec(entry) == source
    assert sf.Consistency._from_spec(other._entry(_MATCH)) == other
    assert declared_from_spec({"cons": entry}) == {"cons": source}

    refused: list[dict[str, Any]] = [
        {key: value for key, value in entry.items() if key != "n"},
        {**entry, "n": True},
        {**entry, "n": 3.0},
        {**entry, "temperature": "1"},
        {**entry, "temperature": True},
        {**entry, "temperature": None},
        {**entry, "match": []},
        {**entry, "match": {"extract": _MATCH["extract"]}},
        {**entry, "match": {**_MATCH, "flags": 1}},
        {**entry, "seed": 1},
        {**entry, "source": "logprob"},
        source._spec(),
    ]
    for bad in refused:
        assert _error_text(lambda bad=bad: sf.Consistency._from_spec(bad)) == _CANNOT_REBUILD, bad
        assert _error_text(lambda bad=bad: declared_from_spec({"cons": bad})) == _CANNOT_REBUILD, (
            bad
        )
    # out of range: the constructor refuses, and the rebuild shows the C5 text
    for bad in (
        {**entry, "n": 0},
        {**entry, "n": 33},
        {**entry, "n": 10**30},
        {**entry, "temperature": -0.5},
        {**entry, "temperature": float("inf")},
    ):
        assert _error_text(lambda bad=bad: declared_from_spec({"cons": bad})) == _CANNOT_REBUILD, (
            bad
        )


# --- CB#9: a samples key without a declaration does not rebuild (CB-D5) ---


def _drop_signals(spec: dict[str, Any]) -> None:
    assert spec["signals"]["cons"]["source"] == "consistency"
    del spec["signals"]


def test_a_samples_key_without_a_declaration_does_not_rebuild() -> None:
    url4 = BUILDERS[_MEDIAN]()

    tampered = _replace_source(url4, "synthesis_1", _with_spec(_drop_signals))

    assert '"samples":[' in tampered  # the rider still lists the sample calls
    assert _error_text(lambda: sf.Url4(tampered).to_python()) == _METADATA
    assert _error_text(lambda: _candidate_from_url4(_linked(tampered))) == _METADATA


# --- review fix (MAJOR): a sample slot is policy; a url4 without its policy markers is refused ---


def _without_policy_markers(url4: str) -> str:
    """Drop the ``;optional`` and ``;quorum=0`` markers of a consistency url4 (the review's probe).

    WHY: the recompile trigger for the url4 reads these markers only. A url4 without them must
    still take the byte-for-byte recompile: a sample slot is optional, and a quorum is policy.
    """
    assert ";optional" in url4 and ";quorum=0" in url4
    return url4.replace(";optional", "").replace(";quorum=0", "")


def test_a_consistency_url4_without_its_policy_markers_does_not_rebuild() -> None:
    url4 = BUILDERS[_PICK]()

    tampered = _without_policy_markers(url4)

    assert tampered != url4
    assert _error_text(lambda: sf.Url4(tampered).to_python()) == _METADATA
    assert _error_text(lambda: _candidate_from_url4(_linked(tampered))) == _METADATA


def test_a_samples_key_without_a_declaration_and_policy_markers_does_not_rebuild() -> None:
    url4 = BUILDERS[_MEDIAN]()
    dropped = _replace_source(url4, "synthesis_1", _with_spec(_drop_signals))

    tampered = _without_policy_markers(dropped)

    assert '"samples":[' in tampered  # the rider still lists the sample calls
    assert _error_text(lambda: sf.Url4(tampered).to_python()) == _METADATA
    assert _error_text(lambda: _candidate_from_url4(_linked(tampered))) == _METADATA


# --- review fix (MAJOR): a hand-added consistency source on a plain url4 is refused ---


def test_a_consistency_source_added_to_a_plain_url4_does_not_rebuild() -> None:
    """WHY: a declared source adds sample calls; a url4 without them must not rebuild or replay."""
    url4 = _url4(sf.Fanout(_MEMBERS, name="median") >> sf.Median())
    signals = _spec_of(BUILDERS[_MEDIAN]())["signals"]

    def add_signals(spec: dict[str, Any]) -> None:
        assert "signals" not in spec
        spec["signals"] = signals

    tampered = _replace_source(url4, "synthesis_1", _with_spec(add_signals))

    assert tampered != url4
    assert _error_text(lambda: sf.Url4(tampered).to_python()) == _METADATA
    assert _error_text(lambda: _candidate_from_url4(_linked(tampered))) == _METADATA
