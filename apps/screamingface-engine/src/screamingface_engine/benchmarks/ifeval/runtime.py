"""Install IFEval's private assets and deterministic functions into one Runner world."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.ensemble.policy import CHECK_SURFACE_SCHEMA
from screamingface_engine.benchmarks.evaluation import (
    aggregate_endpoint,
    candidate_answer,
    compact_json,
    json_object,
)
from screamingface_engine.benchmarks.evaluation import benchmark_unavailable as _unavailable
from screamingface_engine.benchmarks.ifeval import aggregate as scoring
from screamingface_engine.benchmarks.ifeval import grading
from screamingface_engine.benchmarks.ifeval.case_evaluation import bind_case_evaluation
from screamingface_engine.benchmarks.ifeval.definition import (
    AGGREGATE_ROUTE,
    BENCHMARK_ID,
    CASE_COUNT,
    CASE_EVALUATION_ROUTE,
    CASES_ROUTE,
    CHECK_ROUTE,
    CHECK_SURFACE_ROUTE,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


def install(node: Url4Node, root: Path) -> None:
    """Register the canonical IFEval runtime and its check-surface port."""

    if CASES_ROUTE not in getattr(node, "_data", {}):
        node.data(CASES_ROUTE, _cases(root), media_type="application/json")
    routes = frozenset(node.processor_routes())
    endpoints = (
        (CHECK_ROUTE, _check(root)),
        (CHECK_SURFACE_ROUTE, _check_surface(root)),
        (CASE_EVALUATION_ROUTE, _case_evaluation),
        (
            AGGREGATE_ROUTE,
            aggregate_endpoint(
                label="IFEval aggregation",
                available_case_count=CASE_COUNT,
                aggregate=_aggregate(root),
            ),
        ),
    )
    for route, handler in endpoints:
        if route not in routes:
            node.endpoint(route)(handler)


def _cases(root: Path):
    def cases() -> str:
        return _read(root / "cases.json", "IFEval cases")

    return cases


def _check(root: Path):
    """Authoritative per-Case Grading record consumed only by Aggregation."""

    def check(request: Request) -> str:
        try:
            case_id, attempt = _case_and_attempt(request.intent)
            candidate = candidate_answer(request.context)
            spec, result, violations = _verification(root, case_id, candidate.text)
        except (KeyError, TypeError, ValueError) as exc:
            raise _unavailable(str(exc)) from exc
        record = {
            "schema": scoring.SCHEMA,
            "case_id": case_id,
            "attempt": attempt,
            "valid": True,
            "status": candidate.status,
            "answer": candidate.text,
            "refusal": candidate.refusal,
            "finish_reason": candidate.finish_reason,
            "execution": (
                None
                if candidate.execution is None
                else candidate.execution.model_dump(by_alias=True)
            ),
            # INVARIANT: absence stays absence (OME-843) — the key exists only when
            # the Engine attributed named model outputs.
            **(
                {}
                if candidate.operations is None
                else {
                    "operations": [
                        operation.model_dump(by_alias=True) for operation in candidate.operations
                    ]
                }
            ),
            "instruction_id_list": spec["instruction_id_list"],
            "descriptions": grading.describe_instructions(
                instruction_id_list=spec["instruction_id_list"],
                kwargs_list=spec["kwargs"],
                prompt=spec["prompt"],
            ),
            "strict": result["strict"],
            "loose": result["loose"],
            # Violations remain ordinary fields inside the exact Case Evaluation.
            "violations": violations,
        }
        return compact_json(record)

    return check


def _check_surface(root: Path):
    """The advertised check-surface port — IFEval's `deterministic_check` adapter.

    FEATURE: benchmark-independent corrective loop (OME-796).
    Input-addressed by design: a black-box `$candidate` only ever sees `$input`,
    so a mid-run check cannot name a case id — the adapter resolves the case from
    the exact prompt text instead. The returned record is the sealed-envelope
    boundary: it flows inside a client-compiled expression, so it carries ONLY
    the port fields — never instruction ids, kwargs, or the raw grading record.
    """

    def check_surface(request: Request) -> str:
        if request.intent == "feedback":
            return _surface_feedback(request.context)
        if request.intent != "check":
            raise _unsupported("IFEval check surface", request.intent)
        try:
            payload = json_object(request.context, "IFEval check surface")
            if set(payload) != {"input", "invocation"}:
                raise ValueError(
                    "IFEval check surface context must carry exactly input and invocation"
                )
            invocation, answer, result, violations = _surface_verification(
                root,
                payload,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _unavailable(str(exc)) from exc
        strict = result["strict"]
        passed = all(bool(value) for value in strict)
        # WHY satisfaction lives here: the never-pass ranking the loop needs was
        # IFEval-private (`_strict_satisfaction`); the port inverts it — this
        # adapter computes the fraction and the generic gate/select just read it.
        satisfaction = sum(1 for value in strict if value) / len(strict)
        if passed:
            feedback = ""
        else:
            described = " | ".join(str(item) for item in violations) or ("unspecified requirement")
            feedback = f"The answer failed these requirements: {described}"
        record = {
            "schema": CHECK_SURFACE_SCHEMA,
            "passed": passed,
            "satisfaction": satisfaction,
            "feedback": feedback,
            "answer": answer,
            "invocation": invocation,
        }
        return compact_json(record)

    return check_surface


def _surface_verification(
    root: Path,
    payload: dict[str, Any],
) -> tuple[str, str, dict[str, list[bool]], list[str]]:
    prompt = payload["input"]
    invocation = payload["invocation"]
    if not isinstance(prompt, str) or not isinstance(invocation, str):
        raise ValueError("IFEval check surface input and invocation must be text")
    answer = candidate_answer(invocation).text
    case_id = _case_by_input(root, prompt)
    _spec, result, violations = _verification(root, case_id, answer)
    return invocation, answer, result, violations


def _surface_feedback(record_json: object) -> str:
    """Extract the sanitized feedback text from one check-surface record."""

    record = json_object(record_json, "IFEval check-surface feedback")
    if record.get("schema") != CHECK_SURFACE_SCHEMA:
        raise _unavailable(f"feedback input must be a {CHECK_SURFACE_SCHEMA} check-surface record")
    feedback = record.get("feedback")
    if not isinstance(feedback, str):
        raise _unavailable("check-surface record feedback must be text")
    return feedback


def _case_by_input(root: Path, prompt: str) -> int:
    """Resolve the case whose official prompt is exactly `prompt`.

    INVARIANT: cases.json prompts are unique (official IFEval keys join 1:1 to
    prompts), so exact-text resolution is total on real assets; anything else is
    a caller error, bounded as benchmark_unavailable.
    """

    cases = json.loads(_read(root / "cases.json", "IFEval cases"))
    if not isinstance(cases, list):
        raise ValueError("IFEval cases must be a JSON array")
    matches = [
        case.get("id") for case in cases if isinstance(case, dict) and case.get("input") == prompt
    ]
    if not matches:
        raise ValueError("no IFEval case matches the check surface input")
    if len(matches) > 1:
        raise ValueError("the check surface input matches more than one IFEval case")
    return _positive_int(matches[0], "case id")


def _case_evaluation(request: Request) -> str:
    """Pack exact attempt records into one authoritative per-Case envelope."""

    try:
        case_id = _positive_int(request.intent, "case id")
        payload = json_object(request.context, "Case evaluation")
        expected = tuple(f"attempt_{index}" for index in range(1, len(payload) + 1))
        if not expected or tuple(payload) != expected:
            raise ValueError(
                "IFEval Case evaluation fields must be consecutive attempt_1..attempt_N"
            )
        attempts: list[dict[str, Any]] = []
        for field in expected:
            raw = payload[field]
            if not isinstance(raw, str):
                raise ValueError(f"IFEval Case evaluation {field} must be JSON text")
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                raise ValueError(f"IFEval Case evaluation {field} must decode to an object")
            attempts.append(decoded)
        result = bind_case_evaluation(case_id, attempts)
    except (TypeError, ValueError) as exc:
        raise _unavailable(str(exc)) from exc
    return compact_json(result)


def _verification(
    root: Path,
    case_id: int,
    response: str,
) -> tuple[dict[str, Any], dict[str, list[bool]], list[str]]:
    spec = json.loads(
        _read(root / "instructions" / f"{case_id}.json", f"IFEval case {case_id} spec")
    )
    grading.configure_nltk(root / "nltk_data")
    result = grading.check_case(
        instruction_id_list=spec["instruction_id_list"],
        kwargs_list=spec["kwargs"],
        prompt=spec["prompt"],
        response=response,
    )
    violations = grading.describe_failures(
        instruction_id_list=spec["instruction_id_list"],
        kwargs_list=spec["kwargs"],
        prompt=spec["prompt"],
        strict=result["strict"],
    )
    return spec, result, violations


def _aggregate(root: Path):
    def aggregate(case_evaluations: str, selected_case_count: int) -> dict[str, Any]:
        case_order = scoring.load_case_order(root)
        return scoring.aggregate(
            case_evaluations,
            scoring.load_specs(root / "instructions"),
            BENCHMARK_ID,
            case_order,
            selected_case_count=selected_case_count,
        )

    return aggregate


def _case_and_attempt(value: str) -> tuple[int, int]:
    case_part, _, attempt_part = (value or "").partition(":")
    case_id = _positive_int(case_part, "case id")
    attempt = _positive_int(attempt_part, "attempt") if attempt_part else 1
    return case_id, attempt


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError(f"IFEval {label} must be an integer, got {value!r}")
    try:
        selected = int(value)
    except ValueError:
        raise ValueError(f"IFEval {label} must be an integer, got {value!r}") from None
    if selected < 1:
        raise ValueError(f"IFEval {label} must be positive, got {selected}")
    return selected


def _unsupported(label: str, intent: str) -> ResolutionError:
    return ResolutionError(
        f"unsupported {label} operation {intent!r}",
        code="benchmark_operation_unsupported",
        permanent=True,
    )


def _read(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _unavailable(f"could not read {label} at {str(path)!r}: {exc}") from exc


__all__ = ["install"]
