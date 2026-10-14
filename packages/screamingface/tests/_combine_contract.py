"""Shared helpers for the engine combine contract tests (not a test module; OME-1289)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from _reducer_fixtures import ENGINE_OPERATOR_IDS
from _reducer_fixtures import engine_operators as engine_operators  # re-exported for the tests

from screamingface._evaluation.answer_rule import _AnswerRule
from screamingface._evaluation.operators import STAGES

# parents[3] = the monorepo root (tests → screamingface → packages → root)
REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_APP = REPO_ROOT / "apps" / "screamingface-engine"
COMBINE_CONTRACT = ENGINE_APP / "tests" / "unit" / "data" / "combine_contract"
ENGINE_GOLDEN_DIR = ENGINE_APP / "tests" / "unit" / "fixtures" / "combine"

# The names the Engine registers today (stage -> names, all at version 1), derived from the one
# list the reducer tests share. The Engine may register more; see the subset check in
# test_vote_median_contract_fixtures.
ENGINE_OPERATOR_NAMES: dict[str, tuple[str, ...]] = {
    stage: tuple(
        sorted(
            op_id.split("@")[0]
            for op_id, op_stage in ENGINE_OPERATOR_IDS.items()
            if op_stage == stage
        )
    )
    for stage in STAGES
}

# The catalog of an Engine that predates the Inspect answer rules (units 1-2 only): GP#12.
PRE_INSPECT_OPERATOR_NAMES: dict[str, tuple[str, ...]] = {
    "extract": ("boxed", "json_field", "last_line", "last_number", "whole"),
    "normalize": ("identity", "numeric", "text"),
    "reduce": ("median", "mode", "weighted_mode"),
    "select": ("first_holder", "max_weight_holder", "nearest", "value"),
}

# The answer_rule blocks the Engine writes in Benchmark._metadata() (unit 3).
GSM8K_RULE_WIRE: dict[str, Any] = {
    "extract": {"op": "inspect_number@1", "args": {}},
    "normalize": {"op": "inspect_numeric@1", "args": {}},
    "grader": "inspect_ai.scorer:match(numeric=True)@0.3.263",
}
AIME24_RULE_WIRE: dict[str, Any] = {
    "extract": {"op": "inspect_aime@1", "args": {}},
    "normalize": {"op": "inspect_numeric@1", "args": {}},
    "grader": "inspect_evals.aime2024.aime2024:aime_scorer@0.20.0",
}
AIME25_RULE_WIRE: dict[str, Any] = {
    "extract": {"op": "inspect_aime@1", "args": {}},
    "normalize": {"op": "inspect_numeric@1", "args": {}},
    "grader": "inspect_evals.aime2025.aime2025:aime_scorer@0.20.0",
}


def rule(wire: Mapping[str, Any]) -> _AnswerRule:
    """The domain value a benchmark resource's ``answer_rule`` block decodes to."""

    normalize = wire["normalize"]
    return _AnswerRule(
        extract=wire["extract"]["op"],
        normalize=None if normalize is None else normalize["op"],
        grader=wire["grader"],
    )


requires_engine_app = pytest.mark.skipif(
    not ENGINE_APP.exists(), reason="engine app not present (installed run)"
)


def operators_wire(names: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """The ``GET /v1/operators`` body for these stage -> names (all version 1)."""

    return {
        "object": "list",
        "data": [
            {
                "id": f"{name}@1",
                "name": name,
                "version": 1,
                "stage": stage,
                "args_schema": {},
                "summary": f"{name}.",
            }
            for stage, stage_names in names.items()
            for name in stage_names
        ],
    }


def read_contract(name: str) -> str:
    # WHY removesuffix: the repo's end-of-file-fixer hook appends one newline to data files.
    return (COMBINE_CONTRACT / name).read_text(encoding="utf-8").removesuffix("\n")
