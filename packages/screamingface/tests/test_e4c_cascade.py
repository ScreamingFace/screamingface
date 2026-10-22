"""sf.Cascade: a shortcut that returns nested sf.Gate values (cheap first, escalate when weak).

FEATURE: E4c (OME-1291) cascade PRD rows CA#1, #7, #8, #9, #14 - #24, #26 (the Engine-world rows
are in ``apps/screamingface-engine/tests/unit/test_e4c_cascade_runs.py``).
STORY: as a researcher whose result is a saving, ``sf.Cascade([...], escalate_if=...)`` is the
same value and the same bytes as the nested Gates I could write by hand; a wrong stage is refused
before any run, and a repeated sample seed warns.
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
    r"^a cascade stage before the last must end in a reducer step such as sf\.Vote\(\): write "
    r"sf\.Fanout\(\[m\], signals=\.\.\.\) >> sf\.Vote\(\)$"
)


def _stage(*routes: str):
    return sf.Fanout(list(routes)) >> sf.Vote()


def _opt(*routes: str):
    return sf.Fanout([sf.Model(route, optional=True) for route in routes], quorum=0)


def _chain(value: object) -> Pipeline:
    assert isinstance(value, Pipeline)
    return value


def _compiled(recipe: object) -> str:
    return compile_candidate(recipe, operators=engine_operators()).url4  # type: ignore[arg-type]


def _hand_written():
    inner = _opt("prov/c", "prov/d") >> sf.Gate(
        when=sf.agreement() >= 0.8, then=sf.Vote(), otherwise="prov/large"
    )
    return _opt("prov/a", "prov/b") >> sf.Gate(
        when=sf.agreement() >= 0.8, then=sf.Vote(), otherwise=inner
    )


def _cascade():
    return sf.Cascade(
        [_stage("prov/a", "prov/b"), _stage("prov/c", "prov/d"), "prov/large"],
        escalate_if=sf.agreement() < 0.8,
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
    stage = sf.Fanout(["prov/a", "prov/b"], signals=_CONF) >> sf.Vote()
    chain = _chain(sf.Cascade([stage, "prov/large"], escalate_if=condition))

    gate = chain.steps[-1]
    assert isinstance(gate, sf.Gate)
    assert gate.when.cmp == keep  # type: ignore[union-attr]
    assert gate.when.threshold == 80.0  # type: ignore[union-attr]


def test_one_condition_or_one_per_gated_stage() -> None:
    mean = sf.signal("conf").mean()
    stages = [
        sf.Fanout(["prov/a"], signals=_CONF) >> sf.Vote(),
        sf.Fanout(["prov/b"], signals=_CONF) >> sf.Vote(),
        "prov/large",
    ]
    chain = _chain(sf.Cascade(stages, escalate_if=[mean < 10, mean < 20]))
    outer = chain.steps[-1]
    inner = outer.otherwise.steps[-1]  # type: ignore[union-attr]
    assert (outer.when.threshold, inner.when.threshold) == (10.0, 20.0)  # type: ignore[union-attr]
    with pytest.raises(
        ValueError,
        match=r"^sf\.Cascade escalate_if= takes one condition or one per gated stage \(2\)$",
    ):
        sf.Cascade(stages, escalate_if=[mean < 10])


def test_to_python_writes_nested_gates_and_recompiles() -> None:
    url4 = _compiled(_cascade())
    python = sf.Url4(url4).to_python()

    assert "Cascade" not in python
    assert python.count("sf.Gate(") == 2
    namespace: dict[str, object] = {}
    exec(python, namespace)  # noqa: S102 - the SDK's own generated code, offline
    assert _compiled(namespace["candidate"]) == url4


def test_author_optional_member_is_unchanged() -> None:
    member = sf.Model("prov/a", optional=True, params={"temperature": 0.2})
    chain = _chain(
        sf.Cascade(
            [sf.Fanout([member, "prov/b"]) >> sf.Vote(), "prov/large"],
            escalate_if=sf.agreement() < 0.8,
        )
    )
    fanout = chain.steps[0]
    assert isinstance(fanout, sf.Fanout)
    assert fanout.members[0] == member
    assert fanout.members[1] == sf.Model("prov/b", optional=True)
    assert fanout.quorum == 0


# --- refusals (CA#15 - #20) -----------------------------------------------------------------------


@pytest.mark.parametrize("stages", [[], [_stage("prov/a")]], ids=["none", "one"])
def test_fewer_than_two_stages_is_refused(stages: list[object]) -> None:
    with pytest.raises(ValueError, match=r"^sf\.Cascade needs at least two stages$"):
        sf.Cascade(stages, escalate_if=sf.agreement() < 0.8)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "stage",
    [
        sf.Model("prov/a"),
        sf.Fanout(["prov/a", "prov/b"]),
        sf.Fanout(["prov/a", "prov/b"]) >> sf.Synthesize("prov/w"),
        sf.Fanout(["prov/a", "prov/b"], signals=_CONF) >> sf.Rank(1, by="conf"),
    ],
    ids=["model_with_condition", "open_fanout", "synthesize_end", "narrow_end"],
)
def test_gated_stage_without_a_reducer_is_refused(stage: object) -> None:
    with pytest.raises(TypeError, match=_CA13):
        sf.Cascade([stage, "prov/large"], escalate_if=sf.agreement() < 0.8)  # type: ignore[list-item]


def test_undeclared_signal_names_the_stage() -> None:
    with pytest.raises(ValueError, match=r"^sf\.Cascade stage 1:"):
        sf.Cascade(
            [_stage("prov/a", "prov/b"), "prov/large"],
            escalate_if=sf.signal("conf").chosen() < 0.7,
        )


def test_inverted_agreement_escalation_is_refused() -> None:
    with pytest.raises(ValueError) as caught:
        sf.Cascade([_stage("prov/a", "prov/b"), "prov/large"], escalate_if=sf.agreement() >= 0.8)
    assert "escalate_if=agreement() >= 0.8" in str(caught.value)


def test_numeric_quorum_on_a_gated_stage_is_refused() -> None:
    stage = sf.Fanout(["prov/a", "prov/b", "prov/c"], quorum=2) >> sf.Vote()
    with pytest.raises(
        ValueError,
        match=r"^a cascade stage decides on the members that answered; it takes quorum='all'$",
    ):
        sf.Cascade([stage, "prov/large"], escalate_if=sf.agreement() < 0.8)


@pytest.mark.parametrize("otherwise", [None, "abstain", "fail_closed"])
def test_otherwise_takes_none_abstain_or_fail_closed(otherwise: str | None) -> None:
    chain = sf.Cascade(
        [_stage("prov/a", "prov/b"), _stage("prov/c", "prov/d")],
        escalate_if=sf.agreement() < 0.8,
        otherwise=otherwise,  # type: ignore[arg-type]
    )
    assert _compiled(chain)
    inner = chain.steps[-1].otherwise  # type: ignore[union-attr]
    if otherwise is None:
        # the last stage answers unconditionally: it is the plain block
        assert inner == _stage("prov/c", "prov/d")
    else:
        assert inner.steps[-1].otherwise == otherwise  # type: ignore[union-attr]


@pytest.mark.parametrize("otherwise", ["skip", "prov/x", 3])
def test_otherwise_refuses_any_other_value(otherwise: object) -> None:
    with pytest.raises(
        ValueError, match=r"^sf\.Cascade otherwise= takes None, 'abstain' or 'fail_closed'$"
    ):
        sf.Cascade(
            [_stage("prov/a"), "prov/b"],
            escalate_if=sf.agreement() < 0.8,
            otherwise=otherwise,  # type: ignore[arg-type]
        )


# --- seeds, depth, docs (CA#22, #24, #26) ---------------------------------------------------------


def test_default_seed_collision_warns() -> None:
    first = sf.Fanout(sf.samples("prov/m", 2)) >> sf.Vote()
    repeated = sf.Fanout(sf.samples("prov/m", 5)) >> sf.Vote()
    with pytest.warns(sf.CascadeSeedWarning, match=r"stage 2 repeats seeds 0, 1 of stage 1"):
        sf.Cascade([first, repeated], escalate_if=sf.agreement() < 1.0)
    fresh = sf.Fanout(sf.samples("prov/m", 5, seeds=range(2, 7))) >> sf.Vote()
    with warnings.catch_warnings():
        warnings.simplefilter("error", sf.CascadeSeedWarning)
        sf.Cascade([first, fresh], escalate_if=sf.agreement() < 1.0)


def _nested(levels: int, innermost: object) -> object:
    keywords = sf.Keywords([("math", r"(?i)integral")])
    value: Any = innermost
    for _ in range(levels):
        value = sf.Gate(when=sf.label(keywords) == "math", then=value, otherwise="prov/general")
    return value


def test_cascade_in_a_branch_counts_toward_the_depth_cap() -> None:
    cascade = sf.Cascade(
        [_stage("prov/a", "prov/b"), "prov/large"], escalate_if=sf.agreement() < 0.8
    )
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
    assert inspect.isfunction(sf.Cascade)


def test_the_new_names_are_exported() -> None:
    assert {"Cascade", "CascadeSeedWarning", "answered"} <= set(sf.__all__)
    assert issubclass(sf.CascadeSeedWarning, sf.EvaluationWarning)
    assert repr(sf.answered()) == "answered()"
