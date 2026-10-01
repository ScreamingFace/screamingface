"""Golden-fixture runner shared by the answer-operator tests (OME-1289, E4a, unit 2).

FEATURE: an operator's behavior is frozen per ``@version`` by a hand-computed fixture file.
Fixture format: ``fixtures/combine/<id>.json`` = ``{"op", "stage", "cases": [{"name", "input",
"args", "expect"}]}``. Decimals are strings. See the unit 2 spec, section 2.6.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
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
    ReadingStatus,
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
    for descriptor in MODULE_OPERATORS:
        if descriptor.id == op_id:
            return descriptor
    raise LookupError(f"no plugin module lists the combine operator {op_id!r}")


def stage(op_id: str, text: str, args: OpArgs | None = None) -> StageResult:
    """Run one extract or normalize operator on ``text``."""
    return cast("Extractor | Normalizer", find(op_id).run)(text, {} if args is None else args)


def load_fixtures() -> dict[str, dict[str, Any]]:
    """Every fixture file, keyed by operator id."""
    loaded = (json.loads(path.read_text("utf-8")) for path in sorted(FIXTURE_DIR.glob("*.json")))
    return {fixture["op"]: fixture for fixture in loaded}


def readings_from_rows(raw: list[dict[str, Any]]) -> tuple[MemberReading, ...]:
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


def combine_input(readings: tuple[MemberReading, ...]) -> CombineInput:
    """A ``CombineInput`` over ``readings`` (outputs are empty strings; no signals)."""
    return CombineInput(readings=readings, outputs={r.member: "" for r in readings}, signals={})


def member_readings(
    values: Sequence[str | None], weights: Sequence[str | None] | None = None
) -> tuple[MemberReading, ...]:
    """Readings for member_1..member_N: a None value is an ``empty`` member, otherwise voted."""
    rows: list[MemberReading] = []
    for index, value in enumerate(values):
        weight = None if weights is None or weights[index] is None else Decimal(str(weights[index]))
        status: ReadingStatus = "voted" if value is not None else "empty"
        rows.append(MemberReading(f"member_{index + 1}", value, value, status, weight))
    return tuple(rows)


def reduce_result(op_id: str, readings: tuple[MemberReading, ...]) -> Reduction:
    """Run one reduce operator (no args) over ``readings``."""
    return cast("ReduceOp", find(op_id).run)(combine_input(readings), {})


def select_result(
    op_id: str, reduction: Reduction, readings: tuple[MemberReading, ...]
) -> Selection:
    """Run one select operator (no args) on ``reduction``."""
    return cast("SelectOp", find(op_id).run)(reduction, combine_input(readings), {})


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
    readings = readings_from_rows(given["readings"])
    if descriptor.stage == "reduce":
        return _reduction_view(cast("ReduceOp", descriptor.run)(combine_input(readings), args))
    given_reduction = given["reduction"]
    reduction = Reduction(
        tally=_tally(given_reduction["tally"]),
        statistic=None
        if given_reduction["statistic"] is None
        else Decimal(given_reduction["statistic"]),
    )
    select_run = cast("SelectOp", descriptor.run)
    return _selection_view(select_run(reduction, combine_input(readings), args))


def run_case(descriptor: OperatorDescriptor, case: Case) -> dict[str, Any]:
    """What the operator did for one fixture case, in the fixture's ``expect`` shape."""
    try:
        return _run(descriptor, case)
    except CombineError as exc:
        return {"error": exc.code}


__all__ = [
    "FIXTURE_DIR",
    "MODULE_OPERATORS",
    "combine_input",
    "find",
    "load_fixtures",
    "member_readings",
    "readings_from_rows",
    "reduce_result",
    "run_case",
    "select_result",
    "stage",
]
