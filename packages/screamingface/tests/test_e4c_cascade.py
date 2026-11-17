"""sf.Cascade: a shortcut that returns nested sf.Gate values (cheap first, escalate on a line).

FEATURE: E4c (OME-1291) cascade PRD rows CA#1, #7, #8, #9, #14 - #24, #26, in the line form of the
2026-11-12 review (the Engine-world rows are in
``apps/screamingface-engine/tests/unit/test_e4c_cascade_runs.py``).
STORY: as a researcher whose result is a saving, ``sf.Cascade(t1, sf.escalate_if(...), t2)`` is
the same value and the same bytes as the nested Gates I could write by hand; each reason to
escalate is a line I wrote; a wrong tier or a missing line is refused before any run, and a
repeated sample seed warns.
"""

from __future__ import annotations

import inspect
import warnings
from typing import Any

import pytest
from _reducer_fixtures import engine_operators

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._surface.chain import Pipeline

_CONF = {"conf": sf.Verbalized("Confidence: ([0-9]+)")}
_CA13 = (
    r"^a cascade tier before a sf\.escalate_if line must end in a reducer step such as "
    r"sf\.Vote\(\): write sf\.Fanout\(\[m\], signals=\.\.\.\) >> sf\.Vote\(\)$"
)
_LOW = sf.escalate_if(sf.agreement() < 0.8)


def _tier(*routes: str):
    return sf.Fanout(list(routes)) >> sf.Vote()


def _opt(*routes: str):
    return sf.Fanout([sf.Model(route, optional=True) for route in routes], quorum=0)


def _chain(value: object) -> Pipeline:
    assert isinstance(value, Pipeline)
    return value


def _compiled(recipe: object) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4  # type: ignore[arg-type]


def _hand_written():
    inner = sf.Fanout(["prov/c", "prov/d"]) >> sf.Gate(
        when=sf.agreement() >= 0.8, then=sf.Vote(), otherwise="prov/large"
    )
    return sf.Fanout(["prov/a", "prov/b"]) >> sf.Gate(
        when=sf.agreement() >= 0.8, then=sf.Vote(), otherwise=inner
    )


def _cascade():
    return sf.Cascade(
        _tier("prov/a", "prov/b"), _LOW, _tier("prov/c", "prov/d"), _LOW, "prov/large"
    )


# --- CHAR (CA#1) ----------------------------------------------------------------------------------


def test_agreement_keep_form_refuses_less_than() -> None:
    with pytest.raises(
        ValueError,
        match=r"^an agreement gate keeps the majority when the agreement is high; use '>=' or "
        r"'>'$",
    ):
        sf.Gate(when=sf.agreement() <= 0.7, then=sf.Vote())


# --- the shortcut builds nested Gates (CA#7, #8, #9, #14, #21, #23) -------------------------------


def test_cascade_equals_the_hand_written_nested_gates() -> None:
    assert _cascade() == _hand_written()


def test_cascade_compiles_to_the_same_bytes_as_nested_gates() -> None:
    assert _compiled(_cascade()) == _compiled(_hand_written())


@pytest.mark.parametrize(
    ("escalate", "keep"),
    [("<", ">="), ("<=", ">"), (">", "<="), (">=", "<")],
)
def test_escalate_form_maps_to_the_keep_form(escalate: str, keep: str) -> None:
    mean = sf.signal("conf").mean()
    condition = {"<": mean < 80, "<=": mean <= 80, ">": mean > 80, ">=": mean >= 80}[escalate]
    tier = sf.Fanout(["prov/a", "prov/b"], signals=_CONF) >> sf.Vote()
    chain = _chain(sf.Cascade(tier, sf.escalate_if(condition), "prov/large"))

    gate = chain.steps[-1]
    assert isinstance(gate, sf.Gate)
    assert gate.when.cmp == keep  # type: ignore[union-attr]
    assert gate.when.threshold == 80.0  # type: ignore[union-attr]


def test_each_line_has_its_own_condition() -> None:
    mean = sf.signal("conf").mean()
    chain = _chain(
        sf.Cascade(
            sf.Fanout(["prov/a"], signals=_CONF) >> sf.Vote(),
            sf.escalate_if(mean < 10),
            sf.Fanout(["prov/b"], signals=_CONF) >> sf.Vote(),
            sf.escalate_if(mean < 20),
            "prov/large",
        )
    )
    outer = chain.steps[-1]
    inner = outer.otherwise.steps[-1]  # type: ignore[union-attr]
    assert (outer.when.threshold, inner.when.threshold) == (10.0, 20.0)  # type: ignore[union-attr]


def test_a_signal_line_names_the_number_it_reads() -> None:
    # 2026-11-12 round 2 (owner): a bare sf.signal("conf") is refused in a condition
    # (test_e4c_bare_signal_refused.py); the line writes .chosen() or .mean().
    assert (
        repr(sf.escalate_if(sf.signal("conf").chosen() < 70))
        == "escalate_if(signal('conf').chosen() < 70.0)"
    )
    gate = sf.Gate(when=sf.signal("conf").chosen() >= 70, then=sf.Vote())
    assert gate.when == (sf.signal("conf").chosen() >= 70)


def test_a_condition_line_keeps_the_tier_as_written() -> None:
    # 2026-11-12: nothing escalates unless a line says so; the tier's quorum decides when it fails.
    member = sf.Model("prov/a", params={"temperature": 0.2})
    tier = sf.Fanout([member, "prov/b", "prov/c"], quorum=2) >> sf.Vote()
    fanout = _chain(sf.Cascade(tier, _LOW, "prov/large")).steps[0]

    assert isinstance(fanout, sf.Fanout)
    assert fanout.members == (member, sf.Model("prov/b"), sf.Model("prov/c"))
    assert fanout.quorum == 2


def test_an_unanswered_line_makes_the_tier_members_optional() -> None:
    member = sf.Model("prov/a", optional=True, params={"temperature": 0.2})
    tier = sf.Fanout([member, "prov/b"]) >> sf.Vote()
    chain = _chain(sf.Cascade(tier, sf.escalate_if(sf.unanswered()), "prov/large"))
    fanout = chain.steps[0]

    assert isinstance(fanout, sf.Fanout)
    assert fanout.members[0] == member  # CA-24: already optional, unchanged
    assert fanout.members[1] == sf.Model("prov/b", optional=True)
    assert fanout.quorum == 0
    assert chain.steps[-1].when == sf.answered()  # type: ignore[union-attr]


def test_first_success_wraps_a_route_and_equals_answered_gates() -> None:
    cascade = sf.Cascade(
        "prov/a",
        sf.escalate_if(sf.unanswered()),
        sf.Model("prov/b"),
        sf.escalate_if(sf.unanswered()),
        "prov/c",
    )
    inner = _opt("prov/b") >> sf.Gate(when=sf.answered(), then=sf.Vote(), otherwise="prov/c")
    assert cascade == _opt("prov/a") >> sf.Gate(when=sf.answered(), then=sf.Vote(), otherwise=inner)


def test_to_python_writes_nested_gates_and_recompiles() -> None:
    url4 = _compiled(_cascade())
    python = sf.Url4(url4).to_python()

    assert "Cascade" not in python
    assert python.count("sf.Gate(") == 2
    namespace: dict[str, object] = {}
    exec(python, namespace)  # noqa: S102 - the SDK's own generated code, offline
    assert _compiled(namespace["candidate"]) == url4


def test_to_python_round_trips_a_first_success_cascade_ending_in_fail() -> None:
    cascade = sf.Cascade(
        "prov/a", sf.escalate_if(sf.unanswered()), _tier("prov/b", "prov/c"), _LOW, sf.fail()
    )
    url4 = _compiled(cascade)
    python = sf.Url4(url4).to_python()

    assert "sf.fail()" in python
    namespace: dict[str, object] = {}
    exec(python, namespace)  # noqa: S102 - the SDK's own generated code, offline
    assert _compiled(namespace["candidate"]) == url4


@pytest.mark.parametrize(
    ("outcome", "word"), [(sf.abstain(), "abstain"), (sf.fail(), "fail_closed")]
)
def test_an_outcome_after_the_last_line_gates_the_last_tier(outcome: Any, word: str) -> None:
    chain = sf.Cascade(_tier("prov/a", "prov/b"), _LOW, _tier("prov/c", "prov/d"), _LOW, outcome)
    assert _compiled(chain)
    inner = chain.steps[-1].otherwise  # type: ignore[union-attr]
    assert inner.steps[-1].otherwise == word  # type: ignore[union-attr]
    assert repr(inner).endswith(f"otherwise={outcome!r})")


def test_the_last_tier_answers_unconditionally_without_an_outcome() -> None:
    chain = sf.Cascade(_tier("prov/a", "prov/b"), _LOW, _tier("prov/c", "prov/d"))
    assert chain.steps[-1].otherwise == _tier("prov/c", "prov/d")  # type: ignore[union-attr]


# --- refusals (CA#12 - #18) -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "parts",
    [(), (_tier("prov/a"),), (_tier("prov/a"), _LOW), ("prov/a", sf.abstain())],
    ids=["none", "one_tier", "ends_on_a_line", "no_line"],
)
def test_a_cascade_without_a_line_and_a_next_part_is_refused(parts: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        sf.Cascade(*parts)  # type: ignore[arg-type]


def test_the_list_form_is_refused() -> None:
    with pytest.raises(TypeError, match=r"^sf\.Cascade takes its tiers as arguments"):
        sf.Cascade([_tier("prov/a"), "prov/b"])  # type: ignore[arg-type]


def test_two_tiers_with_no_line_between_them_are_refused() -> None:
    with pytest.raises(
        ValueError,
        match=r"^sf\.Cascade part 4 can never run: write sf\.escalate_if\(\.\.\.\) after tier 2$",
    ):
        sf.Cascade(_tier("prov/a"), _LOW, _tier("prov/b"), "prov/large")


@pytest.mark.parametrize(
    "parts",
    [(_LOW, "prov/a"), (_tier("prov/a"), _LOW, _LOW, "prov/b")],
    ids=["line_first", "two_lines"],
)
def test_a_line_must_sit_between_two_tiers(parts: tuple[object, ...]) -> None:
    with pytest.raises(
        ValueError, match=r"^sf\.escalate_if\(\.\.\.\) goes between two sf\.Cascade tiers$"
    ):
        sf.Cascade(*parts)  # type: ignore[arg-type]


def test_an_outcome_is_the_last_part() -> None:
    with pytest.raises(
        ValueError, match=r"^sf\.abstain\(\) or sf\.fail\(\) is the last part of a sf\.Cascade$"
    ):
        sf.Cascade(_tier("prov/a"), _LOW, sf.abstain(), "prov/b")
    with pytest.raises(ValueError, match=r"^a sf\.Cascade starts with a tier$"):
        sf.Cascade(sf.fail(), _LOW, "prov/b")


@pytest.mark.parametrize("word", ["abstain", "fail_closed", "fail-closed", "Skip"])
@pytest.mark.parametrize("first", [True, False], ids=["first_tier", "last_tier"])
def test_an_outcome_word_string_is_refused(word: str, first: bool) -> None:
    # GT-12: a word, spelled any way, never becomes a model route, in any tier.
    unanswered = sf.escalate_if(sf.unanswered())
    parts = (word, unanswered, "prov/b") if first else (_tier("prov/a"), _LOW, word)
    with pytest.raises(
        TypeError,
        match=rf"^sf\.Cascade takes sf\.abstain\(\) or sf\.fail\(\) as its last part, not the "
        rf"word '{word}'$",
    ):
        sf.Cascade(*parts)


@pytest.mark.parametrize("value", [3, "x", sf.answered(), sf.agreement()])
def test_escalate_if_takes_a_condition(value: object) -> None:
    with pytest.raises(TypeError, match=r"^sf\.escalate_if takes a condition"):
        sf.escalate_if(value)


@pytest.mark.parametrize(
    "tier",
    [
        sf.Model("prov/a"),
        sf.Fanout(["prov/a", "prov/b"]),
        sf.Fanout(["prov/a", "prov/b"]) >> sf.Synthesize("prov/w"),
        sf.Fanout(["prov/a", "prov/b"], signals=_CONF) >> sf.Rank(1, by="conf"),
    ],
    ids=["model_with_condition", "open_fanout", "synthesize_end", "narrow_end"],
)
def test_gated_tier_without_a_reducer_is_refused(tier: object) -> None:
    with pytest.raises(TypeError, match=_CA13):
        sf.Cascade(tier, _LOW, "prov/large")  # type: ignore[arg-type]


def test_undeclared_signal_names_the_tier() -> None:
    with pytest.raises(ValueError, match=r"^sf\.Cascade tier 1:"):
        sf.Cascade(
            _tier("prov/a", "prov/b"),
            sf.escalate_if(sf.signal("conf").chosen() < 0.7),
            "prov/large",
        )


def test_inverted_agreement_escalation_is_refused() -> None:
    with pytest.raises(ValueError) as caught:
        sf.Cascade(_tier("prov/a", "prov/b"), sf.escalate_if(sf.agreement() >= 0.8), "prov/large")
    assert "sf.escalate_if(agreement() >= 0.8)" in str(caught.value)


def test_numeric_quorum_on_an_unanswered_tier_is_refused() -> None:
    tier = sf.Fanout(["prov/a", "prov/b", "prov/c"], quorum=2) >> sf.Vote()
    with pytest.raises(
        ValueError,
        match=r"^a sf\.escalate_if\(sf\.unanswered\(\)\) tier decides on the members that "
        r"answered; it takes quorum='all'$",
    ):
        sf.Cascade(tier, sf.escalate_if(sf.unanswered()), "prov/large")


# --- seeds, depth, docs (CA#22, #24, #26) ---------------------------------------------------------


def test_default_seed_collision_warns() -> None:
    first = sf.Fanout(sf.samples("prov/m", 2)) >> sf.Vote()
    repeated = sf.Fanout(sf.samples("prov/m", 5)) >> sf.Vote()
    line = sf.escalate_if(sf.agreement() < 1.0)
    with pytest.warns(sf.CascadeSeedWarning, match=r"tier 2 repeats seeds 0, 1 of tier 1"):
        sf.Cascade(first, line, repeated)
    fresh = sf.Fanout(sf.samples("prov/m", 5, seeds=range(2, 7))) >> sf.Vote()
    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.CascadeSeedWarning)
        sf.Cascade(first, line, fresh)


def _nested(levels: int, innermost: object) -> object:
    keywords = sf.RegexClassifier([("math", r"(?i)integral")])
    value: Any = innermost
    for _ in range(levels):
        value = sf.Gate(when=sf.label(keywords) == "math", then=value, otherwise="prov/general")
    return value


def test_cascade_in_a_branch_counts_toward_the_depth_cap() -> None:
    cascade = sf.Cascade(_tier("prov/a", "prov/b"), _LOW, "prov/large")
    # 6 input Gates around a 1-Gate cascade: 7 deep.
    assert _compiled(_nested(6, cascade))
    # 7 input Gates around it: 8 deep, the cap.
    assert _compiled(_nested(7, cascade))
    with pytest.raises(ValueError, match=r"^sf\.Gate nests at most 8 deep$"):
        _compiled(_nested(8, cascade))


def test_cascade_docstring_states_per_answer_and_no_isinstance() -> None:
    doc = inspect.getdoc(sf.Cascade)
    assert doc is not None
    assert "per full answer" in doc
    assert "isinstance(x, sf.Cascade)" in doc
    assert "not supported" in doc
    assert "Nothing escalates unless a line says so" in doc
    assert inspect.isfunction(sf.Cascade)


def test_the_new_names_are_exported() -> None:
    assert {"Cascade", "CascadeSeedWarning", "answered", "escalate_if", "unanswered"} <= set(
        sf.__all__
    )
    assert issubclass(sf.CascadeSeedWarning, sf.EvaluationWarning)
    assert repr(sf.answered()) == "answered()"
    assert repr(sf.unanswered()) == "unanswered()"
