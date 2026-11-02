# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The importer takes HLE's official grading: a scorer beside the Task, a role in an argument.

FEATURE: OME-1478 PR 1 of 2. HLE's paper-faithful set-up (inspect_evals'
``run_configs/original.yaml``, the owner's pick on 2026-10-28) grades with ``json_judge`` and
one o3-mini judge in the ``grader`` role. Two importer rules refused it:

- the scorer lives in ``inspect_evals.hle.scorers``, not in the Task's own module, and the
  importer looked only there and in ``inspect_ai.scorer``;
- the scorer asks ``get_model(role=role)`` inside a helper, with the role arriving from its own
  ``grader_role`` argument, which the reader could not name.

INVARIANT the suite defends: each rule widens only to what is provable. A scorer is found in
its own module only inside the eval's own package; a role is read from the scorer's argument
only when the argument's value is a string, and any role but ``grader`` is still refused.

Stand-ins: none. Every scorer here is HLE's own, built by HLE's own ``scorers_from_spec`` from
the spec written in the installed ``original.yaml``, so a change to that file shows up here.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

import yaml  # noqa: E402
from inspect_ai import Epochs, Task  # noqa: E402
from inspect_ai.dataset import MemoryDataset, Sample  # noqa: E402

from screamingface_engine_inspect.importer import (  # noqa: E402
    ImporterError,
    ScorerFacts,
    _resolve_scorer,
    _scorer_facts,
)

#: HLE's Task module: the module a Task-replay import resolves the row's scorer against.
_HLE_TASK_MODULE: str = "inspect_evals.hle.hle"


def _module(name: str) -> Any:
    """One inspect_evals module by dotted name."""

    return importlib.import_module(name)


def _original_scorer_spec() -> dict[str, Any]:
    """The ``scorer`` task argument exactly as the installed ``original.yaml`` writes it."""

    folder: Path = Path(_module("inspect_evals.hle").__file__).parent
    config: dict[str, Any] = yaml.safe_load(
        (folder / "run_configs" / "original.yaml").read_text(encoding="utf-8")
    )
    return dict(config["task"]["args"]["scorer"])


def _hle_scorers(spec: dict[str, Any]) -> list[Any]:
    """HLE's scorers built by HLE's own spec reader, as its Task builds them."""

    return list(_module("inspect_evals.hle.scorers").scorers_from_spec(spec))


def _hle_task(spec: dict[str, Any]) -> Task:
    """A one-Sample Task with HLE's scorers and HLE's own epoch reducer; nothing is fetched."""

    metrics: Any = _module("inspect_evals.hle.metrics")
    return Task(
        dataset=MemoryDataset([Sample(input="q", target="a")]),
        scorer=_hle_scorers(spec),
        epochs=Epochs(1, metrics.attempt_preserving_mean()),
    )


def test_original_yaml_still_names_one_json_judge_in_the_grader_role() -> None:
    """The premise of this PR, read from the installed file: one judge, the grader role."""

    spec: dict[str, Any] = _original_scorer_spec()

    assert spec["scorer"] == "json_judge"
    assert spec["graders"] == ["grader"]


def test_a_scorer_defined_beside_the_task_module_resolves_to_its_own_module() -> None:
    """``json_judge`` is defined in ``inspect_evals.hle.scorers``; the row must name that
    module, the one grading imports, with the arguments HLE's spec passed."""

    [judge] = _hle_scorers(_original_scorer_spec())

    reference, kwargs, name = _resolve_scorer(judge, _module(_HLE_TASK_MODULE))

    assert reference == "inspect_evals.hle.scorers:json_judge"
    assert name == "json_judge"
    assert kwargs == {"prompt": "json_judge", "grader_role": "grader", "max_grader_attempts": 1}


def test_a_scorer_from_another_evals_package_is_still_refused() -> None:
    """WHY: a row names its own eval's code. Resolving against MMMU's Task module, HLE's
    scorer is outside that eval's package, so the importer refuses as before."""

    [judge] = _hle_scorers(_original_scorer_spec())

    with pytest.raises(ImporterError, match="cannot resolve scorer"):
        _resolve_scorer(judge, _module("inspect_evals.mmmu.mmmu"))


def test_hles_official_grading_passes_the_scorer_checks_with_the_mean_kept() -> None:
    """The whole scorer gate on HLE's real scorer: the judge fills the grader role, and the
    headline is the mean of the "score" leaf under a Named Deviation (HLE's own accuracy
    drops an unreadable judge reply; the mean counts it wrong, as the CAIS leaderboard does)."""

    facts: ScorerFacts = _scorer_facts(
        _hle_task(_original_scorer_spec()), _module(_HLE_TASK_MODULE), "mean"
    )

    assert facts.scorer == "inspect_evals.hle.scorers:json_judge"
    assert facts.judge_role == "grader"
    assert facts.mean_instead_of == "accuracy"


def test_a_role_argument_naming_another_role_is_still_refused() -> None:
    """WHY: a row binds its pinned judge to the one ``grader`` role. default.yaml's backup
    judge, ``grader_2``, would be left unbound, and inspect would grade with the Candidate's
    own model, so a spec asking for it is refused by name."""

    spec: dict[str, Any] = {**_original_scorer_spec(), "graders": ["grader_2"]}

    with pytest.raises(ImporterError, match="'grader_2'"):
        _scorer_facts(_hle_task(spec), _module(_HLE_TASK_MODULE), "mean")
