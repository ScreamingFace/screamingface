"""The judge-shape reader: how a scorer reaches a judge its kwargs never name (OME-1602, F2).

INVARIANT: the reader reads source and never imports it. Every stand-in package below raises
on import, so a test that reads it also proves nothing was executed. The stand-ins are laid
out like inspect_evals (``<root>.<eval>.<module>``), because a scorer's helpers are followed
only inside its own root package. They prove the reader's rules, not any real eval's scorer.

No inspect import is needed: the reader is plain ``ast``, so these run without the extra.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from screamingface_engine_inspect.judge_shape import JudgeShape, judge_shape

#: Any stand-in module that runs has been imported, which the reader must never do.
_IMPORT_TRAP: str = 'raise RuntimeError("the judge-shape reader imported an eval module")\n'

#: The stand-in eval package's modules, by file name.
_QUIZ_FILES: dict[str, str] = {
    "__init__.py": _IMPORT_TRAP,
    "task.py": _IMPORT_TRAP
    + textwrap.dedent(
        """
        from .scorer import asks_the_grader, through_a_helper, through_another_eval
        """
    ),
    "helpers.py": _IMPORT_TRAP
    + textwrap.dedent(
        """
        from inspect_ai.model import get_model

        async def ask_the_grader(question):
            return await get_model(role="grader").generate(question)
        """
    ),
    "scorer.py": _IMPORT_TRAP
    + textwrap.dedent(
        """
        from inspect_ai.model import get_model
        from stand_in_evals.other.helpers import ask_elsewhere
        from .helpers import ask_the_grader

        def asks_the_grader():
            async def score(state, target):
                return await get_model(role="grader").generate("Is it right?")
            return score

        def through_a_helper():
            async def score(state, target):
                return await ask_the_grader("Is it right?")
            return score

        def through_another_eval():
            async def score(state, target):
                return await ask_elsewhere("Is it right?")
            return score

        def asks_the_candidate():
            async def score(state, target):
                return await get_model().generate("Is it right?")
            return score

        def names_its_model(model="openai/gpt-4o"):
            async def score(state, target):
                get_model(model)
                get_model(model=model)
            return score

        def takes_judges(include_history=None, *, judge_model=None, grader_models=None):
            async def score(state, target):
                return None
            return score

        def judge_free():
            async def score(state, target):
                return None
            return score
        """
    ),
}

#: A second eval in the same root whose helper asks the grader role (aime2025 imports its
#: scorer from ``inspect_evals.utils``): followed from the quiz package.
_OTHER_HELPERS: str = _IMPORT_TRAP + textwrap.dedent(
    """
    from inspect_ai.model import get_model

    async def ask_elsewhere(question):
        return await get_model(role="grader").generate(question)
    """
)


@pytest.fixture
def stand_in_evals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Lay the stand-in eval packages out on the import path; return the quiz module prefix."""

    quiz: Path = tmp_path / "stand_in_evals" / "quiz"
    quiz.mkdir(parents=True)
    (tmp_path / "stand_in_evals" / "__init__.py").write_text(_IMPORT_TRAP, encoding="utf-8")
    for name, text in _QUIZ_FILES.items():
        (quiz / name).write_text(text, encoding="utf-8")
    other: Path = tmp_path / "stand_in_evals" / "other"
    other.mkdir()
    (other / "__init__.py").write_text(_IMPORT_TRAP, encoding="utf-8")
    (other / "helpers.py").write_text(_OTHER_HELPERS, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return "stand_in_evals.quiz"


def test_a_grader_role_asked_in_the_scorer_body_is_read_with_where(stand_in_evals: str) -> None:
    shape: JudgeShape = judge_shape(f"{stand_in_evals}.scorer:asks_the_grader")

    assert shape.roles == (("grader", "scorer.py:9"),)
    assert shape.described() == "get_model(role='grader') in scorer.py:9"


def test_a_row_naming_the_task_module_reaches_the_def_it_imports(stand_in_evals: str) -> None:
    """A row names the scorer by the Task module that imports it (simpleqa's shape)."""

    shape: JudgeShape = judge_shape(f"{stand_in_evals}.task:asks_the_grader")

    assert shape.roles == (("grader", "scorer.py:9"),)


def test_a_role_asked_one_helper_down_in_the_same_eval_is_read(stand_in_evals: str) -> None:
    """persistbench's shape: the scorer calls ``_get_judge()``, which asks for the role."""

    shape: JudgeShape = judge_shape(f"{stand_in_evals}.task:through_a_helper")

    assert shape.roles == (("grader", "helpers.py:6"),)


def test_a_helper_from_another_eval_in_the_same_root_is_followed(stand_in_evals: str) -> None:
    """A judge one eval borrows from a sibling (``inspect_evals.utils``) is still a judge;
    stopping at the eval's own package read it as judge-free."""

    shape: JudgeShape = judge_shape(f"{stand_in_evals}.task:through_another_eval")

    assert shape.roles == (("grader", "helpers.py:6"),)


def test_get_model_with_no_model_is_the_model_under_test(stand_in_evals: str) -> None:
    shape: JudgeShape = judge_shape(f"{stand_in_evals}.scorer:asks_the_candidate")

    assert shape.model_under_test == ("scorer.py:24",)
    assert shape.reaches_a_judge


def test_get_model_naming_its_model_is_not_a_judge_finding(stand_in_evals: str) -> None:
    """math's helper calls ``get_model(model)``: reading it as judged would drop math's
    exact-match scorers. The signature rule still sees the ``model`` parameter."""

    shape: JudgeShape = judge_shape(f"{stand_in_evals}.scorer:names_its_model")

    assert (shape.roles, shape.model_under_test) == ((), ())
    assert shape.parameters == ("model",)


def test_judge_parameters_are_read_from_the_signature_passed_or_not(stand_in_evals: str) -> None:
    """niah's shape: ``judge_model`` defaults to None and nobody passes it."""

    shape: JudgeShape = judge_shape(f"{stand_in_evals}.scorer:takes_judges")

    assert shape.parameters == ("judge_model", "grader_models")
    assert shape.described() == "parameter judge_model, grader_models"


def test_a_scorer_that_reaches_no_judge_has_an_empty_shape(stand_in_evals: str) -> None:
    shape: JudgeShape = judge_shape(f"{stand_in_evals}.scorer:judge_free")

    assert shape == JudgeShape()
    assert not shape.reaches_a_judge


def test_reading_never_imports_the_eval(stand_in_evals: str) -> None:
    judge_shape(f"{stand_in_evals}.task:through_a_helper")

    assert not [name for name in sys.modules if name.startswith("stand_in_evals")]


def test_inspects_own_scorers_are_never_read() -> None:
    """``model_graded_*`` is judged by its name; no other built-in takes a judge."""

    assert judge_shape("inspect_ai.scorer:model_graded_qa") == JudgeShape()


def test_a_scorer_whose_source_cannot_be_found_is_unread_because_unread_is_not_judge_free() -> None:
    """aime2025's scorer, named through a Task module that imports it from another eval,
    read as an empty shape: a judge-free row with nothing actually read."""

    shape: JudgeShape = judge_shape("no_such_eval_package.scorer:anything")

    assert shape.reaches_a_judge
    assert shape.described() == (
        "unread: the source of anything in no_such_eval_package.scorer was not found"
    )


# ── review findings on the first cut: fail closed on a role held in a variable ──

#: hle's shape: the role arrives as a scorer argument, so it is never a literal.
_VARIABLE_ROLE_SCORER: str = _IMPORT_TRAP + textwrap.dedent(
    """
    from inspect_ai.model import get_model

    def asks_a_role_it_was_given(grader_role="grader"):
        async def score(state, target):
            return await get_model(role=grader_role).generate("Is it right?")
        return score
    """
)


@pytest.fixture
def variable_role_scorer(stand_in_evals: str, tmp_path: Path) -> str:
    """Add hle's shape to the stand-in quiz package; return its module name."""

    (tmp_path / "stand_in_evals" / "quiz" / "variable_role.py").write_text(
        _VARIABLE_ROLE_SCORER, encoding="utf-8"
    )
    return f"{stand_in_evals}.variable_role"


def test_a_role_held_in_a_variable_reaches_a_judge_because_unread_is_not_judge_free(
    variable_role_scorer: str,
) -> None:
    """The reader cannot tell which role a variable holds, so it fails closed: hle's
    ``json_judge`` read as judge-free before, and would have shipped an unpinned judge."""

    shape: JudgeShape = judge_shape(f"{variable_role_scorer}:asks_a_role_it_was_given")

    assert shape.reaches_a_judge
    assert shape.described() == "get_model(role=<unknown>) in variable_role.py:7"


def test_hles_judges_reach_a_judge() -> None:
    pytest.importorskip("inspect_evals")

    for constructor in ("json_judge", "regex_judge"):
        assert judge_shape(f"inspect_evals.hle.scorers:{constructor}").reaches_a_judge


# ── review findings on the second cut: every shape the reader cannot follow fails closed ──

#: Shapes the second cut read as judge-free, or read only in part. One function each.
_HIDDEN_JUDGES: str = _IMPORT_TRAP + textwrap.dedent(
    """
    from inspect_ai.model import get_model as fetch_model
    from inspect_ai.scorer import model_graded_fact

    from stand_in_evals.quiz import helpers as quiz_helpers

    SCORERS = {"fact": model_graded_fact}

    def two_helpers_down():
        async def score(state, target):
            return await _first_helper("Is it right?")
        return score

    async def _first_helper(question):
        return await _second_helper(question)

    async def _second_helper(question):
        return await fetch_model(role="grader").generate(question)

    def through_a_module():
        async def score(state, target):
            return await quiz_helpers.ask_the_grader("Is it right?")
        return score

    def from_a_lookup_table(kind="fact"):
        return SCORERS[kind]()

    def judge_under_another_name(grader=None):
        async def score(state, target):
            return await fetch_model(grader).generate("Is it right?")
        return score

    def names_its_own_judge():
        async def score(state, target):
            return await fetch_model("openai/gpt-4o").generate("Is it right?")
        return score

    class _Judge:
        def __init__(self, judge_model="openai/gpt-4o"):
            self.model = fetch_model(judge_model)

    def builds_a_judge_class():
        judge = _Judge()
        async def score(state, target):
            return judge
        return score

    def asks_two_roles():
        async def score(state, target):
            await fetch_model(role="grader").generate("Is it right?")
            await fetch_model(role="critic").generate("Is it fair?")
            await fetch_model(role="grader").generate("Sure?")
        return score

    def wraps_model_graded_fact():
        return model_graded_fact()
    """
)


@pytest.fixture
def hidden_judges(stand_in_evals: str, tmp_path: Path) -> str:
    """Add the hidden-judge shapes to the stand-in quiz package; return its module name."""

    (tmp_path / "stand_in_evals" / "quiz" / "hidden.py").write_text(
        _HIDDEN_JUDGES, encoding="utf-8"
    )
    return f"{stand_in_evals}.hidden"


def test_a_role_asked_two_helpers_down_is_read(hidden_judges: str) -> None:
    """cti_realm's shape: a one-helper limit read its judge as missing, so the row would have
    landed judge-free and the Candidate would mark its own answers."""

    assert judge_shape(f"{hidden_judges}:two_helpers_down").roles == (("grader", "hidden.py:19"),)


def test_a_helper_called_through_its_module_is_followed(hidden_judges: str) -> None:
    assert judge_shape(f"{hidden_judges}:through_a_module").roles == (("grader", "helpers.py:6"),)


def test_a_lookup_table_holding_a_judged_scorer_is_unread(hidden_judges: str) -> None:
    """sciknoweval's shape: the scorer is picked from a table at grading time, so no call
    the reader follows reaches the judge; a value it cannot follow is unread, never
    judge-free."""

    shape: JudgeShape = judge_shape(f"{hidden_judges}:from_a_lookup_table")

    assert shape.reaches_a_judge
    assert shape.unread == (
        "hidden.py:8 passes model_graded_fact on as a value, a call the reader cannot follow",
    )


def test_a_judge_under_a_parameter_name_no_check_reads_is_unread(hidden_judges: str) -> None:
    """``get_model`` imported under another name, with the judge passed by position through
    a parameter not named like a judge: no kwarg check would see it."""

    shape: JudgeShape = judge_shape(f"{hidden_judges}:judge_under_another_name")

    assert shape.unread == (
        "a judge passed in through parameter grader in hidden.py:31, a name no judge check reads",
    )


def test_a_judge_named_in_the_code_is_unread(hidden_judges: str) -> None:
    """A hard-coded judge is called straight to its provider, outside any pin."""

    shape: JudgeShape = judge_shape(f"{hidden_judges}:names_its_own_judge")

    assert shape.unread == ("a judge named in the code ('openai/gpt-4o') in hidden.py:36",)


def test_a_judge_built_inside_a_helper_class_is_unread(hidden_judges: str) -> None:
    shape: JudgeShape = judge_shape(f"{hidden_judges}:builds_a_judge_class")

    assert shape.unread == (
        "a judge named in the code ('openai/gpt-4o', the default of judge_model) in hidden.py:41",
    )


def test_every_distinct_role_is_kept_once_where_it_is_first_asked(hidden_judges: str) -> None:
    """A second role used to be dropped by whoever read ``roles[0]``; a repeated role used to
    be listed once per call site (ipi_scorer listed grader twice)."""

    shape: JudgeShape = judge_shape(f"{hidden_judges}:asks_two_roles")

    assert shape.roles == (("grader", "hidden.py:51"), ("critic", "hidden.py:52"))


def test_model_graded_fact_with_no_model_asks_for_the_grader_role(hidden_judges: str) -> None:
    """inspect's model_graded_* grades with the ``grader`` role unless a model is passed."""

    assert judge_shape(f"{hidden_judges}:wraps_model_graded_fact").roles == (
        ("grader", "hidden.py:57"),
    )


#: A top-level package outside the scorer's root, standing in for inspect_ai's own code.
_OUTSIDE_HELPERS: str = _IMPORT_TRAP + textwrap.dedent(
    """
    def tally(state):
        return state
    """
)


def test_a_helper_outside_the_root_package_is_never_parsed(
    stand_in_evals: str, tmp_path: Path
) -> None:
    """Only the scorer's root package is read: inspect_ai's own code is never parsed."""

    (tmp_path / "stand_in_outside").mkdir()
    (tmp_path / "stand_in_outside" / "__init__.py").write_text(_OUTSIDE_HELPERS, encoding="utf-8")
    (tmp_path / "stand_in_evals" / "quiz" / "outside.py").write_text(
        _IMPORT_TRAP
        + "from stand_in_outside import tally\n\ndef counts():\n    return tally(None)\n",
        encoding="utf-8",
    )

    assert judge_shape(f"{stand_in_evals}.outside:counts") == JudgeShape()


@pytest.mark.parametrize(
    "reference",
    [
        # Picks its judge from a lookup table at grading time (planned for PR 7).
        "inspect_evals.sciknoweval.scorer:sciknoweval_scorer",
        # Asks for the grader role two helpers down.
        "inspect_evals.cti_realm.core.scorer:cti_realm_25_scorer",
    ],
)
def test_real_scorers_the_second_cut_read_as_judge_free_reach_a_judge(reference: str) -> None:
    pytest.importorskip("inspect_evals")

    assert judge_shape(reference).reaches_a_judge


@pytest.mark.parametrize(
    "reference",
    [
        # Imported from inspect_evals.utils: now located, and read as judge-free.
        "inspect_evals.aime2025.aime2025:aime_scorer",
        # Its file holds math's judged helper; exact match never calls it.
        "inspect_evals.math.math:expression_exact_match",
    ],
)
def test_real_judge_free_scorers_stay_judge_free(reference: str) -> None:
    """Failing closed must not refuse the judge-free rows that already ship."""

    pytest.importorskip("inspect_evals")

    assert judge_shape(reference) == JudgeShape()
