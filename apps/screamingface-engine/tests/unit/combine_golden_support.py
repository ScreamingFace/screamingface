"""Real-operator test support for the answer operators (OME-1289, E4a, unit 2).

Role: this module serves the REAL plugin operators (``combine/operators``): the golden-fixture
runner, direct stage helpers, and real-operator specs for the built-in registry. Its sibling
``combine_support`` serves the combine CORE with fake operators; the spec, context and run builders
here come from that module (``vote_spec``, ``spec_text``, ``context_text``, ``run``) and are never
copied. Fixture format: ``fixtures/combine/<id>.json`` = ``{"op", "stage", "cases": [{"name",
"input", "args", "expect"}]}``. Decimals are strings. See the unit 2 spec, section 2.6.

The reduce/select fixture rows keep the stage-reading format (``member``, ``status`` "voted" or
"empty"); ``readings_from_rows`` turns each into an ``Answer`` through the core's ``answer_status``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from combine_support import context_text, run, spec_text, vote_spec

from screamingface_engine.combine.builtins import BUILTIN_OPERATORS
from screamingface_engine.combine.operators import extract, normalize, reduce, select
from screamingface_engine.combine.ports import (
    Answer,
    CombineError,
    CombineInput,
    Extractor,
    Normalizer,
    NoVotes,
    OpArgs,
    OperatorDescriptor,
    ReduceOp,
    Reduction,
    Selection,
    SelectOp,
    StageResult,
    TallyRow,
    answer_status,
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


def readings_from_rows(raw: list[dict[str, Any]]) -> tuple[Answer, ...]:
    """Answers from fixture rows in the stage-reading format (the status goes through the core)."""
    answers: list[Answer] = []
    for row in raw:
        status, reason = answer_status(row["status"])
        signals = {k: None if v is None else float(v) for k, v in row.get("signals", {}).items()}
        answers.append(
            Answer(
                member_id=row["member"],
                raw=row.get("raw"),
                value=row["value"],
                status=status,
                reason=reason,
                signals=MappingProxyType(signals),
                weight=None if row["weight"] is None else Decimal(row["weight"]),
            )
        )
    return tuple(answers)


def combine_input(answers: tuple[Answer, ...]) -> CombineInput:
    """A ``CombineInput`` over ``answers`` (outputs are empty strings; no signals)."""
    return CombineInput(answers=answers, outputs={a.member_id: "" for a in answers}, signals={})


def member_readings(
    values: Sequence[str | None],
    weights: Sequence[str | None] | None = None,
    signals: Sequence[dict[str, float | None]] | None = None,
) -> tuple[Answer, ...]:
    """Answers for member_1..member_N: a None value is a failed ``empty`` member, else answered.

    ``signals`` is an optional per-member mapping (the signal the spec reads, if any).
    """
    rows: list[Answer] = []
    for index, value in enumerate(values):
        weight = None if weights is None or weights[index] is None else Decimal(str(weights[index]))
        status, reason = answer_status("voted" if value is not None else "empty")
        own = MappingProxyType({} if signals is None else dict(signals[index]))
        rows.append(Answer(f"member_{index + 1}", value, value, status, reason, own, weight))
    return tuple(rows)


def reduce_result(op_id: str, readings: tuple[Answer, ...]) -> Reduction:
    """Run one reduce operator (no args) over ``readings``."""
    return cast("ReduceOp", find(op_id).run)(combine_input(readings), {})


def select_result(op_id: str, reduction: Reduction, readings: tuple[Answer, ...]) -> Selection:
    """Run one select operator (no args) on ``reduction``."""
    return cast("SelectOp", find(op_id).run)(reduction, combine_input(readings), {})


_TIE_TEXTS = (
    "so the answer is 7.",
    "The total is 9.",
    "roughly 7.0",
    "answer: $9",
    "it fell to \u22123",
    "down to -3.",
    "that is $1,200",
    "no digits at all",
)
_SPREAD_TEXTS = ("I think 10", "12", "maybe 30", "40 ", "no number here")


def _step(op_id: str) -> dict[str, Any]:
    return {"op": op_id, "args": {}}


def builtin_vote_spec(member_count: int) -> dict[str, Any]:
    """A vote over the last number of each member: last_number, numeric, mode, first_holder."""
    return vote_spec(
        member_count,
        extract=_step("last_number@1"),
        normalize=_step("numeric@1"),
        reduce=_step("mode@1"),
        select=_step("first_holder@1"),
    )


def builtin_median_spec(member_count: int, select_op: str = "nearest@1") -> dict[str, Any]:
    """A median over the last number of each member: last_number, numeric, median, ``select_op``."""
    return vote_spec(
        member_count,
        reducer="median",
        extract=_step("last_number@1"),
        normalize=_step("numeric@1"),
        reduce=_step("median@1"),
        select=_step(select_op),
    )


def _bytes_of(spec: dict[str, Any], texts: Sequence[str]) -> str:
    outcome = run(spec_text(spec), context_text(list(texts)), registry=BUILTIN_OPERATORS)
    return outcome.output + "\n" + outcome.evidence.model_dump_json(by_alias=True)


def vote_scenario() -> str:
    """Output and evidence JSON of a vote with three 2-way ties (built-in operators only)."""
    return _bytes_of(builtin_vote_spec(len(_TIE_TEXTS)), _TIE_TEXTS)


def median_scenario() -> str:
    """Output and evidence JSON of a median + nearest with a tie at the minimum distance."""
    return _bytes_of(builtin_median_spec(len(_SPREAD_TEXTS)), _SPREAD_TEXTS)


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
    except NoVotes as exc:
        return {"abstain": exc.reason}
    except CombineError as exc:
        return {"error": exc.code}


__all__ = [
    "FIXTURE_DIR",
    "MODULE_OPERATORS",
    "builtin_median_spec",
    "builtin_vote_spec",
    "combine_input",
    "find",
    "load_fixtures",
    "median_scenario",
    "member_readings",
    "readings_from_rows",
    "reduce_result",
    "run_case",
    "select_result",
    "stage",
    "vote_scenario",
]
