"""``sf.Gate``: keep the vote's answer only when a condition holds (E4b surface unit 4, §7).

FEATURE: ``Gate(*, when, then, otherwise="abstain", abstain_if=None)`` closes a block. ``when`` is
a reference (``sf.agreement()``, ``sf.signal(x).chosen()``, ``sf.signal(x).mean()``) compared with
a finite number; it is the condition that KEEPS the vote's answer. ``then`` is a ``sf.Vote``.
``otherwise`` is ``"abstain"``, a ``sf.JudgePick`` or a ``sf.Synthesize`` with one model.
``abstain_if=ref.between(lo, hi)`` abstains inside a closed band of the same number.
INVARIANT: a gate lowers to today's ``sf.Vote(gate=sf.Gate(observe, cmp, threshold, ...))`` and
compiles to its bytes (GA-P).
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping

import pytest
from _combine_flow_fixtures import flow_operators
from _nodes import FusionNode, GateNode, JudgeNode, RankNode, VoteNode, frozen_url4, fusion_node

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._surface.lowering import lower
from screamingface.signal_sources import SignalSource

_PANEL = ["prov/alpha", "prov/beta", "prov/gamma"]
_CONF = {"conf": sf.Verbalized(r"Confidence: ([0-9]+)")}
_SEVERITY = {
    "risk": sf.Sum({"sev_a": 0.5, "sev_b": 0.3}),
    "sev_a": sf.Verbalized(r"A: ([0-9]+)"),
    "sev_b": sf.Verbalized(r"B: ([0-9]+)"),
}
_PICK = "Pick the best answer."
_SHARE = r"^sf\.agreement\(\) is a share: compare it with numbers between 0 and 1$"


def _url4(recipe: sf.Recipe) -> str:
    return compile_candidate(recipe, operators=flow_operators()).url4


def _gated(gate: sf.Gate, *, signals: Mapping[str, SignalSource] | None = None) -> sf.Recipe:
    return sf.Fanout(_PANEL, name="vote", signals=signals) >> gate


# ---------------------------------------------------------------- GA-P (README part 5 and 6)

# The README recipes this copies: "Gate the vote" g1-g4 (S/README.md, about lines 1091-1128) and
# the band gate s2 (about lines 1236-1242); the last two cases add a writer fallback with a band
# and weights, and a judge-weighted gated vote.

_RECIPES: dict[str, tuple[Callable[[], sf.Recipe], Callable[[], sf.Recipe]]] = {
    "g1-agreement-abstain": (
        lambda: _gated(sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote())),
        lambda: fusion_node(
            _PANEL, name="vote", reducer=VoteNode(gate=GateNode("agreement", ">=", 0.7))
        ),
    ),
    "g2-agreement-judge": (
        lambda: _gated(
            sf.Gate(
                when=sf.agreement() >= 0.7,
                then=sf.Vote(),
                otherwise=sf.JudgePick("prov/judge", rubric=_PICK),
            )
        ),
        lambda: fusion_node(
            _PANEL,
            name="vote",
            reducer=VoteNode(
                gate=GateNode(
                    "agreement",
                    ">=",
                    0.7,
                    otherwise=JudgeNode("prov/judge", returns="label", rubric=_PICK),
                )
            ),
        ),
    ),
    "g3-agreement-writer": (
        lambda: _gated(
            sf.Gate(
                when=sf.agreement() >= 0.7,
                then=sf.Vote(),
                otherwise=sf.Synthesize("prov/writer", prompt="Write one answer."),
            )
        ),
        lambda: fusion_node(
            _PANEL,
            name="vote",
            reducer=VoteNode(
                gate=GateNode(
                    "agreement",
                    ">=",
                    0.7,
                    otherwise=sf.Model("prov/writer", prompt="Write one answer."),
                )
            ),
        ),
    ),
    "g4-confidence-gate": (
        lambda: _gated(
            sf.Gate(when=sf.signal("conf").chosen() >= 80, then=sf.Vote()), signals=_CONF
        ),
        lambda: fusion_node(
            _PANEL,
            name="vote",
            signals=_CONF,
            reducer=VoteNode(gate=GateNode("chosen:conf", ">=", 80)),
        ),
    ),
    "s2-band-gate": (
        lambda: _gated(
            sf.Gate(
                when=sf.signal("risk").mean() <= 3.0,
                then=sf.Vote(),
                abstain_if=sf.signal("risk").mean().between(2.5, 3.5),
            ),
            signals=_SEVERITY,
        ),
        lambda: fusion_node(
            _PANEL,
            name="vote",
            signals=_SEVERITY,
            reducer=VoteNode(gate=GateNode("mean:risk", "<=", 3.0, abstain_band=(2.5, 3.5))),
        ),
    ),
    "band-writer-weighted": (
        lambda: _gated(
            sf.Gate(
                when=sf.signal("risk").mean() < 4,
                then=sf.Vote(over="last_number", normalize="numeric", weights=(1, 2, 1)),
                otherwise=sf.Synthesize(sf.Model("prov/big", params={"temperature": 0})),
                abstain_if=sf.signal("risk").mean().between(3, 3.5),
            ),
            signals=_SEVERITY,
        ),
        lambda: fusion_node(
            _PANEL,
            name="vote",
            signals=_SEVERITY,
            reducer=VoteNode(
                extract="last_number",
                normalize="numeric",
                weights=(1, 2, 1),
                gate=GateNode(
                    "mean:risk",
                    "<",
                    4,
                    otherwise=sf.Model("prov/big", params={"temperature": 0}),
                    abstain_band=(3, 3.5),
                ),
            ),
        ),
    ),
    "judge-weighted-gate": (
        lambda: (
            sf.Fanout(_PANEL, name="vote")
            >> sf.Judge("prov/scorer", rubric="Score each answer.")
            >> sf.Gate(
                when=sf.agreement() > 0.5,
                then=sf.Vote(weights="score:judge"),
                otherwise=sf.JudgePick("prov/judge", rubric=_PICK),
            )
        ),
        lambda: fusion_node(
            _PANEL,
            name="vote",
            reducer=VoteNode(
                weights=sf.signal("score:judge"),
                judge=JudgeNode("prov/scorer", returns="scores", rubric="Score each answer."),
                gate=GateNode(
                    "agreement",
                    ">",
                    0.5,
                    otherwise=JudgeNode("prov/judge", returns="label", rubric=_PICK),
                ),
            ),
        ),
    ),
}


@pytest.mark.parametrize("case", sorted(_RECIPES))
def test_gap_a_gate_recipe_compiles_to_the_bytes_of_today(case: str) -> None:
    new, today = _RECIPES[case]

    assert lower(new()) == today()
    assert _url4(new()) == frozen_url4(f"gate_surface:{case}")


def test_gate_equality_follows_the_bytes() -> None:
    def gate(threshold: float) -> sf.Gate:
        return sf.Gate(when=sf.signal("conf").chosen() >= threshold, then=sf.Vote())

    assert gate(80) == gate(80.0)
    assert gate(80) != gate(81)


# ---------------------------------------------------------------- the references


def test_the_references_name_their_observed_number() -> None:
    assert sf.agreement() == sf.agreement()
    assert sf.signal("risk").mean() == sf.signal("risk").mean()
    assert sf.signal("risk").mean() != sf.signal("risk").chosen()


@pytest.mark.parametrize("key", ["cost_usd", "score:judge", "field:confidence"])
@pytest.mark.parametrize("method", ["chosen", "mean"])
def test_si1_an_e4a_key_is_not_a_gate_input(key: str, method: str) -> None:
    message = (
        rf"^sf\.signal\('{key}'\)\.{method}\(\) reads a declared signal; an E4a key such as "
        r"cost_usd is not a gate input$"
    )
    with pytest.raises(ValueError, match=message):
        getattr(sf.signal(key), method)()


@pytest.mark.parametrize("value", ["x", True, None])
def test_a_condition_compares_with_a_number(value: object) -> None:
    with pytest.raises(
        TypeError, match=rf"^a gate condition compares with a number, not {value!r}$"
    ):
        _ = sf.agreement() >= value  # type: ignore[operator]


def test_a_condition_compares_with_a_finite_number() -> None:
    with pytest.raises(ValueError, match=r"^a gate condition compares with a finite number$"):
        _ = sf.signal("risk").mean() <= float("inf")


@pytest.mark.parametrize(
    ("lo", "hi", "error", "message"),
    [
        (3, 2, ValueError, r"^between\(lo, hi\) needs lo <= hi$"),
        ("a", 2, TypeError, r"^between\(lo, hi\) takes two numbers$"),
        (1, float("nan"), ValueError, r"^between\(lo, hi\) needs finite numbers$"),
    ],
    ids=["order", "type", "finite"],
)
def test_between_checks_its_band(
    lo: object, hi: object, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        sf.signal("risk").mean().between(lo, hi)  # type: ignore[arg-type]


def test_an_agreement_band_is_a_share() -> None:
    with pytest.raises(ValueError, match=_SHARE):
        sf.agreement().between(0.5, 2)


@pytest.mark.parametrize("threshold", [1.5, -0.1])
def test_an_agreement_condition_is_a_share(threshold: float) -> None:
    with pytest.raises(ValueError, match=_SHARE):
        _ = sf.agreement() > threshold


def test_a_huge_int_is_not_finite() -> None:
    with pytest.raises(ValueError, match=r"^a gate condition compares with a finite number$"):
        _ = sf.signal("risk").mean() <= 10**400
    with pytest.raises(ValueError, match=r"^between\(lo, hi\) needs finite numbers$"):
        sf.signal("risk").mean().between(0, 10**400)


def test_minus_zero_is_zero_in_values_and_bytes() -> None:
    def gate(zero: float, band: float) -> sf.Gate:
        return sf.Gate(
            when=sf.signal("risk").mean() <= zero,
            then=sf.Vote(),
            abstain_if=sf.signal("risk").mean().between(band, 1),
        )

    assert gate(-0.0, -0.0) == gate(0.0, 0.0)
    assert _url4(_gated(gate(-0.0, -0.0), signals=_SEVERITY)) == _url4(
        _gated(gate(0.0, 0.0), signals=_SEVERITY)
    )


def test_the_gate_references_have_source_like_reprs() -> None:
    assert repr(sf.agreement()) == "agreement()"
    assert repr(sf.agreement() >= 0.5) == "agreement() >= 0.5"
    assert repr(sf.signal("conf").chosen() < 80) == "signal('conf').chosen() < 80.0"
    assert repr(sf.signal("risk").mean().between(2.5, 3.5)) == (
        "signal('risk').mean().between(2.5, 3.5)"
    )


# ---------------------------------------------------------------- GA-1 .. GA-6


def test_ga1_an_agreement_gate_keeps_a_high_agreement() -> None:
    with pytest.raises(
        ValueError,
        match=r"^an agreement gate keeps the majority when the agreement is high; use '>=' or "
        r"'>'$",
    ):
        sf.Gate(when=sf.agreement() <= 0.7, then=sf.Vote())
    with pytest.raises(ValueError, match=_SHARE):
        sf.Gate(when=sf.agreement() >= 1.5, then=sf.Vote())


def test_ga2_a_gate_reads_a_declared_name_of_its_block() -> None:
    gate = sf.Gate(when=sf.signal("conf").chosen() >= 80, then=sf.Vote())

    with pytest.raises(
        ValueError,
        match=r"^the gate reads 'chosen:conf', but this Fusion does not declare 'conf' "
        r"\(declared: none\)$",
    ):
        _ = sf.Fanout(_PANEL) >> gate


@pytest.mark.parametrize(
    "then", [sf.Median(), sf.ArgMax("cost_usd"), "vote"], ids=["median", "argmax", "text"]
)
def test_ga3_then_takes_a_vote(then: object) -> None:
    with pytest.raises(TypeError, match=r"^sf\.Gate then= takes sf\.Vote until E4c$"):
        sf.Gate(when=sf.agreement() >= 0.7, then=then)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "writer",
    [
        sf.Pipeline(["prov/a", "prov/b"]),
        sf.Fanout(["prov/a", "prov/b"]) >> sf.Synthesize("prov/s"),
    ],
    ids=["pipeline", "chain"],
)
def test_ga4_a_writer_fallback_is_one_model_call(writer: sf.Recipe) -> None:
    with pytest.raises(
        ValueError,
        match=r"^sf\.Gate otherwise=sf\.Synthesize\(\.\.\.\) makes one model call: give it a "
        r"model route or a sf\.Model$",
    ):
        sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote(), otherwise=sf.Synthesize(writer))


@pytest.mark.parametrize(
    "otherwise", ["fallback", sf.Vote(), sf.Model("prov/w")], ids=["text", "vote", "model"]
)
def test_otherwise_takes_abstain_a_judge_pick_or_a_writer(otherwise: object) -> None:
    with pytest.raises(
        (TypeError, ValueError),
        match=r"^sf\.Gate otherwise= takes 'abstain', sf\.JudgePick\(\.\.\.\) or "
        r"sf\.Synthesize\(\.\.\.\)$",
    ):
        sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote(), otherwise=otherwise)  # type: ignore[arg-type]


def test_ga5_abstain_if_reads_the_same_number_as_when() -> None:
    with pytest.raises(ValueError, match=r"^abstain_if must read the same number as when$"):
        sf.Gate(
            when=sf.signal("risk").mean() <= 3.0,
            then=sf.Vote(),
            abstain_if=sf.signal("risk").chosen().between(2.5, 3.5),
        )


def test_abstain_if_takes_a_band() -> None:
    with pytest.raises(TypeError, match=r"^sf\.Gate abstain_if= takes ref\.between\(lo, hi\)$"):
        sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote(), abstain_if=(0.2, 0.3))  # type: ignore[arg-type]


def test_when_takes_a_condition() -> None:
    with pytest.raises(
        TypeError,
        match=r"^sf\.Gate when= takes a condition such as sf\.agreement\(\) >= 0\.7 or "
        r"sf\.signal\('x'\)\.mean\(\) <= 3\.0$",
    ):
        sf.Gate(when=sf.agreement(), then=sf.Vote())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "over", ["field:answer", sf.Extract("regex", pattern="A: (.*)")], ids=["field", "extract"]
)
def test_ga6_a_gated_vote_reads_a_rule_name(over: object) -> None:
    with pytest.raises(ValueError, match=r"^a gated vote reads a rule name in over= until E4c$"):
        sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote(over=over))  # type: ignore[arg-type]


# ---------------------------------------------------------------- the block rules


@pytest.mark.parametrize(
    "otherwise",
    [sf.JudgePick("prov/judge", rubric=_PICK), sf.Synthesize("prov/writer")],
    ids=["judge-pick", "writer"],
)
def test_nrc1_a_model_fallback_gate_cannot_follow_a_narrow_step(otherwise: object) -> None:
    gate = sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote(), otherwise=otherwise)  # type: ignore[arg-type]

    with pytest.raises(
        ValueError,
        match=r"^sf\.Gate makes its own call over every member, so it cannot follow a narrow "
        r"step$",
    ):
        _ = sf.Fanout(_PANEL) >> sf.Rank(2, by="cost_usd") >> gate


def test_an_abstain_gate_after_a_narrow_step_compiles_since_unit_5() -> None:
    gate = sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote())

    lowered = lower(sf.Fanout(_PANEL) >> sf.Rank(2, by="cost_usd") >> gate)

    assert isinstance(lowered, FusionNode)
    assert lowered.synthesizer._narrow == (RankNode(2, by_signal=sf.signal("cost_usd")),)  # type: ignore[union-attr]


def test_ch10_a_gated_judge_weighted_vote_reads_the_judge() -> None:
    gate = sf.Gate(when=sf.agreement() >= 0.7, then=sf.Vote(weights="score:judge"))

    with pytest.raises(
        ValueError, match=r"^score:judge needs sf\.Judge\(\.\.\.\) after sf\.Fanout$"
    ):
        _ = sf.Fanout(_PANEL) >> gate


def test_ch10_a_judge_pick_fallback_does_not_read_the_judge() -> None:
    gate = sf.Gate(
        when=sf.agreement() >= 0.7,
        then=sf.Vote(),
        otherwise=sf.JudgePick("prov/judge", rubric=_PICK),
    )

    with pytest.raises(
        ValueError, match=r"^sf\.Judge scores the members, but no step reads score:judge$"
    ):
        _ = sf.Fanout(_PANEL) >> sf.Judge("prov/scorer", rubric="r") >> gate


def test_the_docstring_says_the_fallback_runs_on_every_case() -> None:
    doc = inspect.getdoc(sf.Gate)

    assert doc is not None
    assert "every Case" in doc
    assert "E4c" in doc
