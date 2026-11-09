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
from dataclasses import dataclass, replace
from typing import NoReturn

from screamingface._core.wire import mapping as _wire_mapping
from screamingface._core.wire import text as _wire_text
from screamingface._evaluation.operators import Stage, _OperatorCatalog, is_pinned_operator_id
from screamingface.blocks import NAMED_EXTRACT_RULES
from screamingface.errors import EngineCapabilityError
from screamingface.reducer import _ReducerPlan, _Step

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
    return op


def resolve_benchmark_rule(
    plan: _ReducerPlan, benchmark: _BenchmarkAnswerRule | None, operators: _OperatorCatalog
) -> _ReducerPlan:
    """Fill a plan's extract and normalize steps from the benchmark's answer rule (GP-1)."""

    if not plan.benchmark_rule:
        return plan
    if benchmark is None:
        raise ValueError(
            "over='benchmark' needs a benchmark; "
            "evaluate the Candidate with client.evaluate(..., benchmark=...)"
        )
    rule = benchmark.rule
    if rule is None:
        raise ValueError(
            f"benchmark {benchmark.benchmark_id!r} declares no answer rule, so "
            "over='benchmark' cannot be used on it; "
            f"use a named extract rule: {', '.join(NAMED_EXTRACT_RULES)}"
        )
    pairs: tuple[tuple[Stage, str | None], ...] = (
        ("extract", rule.extract),
        ("normalize", rule.normalize),
    )
    for stage, op in pairs:
        if op is not None and not operators.serves(stage, op):
            raise _missing_operator(benchmark.benchmark_id, stage, op)
    steps = replace(
        plan.steps,
        extract=_Step(rule.extract),
        normalize=None if rule.normalize is None else _Step(rule.normalize),
    )
    return replace(plan, steps=steps, benchmark_rule=False)


def _missing_operator(benchmark_id: str, stage: Stage, op: str) -> EngineCapabilityError:
    return EngineCapabilityError(
        f"this SF Engine does not serve {op!r}, the {stage} operator benchmark {benchmark_id!r} "
        "declares for over='benchmark'",
        permanent=True,
        details={"benchmark": benchmark_id, "stage": stage, "operator": op},
        hint=(
            "Use an SF Engine that serves the benchmark's answer operators "
            "(GET /v1/operators), or a named extract rule."
        ),
    )


__all__: list[str] = []
