"""The deterministic per-Case and per-run steps, mounted as URL4 code (spec R1).

Each factory returns a :data:`url4.CodeHandler` a Benchmark mounts with ``node.code(path)``.
A handler reads the named sources of its expression (``CodeCall.input(name)``) — never an
intent string — and returns the same row the retired endpoints returned, so the aggregate,
the report and every recorded artifact read it unchanged.

STORY: as a Benchmark author I write ``(case, attempt_1)!/…/case-evaluation`` and
``(evaluations, selected)!/…/aggregate``; the Engine owns how a check, a Case grade and the
outcome-preserving envelope compose inside those two calls.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from screamingface_engine.activity_kinds import ActivityKind
from screamingface_engine.benchmarks.case_grading_report import report_case_grading
from screamingface_engine.benchmarks.failure_classes import (
    benchmark_contract_error,
    benchmark_definition_error,
)
from screamingface_engine.benchmarks.graded_answer import (
    CASE_ATTEMPTS_SCHEMA,
    graded_answer_payload,
)
from screamingface_engine.benchmarks.grading_endpoints import (
    AsyncAggregateAdapter,
    CaseGradeBuilder,
    JsonObject,
    benchmark_unavailable,
    compact_json,
    json_object,
    positive_case_id,
    positive_count,
)
from screamingface_engine.benchmarks.phases import observe_phase
from screamingface_engine.benchmarks.protocol import (
    CASE_SOURCE,
    EVALUATIONS_SOURCE,
    SELECTED_SOURCE,
    attempt_number,
)
from url4 import CodeCall, CodeHandler
from url4.dag import collected_error

#: One Benchmark's check: the Case id, one Candidate Invocation, and the Case's other named
#: sources (e.g. MedXpertQA's turn-1 ``reasoning``) → the Benchmark's own check record.
CaseCheck = Callable[[int, str, Mapping[str, object]], JsonObject]


def case_evaluation_code(
    *, label: str, check: CaseCheck, build_case_grade: CaseGradeBuilder, observe_grading: bool
) -> CodeHandler:
    """``(case, attempt_1..N, …)!/…/case-evaluation`` → one Case row.

    For each Attempt: run ``check``, then ``build_case_grade`` over that one record; a failure
    of either becomes that Attempt's ``{"error": …}`` grading outcome in url4's collected-error
    shape. The row is ``case-execution.v1`` for one Attempt and ``case-attempts.v1`` (one
    envelope per Attempt, in order) for more.

    INVARIANT: a grading failure never drops the Candidate's answer — the envelope keeps the
    invocation for re-grading, as the retired protective iterate did.
    """

    return _CaseEvaluation(label, check, build_case_grade, observe_grading)


class _CaseEvaluation:
    __slots__ = ("_check", "_grade", "_label")

    def __init__(
        self,
        label: str,
        check: CaseCheck,
        build_case_grade: CaseGradeBuilder,
        observe_grading: bool,
    ) -> None:
        def grade(case_id: int, record: JsonObject) -> JsonObject:
            try:
                return build_case_grade(case_id, [record])
            except (OSError, TypeError, ValueError) as exc:
                raise benchmark_contract_error(str(exc)) from exc

        self._label = label
        self._check = check
        self._grade = observe_phase(ActivityKind.GRADING)(grade) if observe_grading else grade

    def __call__(self, call: CodeCall) -> str:
        try:
            case = json_object(call.input(CASE_SOURCE).value, f"{self._label} case")
            invocations, others = _split_inputs(call)
        except (KeyError, TypeError, ValueError) as exc:
            raise benchmark_contract_error(f"{self._label}: {exc}") from exc
        envelopes = [self._envelope(case, invocation, others) for invocation in invocations]
        if len(envelopes) == 1:
            return compact_json(envelopes[0])
        return compact_json(
            {
                "schema": CASE_ATTEMPTS_SCHEMA,
                "case_id": _envelope_case_id(case),
                "attempts": envelopes,
            }
        )

    def _envelope(
        self, case: JsonObject, invocation: str, others: Mapping[str, object]
    ) -> JsonObject:
        case_id = _envelope_case_id(case)
        grading: object
        try:
            check_id = _check_case_id(case)
            grading = self._grade(check_id, self._check(check_id, invocation, others))
        except Exception as exc:  # noqa: BLE001 — every grading failure is kept per Attempt.
            # WHY every exception: the retired `iterate(on_error=collect)` caught them all,
            # and a scorer bug must never poison the collected row.
            grading = collected_error(exc)
        try:
            payload = graded_answer_payload(case_id, invocation, [grading])
        except (TypeError, ValueError) as exc:
            raise benchmark_contract_error(f"{self._label}: {exc}") from exc
        failed = isinstance(grading, Mapping) and "error" in grading
        report_case_grading(case_id, "failed" if failed else "completed")
        return payload


def aggregate_code(
    *, label: str, available_case_count: int, aggregate: AsyncAggregateAdapter
) -> CodeHandler:
    """``(evaluations, selected)!/…/aggregate`` → the run report.

    WHY async (OME-1240): a judged Benchmark's adapter awaits model calls through the run's
    shared HTTP client, so the handler must be awaited on the run's own loop — url4 awaits a
    code handler there.
    """

    positive_count(available_case_count, "available_case_count")

    @observe_phase(ActivityKind.AGGREGATION)
    async def handler(call: CodeCall) -> str:
        selected = _selected(call, available_case_count)
        try:
            result = await aggregate(text_input(call, EVALUATIONS_SOURCE), selected)
        except (OSError, ValueError) as exc:
            raise benchmark_unavailable(str(exc)) from exc
        return compact_json(result)

    return handler


def _selected(call: CodeCall, available_case_count: int) -> int:
    """The run's selected Case count, from its ``selected`` source."""

    raw = call.input(SELECTED_SOURCE).value
    try:
        selected = int(raw) if isinstance(raw, str | int) and not isinstance(raw, bool) else 0
        positive_count(selected, "selected_case_count")
    except ValueError as exc:
        raise benchmark_definition_error(str(exc)) from exc
    if selected > available_case_count:
        raise benchmark_definition_error(
            f"selected_case_count cannot exceed available_case_count ({available_case_count})"
        )
    return selected


def text_input(call: CodeCall, name: str) -> str:
    """One named source as text; a structured value is re-encoded as compact JSON."""

    value = call.input(name).value
    return value if isinstance(value, str) else compact_json(value)


def _split_inputs(call: CodeCall) -> tuple[list[str], dict[str, object]]:
    """The Attempt invocations in Attempt order, and every other named source but ``case``."""

    attempts: dict[int, str] = {}
    others: dict[str, object] = {}
    for item in call.inputs:
        if item.name is None or item.name == CASE_SOURCE:
            continue
        number = attempt_number(item.name)
        if number is None:
            others[item.name] = item.value
            continue
        if not isinstance(item.value, str):
            raise TypeError(f"{item.name} must be a Candidate Invocation record")
        attempts[number] = item.value
    if not attempts or sorted(attempts) != list(range(1, len(attempts) + 1)):
        raise ValueError("Attempts must be consecutive attempt_1..attempt_N")
    return [attempts[number] for number in sorted(attempts)], others


def _envelope_case_id(case: JsonObject) -> str:
    """The Case identity the envelope carries: the row's ``id`` as text.

    WHY text: the retired envelope read ``case_id`` from a quoted ``'$item.id'``, so every
    recorded row carries the identity as a string; the aggregate matches it that way.
    """

    value: Any = case.get("id")
    if isinstance(value, bool) or not isinstance(value, int | str) or not str(value).strip():
        raise benchmark_contract_error("the Case row carries no usable id")
    return str(value)


def _check_case_id(case: JsonObject) -> int:
    """The positive integer identity a check reads (the row's ``case_id``, else its ``id``)."""

    return positive_case_id(case.get("case_id", case.get("id")))


__all__ = [
    "CaseCheck",
    "aggregate_code",
    "case_evaluation_code",
    "text_input",
]
