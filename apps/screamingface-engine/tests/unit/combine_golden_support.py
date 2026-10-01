"""Golden-fixture runner shared by the answer-operator tests (OME-1289, E4a, unit 2).

FEATURE: an operator's behavior is frozen per ``@version`` by a hand-computed fixture file.
Fixture format: ``fixtures/combine/<id>.json`` = ``{"op", "stage", "cases": [{"name", "input",
"args", "expect"}]}``. Decimals are strings. See the unit 2 spec, section 2.6.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from screamingface_engine.combine.operators import extract, normalize, reduce, select
from screamingface_engine.combine.ports import (
    CombineError,
    CombineInput,
    Extractor,
    MemberReading,
    Normalizer,
    OpArgs,
    OperatorDescriptor,
    ReduceOp,
    Reduction,
    Selection,
    SelectOp,
    StageResult,
    TallyRow,
    canonical_decimal,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "combine"
MODULE_OPERATORS: tuple[OperatorDescriptor, ...] = (
    *extract.OPERATORS,
    *normalize.OPERATORS,
    *reduce.OPERATORS,
    *select.OPERATORS,
)
Case = dict[str, Any]


def find(op_id: str) -> OperatorDescriptor:
    """The module-level descriptor for ``op_id`` (the built-in registry is not used here)."""
    return next(d for d in MODULE_OPERATORS if d.id == op_id)


def stage(op_id: str, text: str, args: OpArgs | None = None) -> StageResult:
    """Run one extract or normalize operator on ``text``."""
    return cast("Extractor | Normalizer", find(op_id).run)(text, {} if args is None else args)


def load_fixtures() -> dict[str, dict[str, Any]]:
    """Every fixture file, keyed by operator id."""
    loaded = (json.loads(path.read_text("utf-8")) for path in sorted(FIXTURE_DIR.glob("*.json")))
    return {fixture["op"]: fixture for fixture in loaded}


def _readings(raw: list[dict[str, Any]]) -> tuple[MemberReading, ...]:
    return tuple(
        MemberReading(
            member=row["member"],
            raw=row.get("raw"),
            value=row["value"],
            status=row["status"],
            weight=None if row["weight"] is None else Decimal(row["weight"]),
        )
        for row in raw
    )


def _combine_input(readings: tuple[MemberReading, ...]) -> CombineInput:
    return CombineInput(readings=readings, outputs={r.member: "" for r in readings}, signals={})


def _tally(rows: list[dict[str, Any]] | None) -> tuple[TallyRow, ...] | None:
    if rows is None:
        return None
    return tuple(TallyRow(r["value"], Decimal(r["score"]), tuple(r["holders"])) for r in rows)


def _stage_view(result: StageResult) -> dict[str, Any]:
    return {"status": result.status, "value": result.value}


def _reduction_view(reduction: Reduction) -> dict[str, Any]:
    assert reduction.scores is None
    assert reduction.judge is None
    assert reduction.fields is None
    assert reduction.text is None
    assert reduction.separator_collision is None
    tally = None
    if reduction.tally is not None:
        tally = [
            {"value": r.value, "score": canonical_decimal(r.score), "holders": list(r.holders)}
            for r in reduction.tally
        ]
    statistic = None if reduction.statistic is None else canonical_decimal(reduction.statistic)
    return {"tally": tally, "statistic": statistic}


def _selection_view(selection: Selection) -> dict[str, Any]:
    return {
        "chosen": list(selection.chosen),
        "output": selection.output,
        "tie": selection.tie,
        "agreement": selection.agreement,
    }


def _run(descriptor: OperatorDescriptor, case: Case) -> dict[str, Any]:
    args, given = case["args"], case["input"]
    descriptor.check_args(args)
    if descriptor.stage in ("extract", "normalize"):
        return _stage_view(cast("Extractor | Normalizer", descriptor.run)(given, args))
    readings = _readings(given["readings"])
    if descriptor.stage == "reduce":
        return _reduction_view(cast("ReduceOp", descriptor.run)(_combine_input(readings), args))
    given_reduction = given["reduction"]
    reduction = Reduction(
        tally=_tally(given_reduction["tally"]),
        statistic=None
        if given_reduction["statistic"] is None
        else Decimal(given_reduction["statistic"]),
    )
    select_run = cast("SelectOp", descriptor.run)
    return _selection_view(select_run(reduction, _combine_input(readings), args))


def run_case(descriptor: OperatorDescriptor, case: Case) -> dict[str, Any]:
    """What the operator did for one fixture case, in the fixture's ``expect`` shape."""
    try:
        return _run(descriptor, case)
    except CombineError as exc:
        return {"error": exc.code}


__all__ = ["FIXTURE_DIR", "MODULE_OPERATORS", "find", "load_fixtures", "run_case", "stage"]
