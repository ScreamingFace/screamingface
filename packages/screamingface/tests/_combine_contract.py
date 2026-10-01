"""Shared helpers for the engine combine contract tests (not a test module; OME-1289)."""

from __future__ import annotations

from pathlib import Path

import pytest

from screamingface._evaluation.operators import _OperatorCatalog, decode_operator_catalog

# parents[3] = the monorepo root (tests → screamingface → packages → root)
REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_APP = REPO_ROOT / "apps" / "screamingface-engine"
COMBINE_CONTRACT = ENGINE_APP / "tests" / "unit" / "data" / "combine_contract"
ENGINE_GOLDEN_DIR = ENGINE_APP / "tests" / "unit" / "fixtures" / "combine"

# The names the Engine registers today, all at version 1. The Engine may register more; see the
# subset check in test_vote_median_contract_fixtures.
ENGINE_OPERATOR_NAMES: dict[str, tuple[str, ...]] = {
    "extract": ("boxed", "json_field", "last_line", "last_number", "whole"),
    "normalize": ("identity", "numeric", "text"),
    "reduce": ("median", "mode", "weighted_mode"),
    "select": ("first_holder", "max_weight_holder", "nearest", "value"),
}

requires_engine_app = pytest.mark.skipif(
    not ENGINE_APP.exists(), reason="engine app not present (installed run)"
)


def engine_operators() -> _OperatorCatalog:
    return decode_operator_catalog(
        {
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
                for stage, names in ENGINE_OPERATOR_NAMES.items()
                for name in names
            ],
        }
    )


def read_contract(name: str) -> str:
    # WHY removesuffix: the repo's end-of-file-fixer hook appends one newline to data files.
    return (COMBINE_CONTRACT / name).read_text(encoding="utf-8").removesuffix("\n")
