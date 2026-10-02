"""The selected benchmark's answer rule and the extract='benchmark' resolution (OME-1289 gap, G8).

FEATURE: sf.Vote(extract="benchmark") groups answers the way the benchmark grades them (GP-1).
INVARIANT: resolution runs in compile_evaluation, after the operator catalog load and before any
spend; the url4 pins the rule's concrete operator ids, so it is specific to the rule (GP-D5) and a
replay never looks the rule up again (GP-D6).
WHY the benchmark resource and not GET /v1/benchmarks: the Engine writes answer_rule in
Benchmark._metadata(), which the resource spreads, and every evaluation already fetches that
resource once, so resolution adds no request.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn, cast

from screamingface._core.wire import mapping as _wire_mapping
from screamingface._core.wire import text as _wire_text
from screamingface._evaluation.operators import _OperatorCatalog, is_pinned_operator_id
from screamingface.reducer import _ReducerPlan

type _Invalid = Callable[[str], NoReturn]

_RULE_KEYS = frozenset({"extract", "normalize", "grader"})
_STEP_KEYS = frozenset({"op", "args"})


@dataclass(frozen=True, slots=True)
class _AnswerRule:
    extract: str  # pinned id, e.g. "inspect_number@1"
    normalize: str | None  # pinned id or None
    grader: str  # "<dotted scorer>@<version>", informational in the SDK


@dataclass(frozen=True, slots=True)
class _BenchmarkAnswerRule:
    benchmark_id: str
    rule: _AnswerRule | None


def decode_answer_rule(value: object, invalid: _Invalid) -> _AnswerRule | None:
    """Decode the benchmark resource's optional ``answer_rule`` block; absent means no rule."""

    if value is None:
        return None
    block = _wire_mapping(value, "Benchmark answer_rule", invalid)
    if set(block) != _RULE_KEYS:
        invalid("Benchmark answer_rule must carry exactly extract, normalize, and grader")
    normalize = block["normalize"]
    return _AnswerRule(
        extract=_step_op(block["extract"], "extract", invalid),
        normalize=None if normalize is None else _step_op(normalize, "normalize", invalid),
        grader=_wire_text(block["grader"], "Benchmark answer_rule grader", invalid),
    )


def _step_op(value: object, field: str, invalid: _Invalid) -> str:
    step = _wire_mapping(value, f"Benchmark answer_rule {field}", invalid)
    if set(step) != _STEP_KEYS:
        invalid(f"Benchmark answer_rule {field} must be an object with exactly op and args")
    op = step["op"]
    if not isinstance(op, str) or not is_pinned_operator_id(op):
        invalid(
            f"Benchmark answer_rule {field} op must be a pinned operator id like 'inspect_number@1'"
        )
    if step["args"] != {}:
        invalid(
            f"Benchmark answer_rule {field} args must be an empty object "
            "(v1 rules take no operator args)"
        )
    return cast(str, op)


def resolve_benchmark_rule(
    plan: _ReducerPlan, benchmark: _BenchmarkAnswerRule | None, operators: _OperatorCatalog
) -> _ReducerPlan:
    """Fill a plan's extract and normalize steps from the benchmark's answer rule (GP-1)."""

    if not plan.benchmark_rule:
        return plan
    if benchmark is None:
        raise ValueError(
            "extract='benchmark' needs a benchmark; "
            "evaluate the Candidate with client.evaluate(..., benchmark=...)"
        )
    raise NotImplementedError  # STUB: the rule branches arrive with the evaluation commit


__all__: list[str] = []
