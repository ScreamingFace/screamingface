"""A scorer that is our code joins the Benchmark revision by its source.

What these tests pin, and why: an Imported Benchmark's revision names its Task and its Case
Digest, and leans on the `inspect-ai` / `inspect-evals` version pins for the grading code. A
row that grades with OUR scorer instead (a Named Deviation adopting an inspect_evals fix) has
no such pin, so without this rule an edit to that scorer would change scores under a published
revision with no test failing. A local Task's own scorers already ride its `task_source` pin.

Runs without the `inspect` extra: the rule locates modules, it never imports them.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

import screamingface_engine_inspect.named_deviations as named_deviations
from screamingface_engine_inspect.benchmarks import BENCHMARKS, BenchmarkSpec, grading_references
from screamingface_engine_inspect.local_tasks import scorer_source_pins, source_digest
from screamingface_engine_inspect.prepare import TASK_REPLAY_CASES

#: The rows whose scorer is ours but not their Task's (OME-1701: paws and boolq since PR 1,
#: chembench since PR 2).
_DEVIATING_ROWS: frozenset[str] = frozenset({"paws", "boolq", "chembench"})


def _stand_in_scorer_package(root: Path, name: str) -> Path:
    """A one-module scorer package on disk, standing in for one of ours."""

    package: Path = root / name
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "scorers.py").write_text("def headline():\n    return None\n")
    return package


def test_our_scorer_beside_an_inspect_evals_task_is_pinned_by_its_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package: Path = _stand_in_scorer_package(tmp_path, "stand_in_deviation")
    monkeypatch.syspath_prepend(str(tmp_path))

    pins: tuple[str, ...] = scorer_source_pins(
        "inspect_evals.paws.paws:paws", ("stand_in_deviation.scorers:headline",)
    )

    assert pins == (f"scorer_source={source_digest(package)}",)


def test_an_edit_to_that_scorer_moves_the_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: the grading rule is Benchmark identity; one byte of it is a new revision."""

    package: Path = _stand_in_scorer_package(tmp_path, "stand_in_edited")
    monkeypatch.syspath_prepend(str(tmp_path))
    reference: tuple[str, ...] = ("stand_in_edited.scorers:headline",)
    before: tuple[str, ...] = scorer_source_pins("inspect_evals.paws.paws:paws", reference)

    (package / "scorers.py").write_text("def headline():\n    return 1\n")

    assert scorer_source_pins("inspect_evals.paws.paws:paws", reference) != before


def test_inspects_scorers_and_a_local_tasks_own_scorers_are_not_pinned_again() -> None:
    """inspect's and inspect_evals' scorers ride the package version pins; a local Task's
    scorers sit in the package its `task_source` pin already hashes."""

    assert scorer_source_pins("inspect_evals.paws.paws:paws", ("inspect_ai.scorer:includes",)) == ()
    assert (
        scorer_source_pins(
            "inspect_evals.chembench.chembench:chembench",
            ("inspect_evals.chembench.chembench:chembench_scorer",),
        )
        == ()
    )
    assert (
        scorer_source_pins(
            "screamingface_engine_inspect.local_tasks.bbh.bbh:bbh",
            ("screamingface_engine_inspect.local_tasks.bbh.bbh:bbh_scorer",),
        )
        == ()
    )


def test_two_scorers_from_one_package_give_one_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MATH's headline and its Named Score come from one package: one digest covers both."""

    _stand_in_scorer_package(tmp_path, "stand_in_pair")
    monkeypatch.syspath_prepend(str(tmp_path))

    pins: tuple[str, ...] = scorer_source_pins(
        "inspect_evals.math.math:math",
        ("stand_in_pair.scorers:headline", "stand_in_pair.scorers:headline"),
    )

    assert len(pins) == 1


def test_a_scorer_that_cannot_be_located_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be located"):
        scorer_source_pins("inspect_evals.paws.paws:paws", ("no_such_package.scorers:headline",))


def test_only_the_rows_grading_with_our_scorer_beside_an_inspect_evals_task_carry_the_pin() -> None:
    """INVARIANT: the rule moves no other published revision; every other row's scorer is
    inspect's, inspect_evals' or its own local Task's."""

    pinned: set[str] = {
        spec.key
        for spec in BENCHMARKS
        if scorer_source_pins(TASK_REPLAY_CASES[spec.key].task, grading_references(spec))
    }

    assert pinned == _DEVIATING_ROWS


def test_a_whole_run_metric_of_ours_beside_an_inspect_evals_task_is_pinned_by_its_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: the whole-run metric computes the published number, so when it is our code
    beside an inspect_evals Task, one byte of it is a new revision, as for a scorer of ours."""

    package: Path = _stand_in_scorer_package(tmp_path, "stand_in_metric")
    monkeypatch.syspath_prepend(str(tmp_path))
    # Stand-in: simpleqa is an inspect_evals Task that honours inspect_evals' whole-run
    # metric; swapping in a metric of ours is the case under test. `grading_references` is
    # what assembly hands `scorer_source_pins`.
    simpleqa: BenchmarkSpec = next(spec for spec in BENCHMARKS if spec.key == "simpleqa")
    ours: BenchmarkSpec = replace(simpleqa, whole_run_metric="stand_in_metric.scorers:headline")
    task: str = TASK_REPLAY_CASES["simpleqa"].task

    assert scorer_source_pins(task, grading_references(simpleqa)) == ()
    before: tuple[str, ...] = scorer_source_pins(task, grading_references(ours))
    assert before == (f"scorer_source={source_digest(package)}",)

    (package / "scorers.py").write_text("def headline():\n    return 1\n")

    assert scorer_source_pins(task, grading_references(ours)) != before


def _imported_modules(tree: ast.Module, module_name: str) -> list[str]:
    """Every absolute module name a parsed module imports, relative imports resolved."""

    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                names.append(node.module or "")
                continue
            base: str = module_name.rsplit(".", node.level)[0]
            names.append(f"{base}.{node.module}" if node.module else base)
    return names


def test_a_named_deviation_imports_none_of_our_code_outside_its_own_package() -> None:
    """INVARIANT: the revision hashes a Named Deviation's package only, so that package must be
    the whole marking code: a helper imported from elsewhere in the Engine could change the
    grading under a published revision with no pin moving."""

    root: Path = Path(named_deviations.__file__).parent
    escapes: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative: Path = path.relative_to(root)
        if len(relative.parts) == 1:
            continue  # the namespace's own __init__ grades nothing
        package: str = f"{named_deviations.__name__}.{relative.parts[0]}"
        module_name: str = ".".join((named_deviations.__name__, *relative.with_suffix("").parts))
        tree: ast.Module = ast.parse(path.read_text(encoding="utf-8"))
        escapes.extend(
            f"{relative}: {name}"
            for name in _imported_modules(tree, module_name)
            if name.startswith("screamingface_engine")
            and name != package
            and not name.startswith(f"{package}.")
        )

    assert escapes == []
