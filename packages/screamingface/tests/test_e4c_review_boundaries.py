"""Boundary cases from the PR #1733 review (E4c, OME-1291, 2026-11-12).

1. The overspend line sums charges as exact decimals, like the Engine fold: 0.1 + 0.2 under a
   0.3 cap is no overspend.
2. The strict Gate decision decoder refuses a number that is not finite (NaN, infinity).
3. A sf.LLMClassifier prompt that holds the template's own "Task:" line replays to itself.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import pytest
from test_e4c_gate_replay import _replayed
from test_e4c_overspend_replay import _gate, _hit
from test_e4c_report import case, record

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.gate_decision import decode_gate_decision
from screamingface._ui.branch_view import overspend_of
from screamingface.budget import CallCharge
from screamingface.errors import ExecutionError

# --- 1. exact decimal overspend -------------------------------------------------------------------


def test_float_drift_is_no_overspend() -> None:
    # sum([0.1, 0.2]) == 0.30000000000000004 > 0.3; the Engine's Decimal(repr(x)) fold says 0.3.
    replay = case(
        1,
        (
            _hit("op_model_1", CallCharge(usd=0.1, tokens=1.0)),
            _hit("op_model_2", CallCharge(usd=0.2, tokens=1.0)),
            _gate(cap=0.3),
        ),
    )
    assert overspend_of(replay) == []


def test_a_real_overspend_still_shows() -> None:
    replay = case(
        1,
        (
            _hit("op_model_1", CallCharge(usd=0.1, tokens=1.0)),
            _hit("op_model_2", CallCharge(usd=0.2, tokens=1.0)),
            _hit("op_model_3", CallCharge(usd=0.0001, tokens=1.0)),
            _gate(cap=0.3),
        ),
    )
    assert overspend_of(replay) == [("usd", 0.3001, 0.3)]


# --- 2. finite numbers in a Gate decision ---------------------------------------------------------


def _budget_record() -> dict[str, Any]:
    value = record(
        "gate_1",
        when={"observe": "budget.remaining:usd", "cmp": ">=", "value": 0.02},
        observed=0.05,
        selectors=[],
    )
    value["budget"] = [
        {
            "unit": "usd",
            "cap": 0.05,
            "spent": 0.0,
            "unpriced": 0,
            "estimate": 0.01,
            "refused": False,
        }
    ]
    return value


def _set(raw: dict[str, Any], path: tuple[Any, ...], number: float) -> dict[str, Any]:
    changed = copy.deepcopy(raw)
    target: Any = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = number
    return changed


def test_the_finite_record_decodes() -> None:
    assert decode_gate_decision(_budget_record(), "op_gate_1 decision") is not None


@pytest.mark.parametrize("number", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize(
    "path",
    [
        ("when", "value"),
        ("observed",),
        ("budget", 0, "cap"),
        ("budget", 0, "spent"),
        ("budget", 0, "estimate"),
    ],
    ids=["when.value", "observed", "cap", "spent", "estimate"],
)
def test_a_number_that_is_not_finite_is_refused(path: tuple[Any, ...], number: float) -> None:
    with pytest.raises(ExecutionError, match="finite"):
        decode_gate_decision(_set(_budget_record(), path, number), "op_gate_1 decision")


# --- 3. an LLMClassifier prompt with the template's Task: line ------------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        "first instruction\nTask:\nsecond instruction",
        "Task:\nonly this",
        "ends with the delimiter\nTask:\n",
    ],
)
def test_a_prompt_holding_the_task_line_replays_to_itself(prompt: str) -> None:
    classifier = sf.LLMClassifier("prov/clf", labels=["easy", "hard"], prompt=prompt)
    recipe = sf.Gate(when=sf.label(classifier) == "hard", then="prov/large", otherwise="prov/small")
    compiled = compile_candidate(recipe)

    replayed = _replayed(compiled.url4)

    assert replayed.operations == compiled.operations
    assert replayed.models == compiled.models
