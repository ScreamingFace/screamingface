"""Golden-fixture support for the combine operators with signals, scores and fields (OME-1289 E4a).

Role: units 8 to 10 keep their operators' golden fixtures in ``fixtures/combine/flow/``. The unit 2
harness (``combine_golden_support.load_fixtures``) globs only the top level, so this module runs
the flow folder. Later units add fixture files only. Fixture format: the unit 2 format
``{"op", "stage", "cases": [{"name", "args", "input", "expect"}]}`` for reduce and select only.

- ``input.readings``: rows in the unit 2 shape ``{"member", "raw", "value", "status", "weight"}``.
- ``input.outputs``: optional ``{member: text}``; the default is ``""`` for each reading.
- ``input.signals``: optional ``{name: text}``.
- ``input.reduction`` (select only): optional keys ``tally``, ``statistic``, ``scores``
  (``{member: "decimal"}``), ``judge`` (``{"raw", "returns", "parsed"}``), ``fields`` (a list of
  ``{"field", "rule", "values", "result"}``), ``text``, ``separator_collision``.
- reduce ``expect`` holds ONLY the non-None Reduction parts, decimals as strings
  (``canonical_decimal``); an empty Reduction is ``{}``. Select ``expect`` is
  ``{"chosen", "output", "tie", "agreement"}``. Any ``CombineError`` gives ``{"error": code}``; a
  ``NoVotes`` (an abstain) gives ``{"abstain": reason}``, the same shape as unit 2's ``run_case``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from combine_golden_support import readings_from_rows
from combine_support import vote_spec

from screamingface_engine.combine.builtins import BUILTIN_REGISTRATIONS
from screamingface_engine.combine.ports import (
    CombineError,
    CombineInput,
    FieldReading,
    JudgeReading,
    NoVotes,
    OperatorDescriptor,
    ReduceOp,
    Reduction,
    Selection,
    SelectOp,
    TallyRow,
    canonical_decimal,
)

FLOW_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "combine" / "flow"
Case = dict[str, Any]


def find_builtin(op_id: str) -> OperatorDescriptor:
    """The built-in descriptor for ``op_id``."""
    for descriptor in BUILTIN_REGISTRATIONS:
        if descriptor.id == op_id:
            return descriptor
    raise LookupError(f"no built-in combine operator {op_id!r}")


def load_flow_fixtures() -> dict[str, dict[str, Any]]:
    """Every flow fixture file, keyed by operator id."""
    loaded = (
        json.loads(path.read_text("utf-8")) for path in sorted(FLOW_FIXTURE_DIR.glob("*.json"))
    )
    return {fixture["op"]: fixture for fixture in loaded}


def flow_input(given: Mapping[str, Any]) -> CombineInput:
    """The ``CombineInput`` of one case: readings, optional outputs and optional signals."""
    answers = readings_from_rows(given["readings"])
    outputs = given.get("outputs", {answer.member_id: "" for answer in answers})
    return CombineInput(
        answers=answers,
        outputs=MappingProxyType(dict(outputs)),
        signals=MappingProxyType(dict(given.get("signals", {}))),
    )


def _judge(raw: Mapping[str, Any] | None) -> JudgeReading | None:
    if raw is None:
        return None
    parsed = raw["parsed"]
    return JudgeReading(
        raw["raw"],
        raw["returns"],
        parsed if isinstance(parsed, str) else MappingProxyType(dict(parsed)),
    )


def flow_reduction(given: Mapping[str, Any]) -> Reduction:
    """The ``Reduction`` a select case starts from (``input.reduction``; every key optional)."""
    tally = given.get("tally")
    statistic = given.get("statistic")
    scores = given.get("scores")
    fields = given.get("fields")
    return Reduction(
        tally=None
        if tally is None
        else tuple(TallyRow(r["value"], Decimal(r["score"]), tuple(r["holders"])) for r in tally),
        statistic=None if statistic is None else Decimal(statistic),
        scores=None
        if scores is None
        else MappingProxyType({m: Decimal(score) for m, score in scores.items()}),
        judge=_judge(given.get("judge")),
        fields=None
        if fields is None
        else tuple(FieldReading(f["field"], f["rule"], f["values"], f["result"]) for f in fields),
        text=given.get("text"),
        separator_collision=given.get("separator_collision"),
    )


def reduction_view(reduction: Reduction) -> dict[str, Any]:
    """Only the non-None parts of ``reduction``, in the fixture's ``expect`` shape."""
    view: dict[str, Any] = {}
    if reduction.tally is not None:
        view["tally"] = [
            {"value": r.value, "score": canonical_decimal(r.score), "holders": list(r.holders)}
            for r in reduction.tally
        ]
    if reduction.statistic is not None:
        view["statistic"] = canonical_decimal(reduction.statistic)
    if reduction.scores is not None:
        view["scores"] = {m: canonical_decimal(s) for m, s in reduction.scores.items()}
    if reduction.judge is not None:
        parsed = reduction.judge.parsed
        view["judge"] = {
            "raw": reduction.judge.raw,
            "returns": reduction.judge.returns,
            "parsed": parsed if isinstance(parsed, str) else dict(parsed),
        }
    if reduction.fields is not None:
        view["fields"] = [
            {"field": f.field, "rule": f.rule, "values": dict(f.values), "result": f.result}
            for f in reduction.fields
        ]
    if reduction.text is not None:
        view["text"] = reduction.text
    if reduction.separator_collision is not None:
        view["separator_collision"] = reduction.separator_collision
    return view


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
    combine_input = flow_input(given)
    if descriptor.stage == "reduce":
        return reduction_view(cast("ReduceOp", descriptor.run)(combine_input, args))
    assert descriptor.stage == "select", descriptor.stage
    reduction = flow_reduction(given.get("reduction", {}))
    return _selection_view(cast("SelectOp", descriptor.run)(reduction, combine_input, args))


def run_flow_case(descriptor: OperatorDescriptor, case: Case) -> dict[str, Any]:
    """What the operator did for one fixture case, in the fixture's ``expect`` shape."""
    try:
        return _run(descriptor, case)
    except NoVotes as exc:
        return {"abstain": exc.reason}
    except CombineError as exc:
        return {"error": exc.code}


def judge_spec(
    member_count: int,
    returns: Literal["label", "scores"],
    *,
    reducer: str = "judge",
    select_op: str | None = None,
    select_args: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A judge spec over the built-in operators; the judge text arrives as the ``judge`` signal.

    ``reducer`` and ``select_op`` (with ``select_args``) let a sibling reducer that reads a judge
    reply (for example rank by judge) reuse the same reduce step and signals.
    """
    if returns == "label":
        reduce_step = {"op": "label@1", "args": {}}
        select_step = {"op": "by_label@1", "args": {}}
    else:
        reduce_step = {"op": "scores@1", "args": {"source": "judge"}}
        select_step = {"op": "max_score@1", "args": {}}
    if select_op is not None:
        select_step = {"op": select_op, "args": dict(select_args or {})}
    return vote_spec(
        member_count,
        reducer=reducer,
        extract=None,
        normalize=None,
        reduce=reduce_step,
        select=select_step,
    )
