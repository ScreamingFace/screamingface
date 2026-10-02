"""Shared helpers for the Judge, Pick, Merge, Rank and Concat tests (not a test module; OME-1289).

WHY one file for units 8-10: the SDK tests use this fixture catalog and never a live Engine. The
catalog equals the Engine built-ins (FLOW_OPERATOR_IDS below), so a later unit adds tests and no
edit here.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx

import screamingface as sf
from screamingface._evaluation.operators import _OperatorCatalog, decode_operator_catalog

# (id, stage) sorted by id: EXACTLY the Engine built-ins (`BUILTIN_OPERATORS`), 37 ids. A literal
# on purpose: a drift in the Engine's names must show as a diff here, not be computed away.
FLOW_OPERATOR_IDS: tuple[tuple[str, str], ...] = (
    ("all@1", "select"),
    ("best_holder@1", "select"),
    ("boxed@1", "extract"),
    ("built@1", "select"),
    ("by_field@1", "select"),
    ("by_label@1", "select"),
    ("by_signal@1", "reduce"),
    ("field_rules@1", "reduce"),
    ("filter@1", "reduce"),
    ("first_holder@1", "select"),
    ("identity@1", "normalize"),
    ("inspect_aime@1", "extract"),
    ("inspect_number@1", "extract"),
    ("inspect_numeric@1", "normalize"),
    ("join@1", "reduce"),
    ("json_field@1", "extract"),
    ("json_object@1", "extract"),
    ("kept@1", "select"),
    ("label@1", "reduce"),
    ("last_line@1", "extract"),
    ("last_number@1", "extract"),
    ("max_score@1", "select"),
    ("max_weight_holder@1", "select"),
    ("median@1", "reduce"),
    ("mode@1", "reduce"),
    ("nearest@1", "select"),
    ("numeric@1", "normalize"),
    ("project_field@1", "reduce"),
    ("regex@1", "extract"),
    ("scores@1", "reduce"),
    ("set@1", "normalize"),
    ("text@1", "normalize"),
    ("top_k@1", "select"),
    ("value@1", "select"),
    ("values@1", "reduce"),
    ("weighted_mode@1", "reduce"),
    ("whole@1", "extract"),
)

RUBRIC = "Pick the most correct answer."


def _entry(operator_id: str, stage: str) -> dict[str, object]:
    name, _, version = operator_id.partition("@")
    return {
        "id": operator_id,
        "name": name,
        "version": int(version),
        "stage": stage,
        "args_schema": {},
        "summary": f"{name} v{version}.",
    }


FLOW_OPERATOR_WIRE: dict[str, object] = {
    "object": "list",
    "data": [_entry(operator_id, stage) for operator_id, stage in FLOW_OPERATOR_IDS],
}


def flow_operators() -> _OperatorCatalog:
    return decode_operator_catalog(FLOW_OPERATOR_WIRE)


def flow_operators_response(etag: str = '"v1"', max_age: int = 300) -> httpx.Response:
    return httpx.Response(
        200,
        json=FLOW_OPERATOR_WIRE,
        headers={"ETag": etag, "Cache-Control": f"public, max-age={max_age}, must-revalidate"},
    )


def members3() -> list[str]:
    return ["provider/a", "provider/b", "provider/c"]


def judge_fusion(returns: Literal["label", "scores"] = "label", **kw: Any) -> sf.Fusion:
    """Three members under one judge on ``provider/j``; ``kw`` goes to ``sf.Judge``."""

    options: dict[str, Any] = {"rubric": RUBRIC, **kw}
    return sf.Fusion(members3(), synthesizer=sf.Judge("provider/j", returns=returns, **options))
