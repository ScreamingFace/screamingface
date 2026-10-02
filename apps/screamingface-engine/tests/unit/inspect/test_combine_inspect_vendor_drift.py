"""The vendored Inspect numeric rule is a byte-identical copy of the installed one (OME-1289).

FEATURE: the engine grades a numeric answer exactly as Inspect does, without importing Inspect.
STORY: as an operator, an Inspect upgrade that changes a grading rule fails this test instead of
silently changing what the combine counts as equal. GP#2.

Runs only with the `inspect` extra installed (`uv run --extra inspect pytest ...`).
"""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import re

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine.combine.operators import _inspect_vendor as vendor  # noqa: E402

_NAMES = [(module, name) for module, names in vendor.VENDORED_NAMES for name in names]


def test_vendored_rule_pins_installed_inspect_versions() -> None:
    assert importlib.metadata.version("inspect-ai") == vendor.INSPECT_AI_VERSION
    assert importlib.metadata.version("inspect-evals") == vendor.INSPECT_EVALS_VERSION


def test_every_vendored_module_is_listed() -> None:
    assert [module for module, _ in vendor.VENDORED_NAMES] == [
        "inspect_ai.scorer._unicode",
        "inspect_ai._util.text",
        "inspect_ai.scorer._common",
        "inspect_evals.utils.aime_common",
    ]
    assert len(_NAMES) == 36


@pytest.mark.parametrize(("module", "name"), _NAMES, ids=[f"{m}.{n}" for m, n in _NAMES])
def test_vendored_definitions_are_byte_identical_to_the_installed_ones(
    module: str, name: str
) -> None:
    ours = getattr(vendor, name)
    theirs = getattr(importlib.import_module(module), name)
    if inspect.isfunction(ours):
        assert inspect.getsource(ours) == inspect.getsource(theirs)
    elif isinstance(ours, re.Pattern):
        assert (ours.pattern, ours.flags) == (theirs.pattern, theirs.flags)
    else:
        assert ours == theirs


@pytest.mark.parametrize("task", ["aime2024", "aime2025"])
def test_the_benchmarks_aime_scorer_is_the_shared_one(task: str) -> None:
    # F17: the attribute `inspect_evals.<task>.<task>` is the task FUNCTION, so import the module.
    aime_common = importlib.import_module("inspect_evals.utils.aime_common")
    module = importlib.import_module(f"inspect_evals.{task}.{task}")
    assert module.aime_scorer is aime_common.aime_scorer
