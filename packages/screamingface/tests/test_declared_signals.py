"""Declared signal sources on a Fusion: names, read checks, the spec, the evidence and the rebuild.

FEATURE: a reducer Fusion declares named signal sources with ``signals=`` and reads them with
``sf.signal(name)`` (E4b part 3, unit 2; DS#1-16 of the declared-signals PRD).
STORY: as a benchmark author, I write signals={"conf": sf.Verbalized(r"Confidence: ([0-9]+)")},
weight a vote with sf.signal("conf"), and a typo in the read name fails before any member call.
INVARIANT defended: a Fusion without a declaration compiles to the same bytes; an undeclared read
fails in the Fusion constructor; a declared name is a valid signal name and never an E4a key; a
declaration needs a reducer synthesizer; the rebuild from url4 gives the declaration back.
"""

from __future__ import annotations

from typing import Any

import pytest
from _combine_contract import engine_operators, read_contract, requires_engine_app
from _combine_recipes import RECIPES, compile_recipe
from _nodes import VoteNode
from _reducer_fixtures import evidence_wire
from _vote_run_fixtures import spec_of

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._evaluation.combine_spec import combine_spec_text, decode_combine_spec
from screamingface.combine_evidence import CombineSignal
from screamingface.errors import ExecutionError
from screamingface.signal_sources import SignalSource

MEMBERS = ["provider/a", "provider/b", "provider/c"]
CONF_PATTERN = "Confidence: ([0-9]+)"
_E4A_KEYS = "cost_usd, latency_ms, tokens_in, tokens_out, score:judge and field:<path>"
_SPEC_TEXT = (
    '{"extract":{"args":{},"op":"last_line@1"},"members":["member_1","member_2","member_3"],'
    '"normalize":{"args":{},"op":"text@1"},"reduce":{"args":{},"op":"weighted_mode@1"},'
    '"reducer":"vote","schema":"screamingface.combine-spec.v1",'
    '"select":{"args":{},"op":"max_weight_holder@1"},'
    '"signals":{"conf":{"pattern":"Confidence: ([0-9]+)","source":"verbalized"}},'
    '"weights":{"signal":"conf"}}'
)


def _compiled(fusion: sf.Recipe) -> str:
    return compile_candidate(fusion, operators=engine_operators()).url4


def _fanout(chain: sf.Recipe) -> sf.Fanout:
    """The ``Fanout`` that opens ``chain``: it holds the block's declared signals."""

    assert isinstance(chain, sf.Pipeline)
    fanout = chain.steps[0]
    assert isinstance(fanout, sf.Fanout)
    return fanout


class _FakeEntropy(SignalSource):
    """A test-local stand-in for sf.Entropy (unit 4): only the one-entropy rule is tested (E4)."""

    source = "entropy"

    def _spec(self) -> dict[str, object]:
        return {"source": "entropy", "top_logprobs": 5}

    @classmethod
    def _from_spec(cls, entry: Any) -> _FakeEntropy:
        return cls()

    def __repr__(self) -> str:
        return "_FakeEntropy()"


# --- DS#1: a Fusion without signals= compiles the same bytes ---------------------------------


@requires_engine_app
def test_fusion_without_signals_compiles_the_same_bytes() -> None:
    # WHY the committed bytes: they are the base 0f4b9e292 output, so no existing url4 changes.
    for name in sorted(RECIPES):
        text = compile_recipe(name)
        assert text == read_contract(name)
        # WHY the decoded spec, not the text: the judge topology of url4 has its own "signals" list.
        assert "signals" not in spec_of(text)
    code = sf.Url4(read_contract("signal_vote_candidate.url4")).to_python()
    assert "signals=" not in code


# --- DS#2: the reserved logprob name keeps its E4b refusal -----------------------------------


def test_signal_logprob_mean_is_refused_with_the_e4b_message() -> None:
    with pytest.raises(ValueError, match="E4b") as raised:
        sf.signal("logprob_mean")
    assert "cost_usd" in str(raised.value)


# --- DS#4: a rule that reads an undeclared name fails in the constructor ---------------------


def test_fusion_refuses_a_rule_that_reads_an_undeclared_name() -> None:
    # Positive first: the declared read builds, so the refusals below are about the read check.
    declared = {"conf": sf.Verbalized(CONF_PATTERN)}
    fusion = sf.Fanout(MEMBERS, signals=declared) >> sf.Vote(weights=sf.signal("conf"))
    assert list(_fanout(fusion).signals or {}) == ["conf"]

    with pytest.raises(ValueError) as undeclared:
        _ = sf.Fanout(MEMBERS, signals=declared) >> sf.Vote(weights=sf.signal("lp"))
    assert str(undeclared.value) == (
        "the synthesizer reads sf.signal('lp'), which this Fusion does not declare (declared: conf)"
    )
    with pytest.raises(ValueError, match=r"sf\.signal\('lp'\).*declared: none"):
        _ = sf.Fanout(MEMBERS) >> sf.ArgMax("lp")
    with pytest.raises(ValueError, match=r"sf\.signal\('lp'\).*declared: none"):
        _ = sf.Fanout(MEMBERS) >> sf.Filter(where=sf.signal("lp") > 0.5) >> sf.Vote()


# --- DS#5: names are checked with exact refusal texts ----------------------------------------


def test_fusion_refuses_invalid_and_reserved_names() -> None:
    # Positive first: a 32-character name is valid, so the refusals below are about the rules.
    verbalized = sf.Verbalized(CONF_PATTERN)
    assert _fanout(sf.Fanout(MEMBERS, signals={"a" * 32: verbalized}) >> sf.Vote()).signals

    exact = {
        "cost_usd": (
            "'cost_usd' is an E4a signal key; read it with sf.signal('cost_usd') and do not "
            "declare it"
        ),
        "logprob_x": (
            "'logprob_x' is reserved: a declared name must not start with logprob, entropy, "
            "verbalized or consistency"
        ),
        "Cost": "'Cost' is not a declared name: a declared name matches [a-z][a-z0-9_]{0,31}",
    }
    for name, message in exact.items():
        with pytest.raises(ValueError) as refused:
            _ = sf.Fanout(MEMBERS, signals={name: verbalized}) >> sf.Vote()
        assert str(refused.value) == message

    for name in ("", "a" * 33, "1a"):
        with pytest.raises(ValueError, match="not a declared name"):
            _ = sf.Fanout(MEMBERS, signals={name: verbalized}) >> sf.Vote()
    # WHY "E4a signal key": "field:x" is a valid E4a field key, so the refusal names that class.
    with pytest.raises(ValueError, match="E4a signal key"):
        _ = sf.Fanout(MEMBERS, signals={"field:x": verbalized}) >> sf.Vote()
    with pytest.raises(ValueError, match="E4a signal key"):
        _ = sf.Fanout(MEMBERS, signals={"score:judge": verbalized}) >> sf.Vote()

    with pytest.raises(TypeError):
        sf.Fanout(MEMBERS, signals={1: verbalized}) >> sf.Vote()  # type: ignore[dict-item]
    with pytest.raises(TypeError):
        sf.Fanout(MEMBERS, signals={"conf": "Confidence"}) >> sf.Vote()  # type: ignore[dict-item]
    with pytest.raises(TypeError):
        sf.Fanout(MEMBERS, signals=[("conf", verbalized)]) >> sf.Vote()  # type: ignore[arg-type]


# --- DS#6: the name syntax is accepted by sf.signal; the hint is kept --------------------------


def test_signal_accepts_a_declared_name_syntax() -> None:
    assert sf.signal("cost").key == "cost"
    assert sf.signal("conf").key == "conf"
    assert sf.signal("a" * 32).key == "a" * 32
    assert repr(sf.signal("conf")) == "signal('conf')"

    with pytest.raises(ValueError) as reserved:
        sf.signal("logprob_mean")
    assert str(reserved.value) == (
        "'logprob_mean' is reserved: names that start with logprob, entropy, verbalized or "
        "consistency belong to E4b declared sources; declare a name such as "
        "signals={'lp': sf.Logprob('mean')} and read sf.signal('lp'); "
        f"E4a signal keys are {_E4A_KEYS}"
    )
    with pytest.raises(ValueError) as shape:
        sf.signal("Cost_usd")
    assert str(shape.value) == (
        "'Cost_usd' is not a signal key or a declared name; E4a signal keys are "
        f"{_E4A_KEYS}; an E4b declared name matches [a-z][a-z0-9_]{{0,31}}"
    )
    with pytest.raises(ValueError, match="is not a signal key or a declared name"):
        sf.signal("a" * 33)

    # DS-D2: "cost" is a valid name now, so the read check hints the E4a key it may mean.
    with pytest.raises(ValueError, match="did you mean cost_usd"):
        _ = sf.Fanout(MEMBERS) >> sf.Vote(weights=sf.signal("cost"))


# --- DS#7: at most eight names and at most one entropy ---------------------------------------


def test_fusion_refuses_more_than_eight_names_and_two_entropies() -> None:
    verbalized = sf.Verbalized(CONF_PATTERN)
    eight = {f"n{index}": verbalized for index in range(1, 9)}
    fusion = sf.Fanout(MEMBERS, signals=eight) >> sf.Vote()
    assert len(_fanout(fusion).signals or {}) == 8

    nine = {f"n{index}": verbalized for index in range(1, 10)}
    with pytest.raises(ValueError) as too_many:
        _ = sf.Fanout(MEMBERS, signals=nine) >> sf.Vote()
    assert str(too_many.value) == "a Fusion declares at most 8 signals, not 9"

    with pytest.raises(ValueError, match="at most one sf.Entropy"):
        _ = sf.Fanout(MEMBERS, signals={"e1": _FakeEntropy(), "e2": _FakeEntropy()}) >> sf.Vote()
    assert _fanout(sf.Fanout(MEMBERS, signals={"e1": _FakeEntropy()}) >> sf.Vote()).signals


# --- DS#8: a declaration needs a reducer synthesizer -----------------------------------------


def test_fusion_refuses_signals_with_a_model_synthesizer() -> None:
    declared = {"conf": sf.Verbalized(CONF_PATTERN)}
    # Positive first: a reducer synthesizer with the same declaration builds.
    assert sf.Fanout(MEMBERS, signals=declared) >> sf.Vote(weights=sf.signal("conf"))

    for synthesizer in (sf.Model("provider/s"), "provider/s"):
        with pytest.raises(
            ValueError, match=r"sf\.Fanout signals= needs a reducer: sf\.Synthesize reads no signal"
        ):
            _ = sf.Fanout(MEMBERS, signals=declared) >> sf.Synthesize(synthesizer)

    # WHY the empty map: signals={} is no declaration, so the Fusion keeps no signals.
    empty = sf.Fanout(MEMBERS, signals={}) >> sf.Synthesize(sf.Model("provider/s"))
    assert _fanout(empty).signals is None


# --- DS#9: the spec carries the signals map ---------------------------------------------------


def test_fusion_compiles_the_signals_map_into_the_spec() -> None:
    text = combine_spec_text(
        VoteNode(weights=sf.signal("conf")),
        member_count=3,
        operators=engine_operators(),
        signals={"conf": sf.Verbalized(CONF_PATTERN)},
    )
    assert text == _SPEC_TEXT

    fusion = sf.Fanout(MEMBERS, signals={"conf": sf.Verbalized(CONF_PATTERN)}) >> sf.Vote(
        weights=sf.signal("conf")
    )
    assert spec_of(_compiled(fusion)) == decode_combine_spec(_SPEC_TEXT)

    # WHY: signals={} is no declaration, so it compiles to the same url4 as no signals=.
    empty = sf.Fanout(MEMBERS, signals={}) >> sf.Vote(weights=sf.signal("cost_usd"))
    plain = sf.Fanout(MEMBERS) >> sf.Vote(weights=sf.signal("cost_usd"))
    assert _compiled(empty) == _compiled(plain)


# --- DS#14: repr and the url4 rebuild ---------------------------------------------------------


def test_fusion_signals_round_trip_through_url4_rebuild_and_repr() -> None:
    fusion = sf.Fanout(MEMBERS, signals={"conf": sf.Verbalized(CONF_PATTERN)}) >> sf.Vote(
        weights=sf.signal("conf")
    )
    assert repr(fusion) == (
        "Fanout(['provider/a', 'provider/b', 'provider/c'], "
        "signals={'conf': Verbalized('Confidence: ([0-9]+)')}) >> Vote(weights='conf')"
    )
    url4 = _compiled(fusion)
    code = sf.Url4(url4).to_python()
    lines = code.splitlines()
    signals_line = "    signals={'conf': sf.Verbalized('Confidence: ([0-9]+)')},"
    assert signals_line in lines
    synthesizer_lines = [
        index for index, line in enumerate(lines) if line.startswith("    synthesizer=")
    ]
    assert synthesizer_lines and lines.index(signals_line) < synthesizer_lines[0]

    namespace: dict[str, Any] = {}
    exec(code, namespace)  # noqa: S102 - our own generated code
    rebuilt = namespace["candidate"]
    assert rebuilt.signals == {"conf": sf.Verbalized(CONF_PATTERN)}
    # WHY: the url4 rebuild keeps the pinned operator ids ('@1'), erratum E9.
    assert repr(rebuilt) == (
        "Fusion(['a', 'b', 'c'], signals={'conf': Verbalized('Confidence: ([0-9]+)')}, "
        "synthesizer=Vote(extract='last_line@1', normalize='text@1', weights=signal('conf')))"
    )
    assert _compiled(rebuilt) == url4


# --- DS#15: the SDK decoder reads declared and rejects unknown keys --------------------------


def test_sdk_decoder_reads_declared_and_rejects_unknown_keys() -> None:
    declared = {"conf": {"source": "verbalized", "pattern": CONF_PATTERN}}
    wire = evidence_wire()
    for member in wire["members"]:
        member["signals"] = {"conf": 90.0}
    wire["signal"] = {"key": "conf", "order": None}
    wire["declared"] = declared

    evidence = decode_combine_evidence(wire, "ev")
    assert evidence is not None and evidence.declared == declared  # WHY: pyright narrows it
    assert evidence.signal is not None and evidence.signal.key == "conf"
    dumped = evidence.to_dict()
    assert dumped["declared"] == declared
    assert list(dumped).index("declared") == list(dumped).index("signal") + 1

    without = {key: value for key, value in wire.items() if key != "declared"}
    with pytest.raises(ExecutionError, match="signal key must be"):
        decode_combine_evidence(without, "ev")
    with pytest.raises(ExecutionError):
        decode_combine_evidence({**wire, "declared_by": {}}, "ev")
    with pytest.raises(ExecutionError):
        decode_combine_evidence({**wire, "declared": {"Conf": declared["conf"]}}, "ev")
    with pytest.raises(ExecutionError):
        decode_combine_evidence({**wire, "declared": {"conf": {"pattern": "x"}}}, "ev")

    plain = decode_combine_evidence(evidence_wire(), "ev")
    assert plain is not None and plain.declared is None  # WHY: pyright narrows it
    assert "declared" not in plain.to_dict()

    with pytest.raises(ValueError, match="signal key"):
        CombineSignal("cost", None)


# --- DS#16: the rebuild keeps the authored params of a declared Fusion -----------------------


def test_rebuild_keeps_authored_params_of_a_declared_fusion() -> None:
    # WHY only "authored params stay": the drop of injected params is LP#14 and EN#13 (unit 4);
    # erratum E3 in the ledger.
    fusion = sf.Fanout(
        [sf.Model("provider/a", params={"logprobs": True, "top_logprobs": 3}), "provider/b"],
        signals={"conf": sf.Verbalized(CONF_PATTERN)},
    ) >> sf.Vote(weights=sf.signal("conf"))
    url4 = _compiled(fusion)
    namespace: dict[str, Any] = {}
    exec(sf.Url4(url4).to_python(), namespace)  # noqa: S102 - our own generated code
    rebuilt = namespace["candidate"]
    assert rebuilt.members[0].params == {"logprobs": True, "top_logprobs": 3}
    assert _compiled(rebuilt) == url4
