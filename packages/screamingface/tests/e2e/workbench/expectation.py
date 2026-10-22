"""The expected-failure verdict (e2e workbench spec §3.7; unit 7 plan, Task 1).

A notebook may fail ON PURPOSE (``debug_failing_run``). It declares how in its metadata,
``workbench.expect = {outcome: "fail", failure_codes: [...], stage: ...}``, and passes only when
it failed exactly so and the telemetry caught the error. The verdict also requires what every
notebook needs (no raised cell, a well-formed result, a complete trace chain): ``verdict.py``.

Pure: the declaration, the bundle's ``report.json`` (parsed) and its ``events.jsonl`` text in;
reasons and what was observed out — so every red case is unit-tested without a kernel.

INVARIANT: fail closed. A malformed declaration is red, never ignored; an unreadable report is
missing evidence; a code the notebook did not declare is red, so a changed failure (an SDK or
engine refactor) or a vanished one (a tape re-bless made the model servable) never reads green.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final, get_args

from screamingface._report_primitives import FailureStage, is_declared_failure_code

#: OTel severity number of ERROR; FATAL is 21–24, also an error.
_ERROR_SEVERITY: Final = 17
_STAGES: Final = frozenset(get_args(FailureStage.__value__))
_WHY: Final = "malformed workbench.expect"


@dataclass(frozen=True)
class Expectation:
    failure_codes: tuple[str, ...]
    stage: str

    def to_json(self) -> dict[str, Any]:
        return {"outcome": "fail", "failure_codes": list(self.failure_codes), "stage": self.stage}


def parse_expect(raw: object) -> tuple[Expectation | None, list[str]]:
    """The declaration, or ``None`` and why it is malformed (never raises)."""
    if not isinstance(raw, Mapping):
        return None, [f"{_WHY}: want an object, got {type(raw).__name__}"]
    spec: Mapping[str, Any] = raw  # pyright: ignore[reportUnknownVariableType]
    problems: list[str] = []
    if spec.get("outcome") != "fail":
        problems.append(f"{_WHY}: outcome must be 'fail', got {spec.get('outcome')!r}")
    codes = spec.get("failure_codes")
    if not isinstance(codes, list) or not codes:
        problems.append(f"{_WHY}: failure_codes must be a non-empty list of failure codes")
        codes = []
    for code in codes:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(code, str) or not is_declared_failure_code(code):
            problems.append(f"{_WHY}: {code!r} is not a declared failure code")
    stage = spec.get("stage")
    if stage not in _STAGES:
        problems.append(f"{_WHY}: stage must be one of {sorted(_STAGES)}, got {stage!r}")
    if problems:
        return None, problems
    return Expectation(tuple(codes), str(stage)), []  # pyright: ignore[reportUnknownArgumentType]


def _pair(item: Any) -> Iterator[tuple[str, str]]:
    """One failure dict's ``(code, stage)``, when it has both as text."""
    if isinstance(item, Mapping):
        failure: Mapping[str, Any] = item  # pyright: ignore[reportUnknownVariableType]
        code, stage = failure.get("code"), failure.get("stage")
        if isinstance(code, str) and isinstance(stage, str):
            yield code, stage


def _failures(node: Any) -> Iterator[tuple[str, str]]:
    """Every ``(code, stage)`` in any ``failures`` list of a report.v1 tree: candidate, case,
    attempt and operation alike, so the verdict never depends on where the SDK files one."""
    if isinstance(node, list):
        for item in node:  # pyright: ignore[reportUnknownVariableType]
            yield from _failures(item)
    elif isinstance(node, Mapping):
        mapping: Mapping[str, Any] = node  # pyright: ignore[reportUnknownVariableType]
        for key, value in mapping.items():
            if key == "failures" and isinstance(value, list):
                for item in value:  # pyright: ignore[reportUnknownVariableType]
                    yield from _pair(item)
            else:
                yield from _failures(value)


def is_error_span(event: Mapping[str, Any]) -> bool:
    return event.get("kind") == "span" and (
        event.get("status") == "error" or bool(event.get("refusal"))
    )


def is_error_log(event: Mapping[str, Any]) -> bool:
    severity = event.get("severity_number")
    return (
        event.get("kind") == "log"
        and isinstance(severity, int)
        and not isinstance(severity, bool)
        and severity >= _ERROR_SEVERITY
    )


def error_telemetry(events_text: str) -> dict[str, int]:
    """Failing ``Span`` events and ERROR-or-above ``Log`` events in one run's ``events.jsonl``.

    A torn tail (the kernel died mid-write) or a non-object line is skipped, never fatal.
    """
    spans = logs = 0
    for line in events_text.splitlines():
        try:
            event: Any = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, Mapping):
            spans += is_error_span(event)  # pyright: ignore[reportUnknownArgumentType]
            logs += is_error_log(event)  # pyright: ignore[reportUnknownArgumentType]
    return {"spans": spans, "logs": logs}


def _failure_reasons(expect: Expectation, observed: list[tuple[str, str]]) -> list[str]:
    declared = list(expect.failure_codes)
    if not observed:
        return [
            f"unexpected pass: expected failure code(s) {declared} at stage "
            f"{expect.stage!r}, the report has no failures"
        ]
    codes = sorted({code for code, _ in observed})
    if set(codes) != set(declared):
        return [f"wrong failure code: expected {declared}, observed {codes}"]
    reasons: list[str] = []
    for code in declared:
        stages = sorted({stage for c, stage in observed if c == code})
        if expect.stage not in stages:
            reasons.append(
                f"wrong failure stage for {code!r}: expected {expect.stage!r}, observed {stages}"
            )
    return reasons


def judge_expectation(
    expect: Expectation, report: Mapping[str, Any] | None, events_text: str
) -> tuple[list[str], dict[str, Any]]:
    """(reasons, observed). No reasons means the declared failure happened and was seen.

    ``report`` is the bundle's parsed ``report.json`` (``None`` when absent or unreadable);
    ``events_text`` is its ``events.jsonl``, which holds exactly one run (spec §3.6).
    """
    reasons: list[str] = []
    failures: list[dict[str, str]] | None = None
    if report is None:
        reasons.append("missing evidence: no report.json, so the failure cannot be observed")
    else:
        pairs = sorted(set(_failures(report)))
        failures = [{"code": code, "stage": stage} for code, stage in pairs]
        reasons += _failure_reasons(expect, pairs)
    telemetry = error_telemetry(events_text)
    if not any(telemetry.values()):
        reasons.append(
            "no error telemetry: no Span event with an error status or refusal and no Log "
            "at ERROR or above in events.jsonl"
        )
    return reasons, {"failures": failures, "error_telemetry": telemetry}
