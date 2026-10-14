"""The judge-shape reader: how a scorer reaches a judge its kwargs never name (OME-1602, F2).

INVARIANT: the reader reads source and never imports it. Every stand-in package below raises
on import, so a test that reads it also proves nothing was executed. The stand-ins are laid
out like inspect_evals (``<root>.<eval>.<module>``), because a scorer's helpers are followed
only inside its own eval package. They prove the reader's rules, not any real eval's scorer.

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

#: A second eval whose helper asks the grader role: never followed from the quiz package.
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


def test_a_helper_from_another_package_is_never_followed(stand_in_evals: str) -> None:
    """Only the eval's own package is read: a helper from elsewhere (inspect_ai's own code,
    above all) is never parsed."""

    assert judge_shape(f"{stand_in_evals}.task:through_another_eval") == JudgeShape()


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


def test_a_scorer_whose_source_cannot_be_found_has_an_empty_shape() -> None:
    assert judge_shape("no_such_eval_package.scorer:anything") == JudgeShape()


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
