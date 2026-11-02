"""A judge role passed in through a scorer argument is read, then given by the row's kwargs.

FEATURE: OME-1478 PR 1 of 2. HLE's ``json_judge(grader_role="grader")`` calls a helper,
``_resolve_grader(grader_role)``, which asks ``get_model(role=role)``. The reader used to stop
at ``role=role`` and report ``<unknown>``. It now follows the helper's parameter back to the
argument its caller passed, and when that is the scorer's own argument it reports a role
parameter. The row's kwargs then give the role: ``grader_role="grader"`` → ``"grader"``. Only
the kwargs give it, never the argument's default: inspect logs only arguments a scorer was built
with, so the role a row binds is always one its hashed kwargs state.

INVARIANT the suite defends: "could not tell" stays "unknown". A role from a local variable,
an argument the kwargs leave out or give no string, or a helper parameter nobody traced resolves to
``<unknown>``, which every caller still refuses. The old finding is kept beside the new one, so
a scorer reads exactly as before until a row's kwargs give its role.

Stand-ins: one eval package laid out like inspect_evals; every module raises on import, so a
test that reads it also proves nothing ran. They prove the reader's rules, not a real eval.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from screamingface_engine_inspect.judge_shape import UNKNOWN_ROLE, JudgeShape, judge_shape

#: Any stand-in module that runs has been imported, which the reader must never do.
_IMPORT_TRAP: str = 'raise RuntimeError("the judge-shape reader imported an eval module")\n'

#: Each scorer shape a role can arrive in, one function each. Line numbers matter: the
#: findings say where a role is asked, and the trap above is line 1.
_ROLE_SCORERS: str = _IMPORT_TRAP + textwrap.dedent(
    """
    from inspect_ai.model import get_model

    def _resolve_grader(role):
        return get_model(role=role)

    def through_a_helper(grader_role="grader"):
        async def score(state, target):
            return await _resolve_grader(grader_role).generate("Is it right?")
        return score

    def through_a_helper_by_keyword(grader_role="grader"):
        async def score(state, target):
            return await _resolve_grader(role=grader_role).generate("Is it right?")
        return score

    def asks_directly(grader_role="grader"):
        async def score(state, target):
            return await get_model(role=grader_role).generate("Is it right?")
        return score

    def with_no_default(grader_role):
        async def score(state, target):
            return await get_model(role=grader_role).generate("Is it right?")
        return score

    def from_a_local():
        async def score(state, target):
            role = state.metadata["role"]
            return await get_model(role=role).generate("Is it right?")
        return score

    def through_a_lookup_local(grader_role="grader"):
        async def score(state, target):
            grader = _resolve_grader(grader_role)
            return await model_graded_qa(model=grader)(state, target)
        return score

    def _pick_a_name():
        return "openai/gpt-4o"

    def through_a_named_local():
        async def score(state, target):
            grader = _pick_a_name()
            return await model_graded_qa(model=grader)(state, target)
        return score

    def through_a_reassigned_local(grader_role="grader"):
        async def score(state, target):
            grader = _resolve_grader(grader_role)
            grader = state.metadata["judge"]
            return await model_graded_qa(model=grader)(state, target)
        return score

    def _judge_named(name):
        return get_model(name)

    def through_a_helper_naming_its_judge():
        async def score(state, target):
            grader = _judge_named("openai/gpt-4o")
            return await model_graded_qa(model=grader)(state, target)
        return score

    def through_a_helper_given_a_judge_argument(judge="openai/gpt-4o"):
        async def score(state, target):
            grader = _judge_named(judge)
            return await model_graded_qa(model=grader)(state, target)
        return score

    def reassigns_its_role(grader_role="grader"):
        grader_role = "grader_2"
        async def score(state, target):
            return await get_model(role=grader_role).generate("Is it right?")
        return score
    """
)


@pytest.fixture
def role_scorers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Lay the stand-in package out on the import path; return the scorer module's name."""

    package: Path = tmp_path / "role_stand_ins" / "quiz"
    package.mkdir(parents=True)
    (tmp_path / "role_stand_ins" / "__init__.py").write_text(_IMPORT_TRAP, encoding="utf-8")
    (package / "__init__.py").write_text(_IMPORT_TRAP, encoding="utf-8")
    (package / "scorer.py").write_text(_ROLE_SCORERS, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return "role_stand_ins.quiz.scorer"


def test_a_role_passed_to_a_helper_from_a_scorer_argument_is_a_role_parameter(
    role_scorers: str,
) -> None:
    """HLE's shape: the helper asks at line 6, the role comes from ``grader_role``."""

    shape: JudgeShape = judge_shape(f"{role_scorers}:through_a_helper")

    assert shape.role_parameters == (("grader_role", "scorer.py:6"),)
    assert shape.roles_given({"grader_role": "grader"}) == ("grader",)


def test_a_helper_parameter_bound_by_keyword_is_followed_too(role_scorers: str) -> None:
    shape: JudgeShape = judge_shape(f"{role_scorers}:through_a_helper_by_keyword")

    assert shape.roles_given({"grader_role": "grader"}) == ("grader",)


def test_the_kwargs_give_the_role_and_the_default_never_does(role_scorers: str) -> None:
    """WHY never the default: inspect logs only passed arguments, so a role the row leaves
    out would be bound outside the kwargs Benchmark identity hashes. The row must state it."""

    shape: JudgeShape = judge_shape(f"{role_scorers}:asks_directly")

    assert shape.roles_given({"grader_role": "grader_2"}) == ("grader_2",)
    assert shape.roles_given({}) == (UNKNOWN_ROLE,)


def test_the_old_finding_still_reads_the_same(role_scorers: str) -> None:
    """The scorer still reaches a judge and still says so the old way, so a check that reads
    the shape without the row's kwargs refuses exactly as before."""

    shape: JudgeShape = judge_shape(f"{role_scorers}:asks_directly")

    assert shape.reaches_a_judge
    assert shape.described() == "get_model(role=<unknown>) in scorer.py:20"


def test_an_argument_with_no_string_value_stays_unknown(role_scorers: str) -> None:
    shape: JudgeShape = judge_shape(f"{role_scorers}:with_no_default")

    assert shape.roles_given({}) == (UNKNOWN_ROLE,)
    assert shape.roles_given({"grader_role": None}) == (UNKNOWN_ROLE,)
    assert shape.roles_given({"grader_role": ""}) == (UNKNOWN_ROLE,)


def test_a_role_from_a_local_variable_stays_unknown_whatever_the_kwargs(role_scorers: str) -> None:
    """WHY: nothing in the row says what ``state.metadata["role"]`` holds at grading time."""

    shape: JudgeShape = judge_shape(f"{role_scorers}:from_a_local")

    assert shape.role_parameters == ()
    assert shape.roles_given({"role": "grader"}) == (UNKNOWN_ROLE,)


def test_hles_real_json_judge_gives_the_grader_role_from_its_argument() -> None:
    pytest.importorskip("inspect_evals")

    shape: JudgeShape = judge_shape("inspect_evals.hle.scorers:json_judge")

    # Two entries, one per get_model call in _resolve_grader (bound role, then default).
    assert {parameter for parameter, _ in shape.role_parameters} == {"grader_role"}
    assert shape.roles_given({"prompt": "json_judge", "grader_role": "grader"}) == ("grader",)


# ── a judge held in a local that only ever holds a model lookup (hle's regex_judge) ──


def test_a_local_holding_a_helpers_model_lookup_is_that_lookup(role_scorers: str) -> None:
    """hle's regex_judge: ``grader = _resolve_grader(grader_role)`` then
    ``model_graded_qa(model=grader)``. Every return of the helper is a ``get_model`` call, so
    the local is the lookup the walk already sorts, not an unread judge."""

    shape: JudgeShape = judge_shape(f"{role_scorers}:through_a_lookup_local")

    assert shape.unread == ()
    assert shape.roles_given({"grader_role": "grader"}) == ("grader",)


def test_a_local_from_a_helper_returning_a_name_stays_unread(role_scorers: str) -> None:
    """WHY: ``_pick_a_name`` hands back a model name, a judge no row pins; reading it as a
    lookup would make the scorer look judge-free."""

    shape: JudgeShape = judge_shape(f"{role_scorers}:through_a_named_local")

    assert shape.reaches_a_judge
    assert shape.unread != ()


def test_a_local_reassigned_from_anything_else_stays_unread(role_scorers: str) -> None:
    """WHY: only a local EVERY assignment of which is a lookup is one; a later
    ``grader = state.metadata["judge"]`` could hold any judge at grading time."""

    shape: JudgeShape = judge_shape(f"{role_scorers}:through_a_reassigned_local")

    assert shape.unread != ()


def test_hles_real_regex_judge_reads_in_full_with_the_grader_role() -> None:
    pytest.importorskip("inspect_evals")

    shape: JudgeShape = judge_shape("inspect_evals.hle.scorers:regex_judge")

    assert shape.unread == ()
    assert shape.roles_given({"grader_role": "grader"}) == ("grader",)


# ── review findings on #1631: shapes that must stay closed ──


@pytest.mark.parametrize(
    "constructor", ["through_a_helper_naming_its_judge", "through_a_helper_given_a_judge_argument"]
)
def test_a_local_from_a_helper_returning_a_named_model_stays_unread(
    role_scorers: str, constructor: str
) -> None:
    """WHY: ``_judge_named`` returns ``get_model(name)``, so the judge is whatever its caller
    named (a literal, or a scorer argument no judge check reads). Reading the local as a
    lookup would import the scorer as judge-free, and inspect would then build gpt-4o
    directly, outside the gateway."""

    shape: JudgeShape = judge_shape(f"{role_scorers}:{constructor}")

    assert shape.reaches_a_judge
    assert shape.unread != ()


def test_a_role_argument_the_scorer_reassigns_stays_unknown(role_scorers: str) -> None:
    """WHY: after ``grader_role = "grader_2"`` the argument no longer holds what the row
    passed, so the kwargs cannot give the role the scorer asks for."""

    shape: JudgeShape = judge_shape(f"{role_scorers}:reassigns_its_role")

    assert shape.roles_given({"grader_role": "grader"}) == (UNKNOWN_ROLE,)
