"""Shared helpers for the sf.Vote / sf.Median evaluation tests (not a test module; OME-1289 gap).

STORY: a researcher evaluates a deterministic reducer through a real ``sf.Client``; these helpers
script the Engine (benchmark resources, operator catalog) and the run transport.
"""

from __future__ import annotations

import copy
from typing import Any

from test_client_run import BENCHMARK


def benchmark_resource(
    benchmark_id: str, *, answer_rule: dict[str, Any] | None = None, case_count: int = 1
) -> dict[str, Any]:
    """``GET /v1/benchmarks/<id>``: the draco fixture under another id, with the rule when given."""

    resource = copy.deepcopy(BENCHMARK)
    resource["id"] = benchmark_id
    resource["case_count"] = case_count
    if answer_rule is not None:
        resource["answer_rule"] = copy.deepcopy(answer_rule)
    return resource
