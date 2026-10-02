"""Fakes and builders for the combine core tests (OME-1289 E4a, unit 1).

Test-only. The core is exercised through these fake operators, never through the built-ins, so a
core test cannot pass or fail because of a real operator's behavior.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from screamingface_engine.combine.endpoint import COMBINE_ROUTE, CombineOutcome, run_combine
from screamingface_engine.combine.ports import (
    CombineInput,
    FieldReading,
    JudgeReading,
    OpArgs,
    OperatorDescriptor,
    Reduction,
    Selection,
    SpecInvalid,
    StageResult,
    TallyRow,
    accepted,
    canonical_json,
    rejected,
)
from screamingface_engine.combine.registry import OperatorRegistry
from screamingface_engine.operation_calls import OperationCall, capture_operation_calls
from screamingface_engine.world.combine import CombineRoute
from url4.peer.server import Request


def fake_last_word(text: str, args: OpArgs, /) -> StageResult:
    words = text.split()
    return accepted(words[-1]) if words else rejected("empty")


def fake_digits(text: str, args: OpArgs, /) -> StageResult:
    """The last run of digits, else ``empty``."""
    runs = re.findall(r"[0-9]+", text)
    return accepted(runs[-1]) if runs else rejected("empty")


def fake_bad_stage(text: str, args: OpArgs, /) -> Any:
    """A plugin bug: "voted" with no value (a duck-typed object skips StageResult's own check)."""
    return SimpleNamespace(value=None, status="voted")


def fake_abstain_stage(text: str, args: OpArgs, /) -> Any:
    """A plugin bug: a member reading is never "abstain" (I-A3)."""
    return SimpleNamespace(value=None, status="abstain")


def fake_lower(raw: str, args: OpArgs, /) -> StageResult:
    return accepted(raw.casefold())


def fake_count(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    groups: dict[str, list[str]] = {}
    for answer in combine_input.voters:
        assert answer.value is not None
        groups.setdefault(answer.value, []).append(answer.member_id)
    rows = [
        TallyRow(value, Decimal(len(holders)), tuple(holders)) for value, holders in groups.items()
    ]
    rows.sort(key=lambda row: -row.score)
    return Reduction(tally=tuple(rows))


def fake_first(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    assert reduction.tally
    rows = reduction.tally
    top = rows[0]
    total = sum(row.score for row in rows)
    return Selection(
        chosen=(top.holders[0],),
        tie=len(rows) > 1 and rows[1].score == top.score,
        agreement=float(top.score / total),
    )


def fake_constant(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    return Selection(chosen=(), output="BUILT")


def fake_huge(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    return Selection(chosen=(), output="x" * (8 * 1024 * 1024 + 1))


def fake_bad(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    return Selection(chosen=("member_9",))


def fake_boom(reduction: Reduction, combine_input: CombineInput, args: OpArgs, /) -> Selection:
    raise ZeroDivisionError("boom")


def fake_weighted(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    """Like fake_count, but each vote scores the member's weight."""
    groups: dict[str, list[tuple[str, Decimal]]] = {}
    for answer in combine_input.voters:
        if answer.value is None or answer.weight is None:
            raise SpecInvalid("fake_weighted@1 needs weights")
        groups.setdefault(answer.value, []).append((answer.member_id, answer.weight))
    rows = [
        TallyRow(value, sum((weight for _, weight in held), Decimal(0)), tuple(m for m, _ in held))
        for value, held in groups.items()
    ]
    rows.sort(key=lambda row: -row.score)
    return Reduction(tally=tuple(rows))


def _all_parts(judge: JudgeReading) -> Reduction:
    """A Reduction with every part but the tally filled (the tally excludes the judge parts)."""
    return Reduction(
        statistic=Decimal("2.50"),
        scores={"member_1": Decimal("0.2"), "member_2": Decimal("0.8")},
        judge=judge,
        fields=(
            FieldReading(
                "title",
                "first_voter",
                {"member_1": "A", "member_2": None},
                {"k": [1, 2.5, True, None]},
            ),
        ),
        text="TEXT",
        separator_collision=True,
    )


def fake_all_parts(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    return _all_parts(JudgeReading("member_2 wins", "label", "member_2"))


def fake_all_parts_scores(combine_input: CombineInput, args: OpArgs, /) -> Reduction:
    return _all_parts(JudgeReading("0.2,0.8", "scores", {"member_1": 0.2, "member_2": 0.8}))


def fake_built_many(
    reduction: Reduction, combine_input: CombineInput, args: OpArgs, /
) -> Selection:
    """Builds the reduction's text from two chosen members."""
    return Selection(
        chosen=("member_1", "member_3"), output=reduction.text, tie=True, agreement=0.5
    )


def _check_sep_args(args: OpArgs) -> None:
    if set(args) != {"sep"} or not isinstance(args["sep"], str):
        raise SpecInvalid("expected exactly one string arg named sep")


def fake_args(text: str, args: OpArgs, /) -> StageResult:
    return accepted(str(args["sep"]))


FAKE_REGISTRY = OperatorRegistry(
    (
        OperatorDescriptor("fake_last_word", 1, "extract", "Last word.", fake_last_word),
        OperatorDescriptor("fake_digits", 1, "extract", "Last digit run.", fake_digits),
        OperatorDescriptor("fake_bad_stage", 1, "extract", "Voted, no value.", fake_bad_stage),
        OperatorDescriptor(
            "fake_abstain_stage", 1, "extract", "Abstain status.", fake_abstain_stage
        ),
        OperatorDescriptor("fake_lower", 1, "normalize", "Casefold.", fake_lower),
        OperatorDescriptor("fake_count", 1, "reduce", "One vote each.", fake_count),
        OperatorDescriptor("fake_weighted", 1, "reduce", "One weight each.", fake_weighted),
        OperatorDescriptor("fake_all_parts", 1, "reduce", "Fills every part.", fake_all_parts),
        OperatorDescriptor(
            "fake_all_parts_scores", 1, "reduce", "Fills every part, scores.", fake_all_parts_scores
        ),
        OperatorDescriptor("fake_first", 1, "select", "First holder.", fake_first),
        OperatorDescriptor("fake_built_many", 1, "select", "Builds from two.", fake_built_many),
        OperatorDescriptor("fake_boom", 1, "select", "Raises.", fake_boom),
        OperatorDescriptor("fake_constant", 1, "select", "Builds BUILT.", fake_constant),
        OperatorDescriptor("fake_huge", 1, "select", "Builds 8 MiB + 1.", fake_huge),
        OperatorDescriptor("fake_bad", 1, "select", "Chooses a stranger.", fake_bad),
        OperatorDescriptor(
            "fake_args", 1, "extract", "Returns its sep arg.", fake_args, check_args=_check_sep_args
        ),
    )
)


def vote_spec(member_count: int = 3, **overrides: Any) -> dict[str, Any]:
    """A valid vote spec over ``member_1`` .. ``member_N`` using the fake operators."""
    spec: dict[str, Any] = {
        "schema": "screamingface.combine-spec.v1",
        "reducer": "vote",
        "members": [f"member_{index}" for index in range(1, member_count + 1)],
        "extract": {"op": "fake_last_word@1", "args": {}},
        "normalize": {"op": "fake_lower@1", "args": {}},
        "reduce": {"op": "fake_count@1", "args": {}},
        "select": {"op": "fake_first@1", "args": {}},
        "weights": None,
    }
    spec.update(overrides)
    return spec


def spec_text(spec: Mapping[str, Any]) -> str:
    return canonical_json(spec)


def context_text(outputs: Sequence[str], signals: Mapping[str, str] | None = None) -> str:
    body: dict[str, Any] = {
        "input": "q",
        "outputs": {f"member_{index}": text for index, text in enumerate(outputs, start=1)},
    }
    if signals is not None:
        body["signals"] = dict(signals)
    return json.dumps(body)


def request(intent: str, context: str, params: Mapping[str, str] | None = None) -> Request:
    return Request(
        path=COMBINE_ROUTE,
        context=context,
        intent=intent,
        params={"binding": "synthesis_1"} if params is None else params,
    )


def run(
    intent: str,
    context: str,
    *,
    registry: OperatorRegistry = FAKE_REGISTRY,
    params: Mapping[str, str] | None = None,
) -> CombineOutcome:
    """Run the pure combine core (no url4, no recording)."""
    binding = {"binding": "synthesis_1"} if params is None else params
    return run_combine(registry, binding, context, intent)


def run_recorded(
    intent: str,
    context: str,
    *,
    registry: OperatorRegistry = FAKE_REGISTRY,
    params: Mapping[str, str] | None = None,
) -> tuple[str, list[OperationCall]]:
    """Run the url4 route handler in a capture scope; returns the output and the recorded calls."""
    with capture_operation_calls() as calls:
        output = CombineRoute(registry)(request(intent, context, params))
    return output, list(calls)
