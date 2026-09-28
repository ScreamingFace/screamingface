"""Small immutable values shared by public Report objects."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from screamingface._immutable_json import freeze_mapping, thaw_mapping

type FailureStage = Literal["candidate", "grading", "aggregation"]
type CaseId = int | str

# FEATURE (OME-1235): the declared failure vocabulary — every code a Report Failure
# may carry, mirroring the Engine's list in benchmarks/contract.py. The duplication is
# deliberate (the FailureStage house pattern: an app's internals are never imported);
# a conformance test binds the two copies so a code added on one side and forgotten on
# the other fails loudly. This list IS the reference for report consumers: each code
# names one kind of failure, and `retryable` on the Failure says whether retrying helps.
DECLARED_FAILURE_CODES: frozenset[str] = frozenset(
    {
        # engine-raised codes
        "benchmark_unavailable",
        "benchmark_operation_unsupported",
        "benchmark_retrieval_unavailable",
        "provider_refusal",
        "model_token_cap",
        "model_empty_content",
        "model_parameter_invalid",
        "aigateway_bad_response",
        "aigateway_empty_response",
        "aigateway_transport_error",
        "invalid_candidate_input",
        "web_tool_loop_limit",
        "web_retrieval_invalid",
        "web_retrieval_unavailable",
        "result_too_large",
        "candidate_contract_error",
        "candidate_policy_invalid",
        "candidate_policy_escalation",
        "case_result_missing",
        "case_execution_failed",
        "corrective_role_failed",
        "judge_reply_invalid",
        "invalid_case_evaluation",
        "ifeval_checker_failed",
        "draco_grading_failed",
        "gdpval_grading_failed",
        "healthbench_grading_failed",
        "medxpert_grading_failed",
        "inspect_grading_failed",
        # WHY declared here (OME-1246): contracteval (engine PR #984) landed in flight
        # with the OME-1233 vocabulary close, so its two codes never joined the set —
        # a polarity mismatch then crashed report validation instead of failing the case.
        "contracteval_grading_failed",
        "polarity_mismatch",
        "missing_answer_asset",
        "missing_target_asset",
        # spine failure_messages table codes
        "missing_case_row",
        "missing_rubric_asset",
        "case_error",
        "incomplete_verdicts",
        "no_positive_points",
        "missing_case_rubric",
        "scorer_error",
        "invalid_score_value",
        # fallback defaults
        "grading_dependency_failed",
        "grading_failed",
        # upstream pass-through codes the engine declares verbatim
        "resolution_failed",
        "judge_unavailable",
        "asset_unavailable",
        "provider_error",
        "rate_limited",
        "candidate_failed",
        "checker_failed",
        "judge_failed",
        # classes introduced by OME-1234
        "benchmark_contract_error",
        "benchmark_definition_error",
        "upstream_error",
    }
)
# WHY a pattern beside the set: the engine's connector mints one code per HTTP status
# (`aigateway_http_<status>`) and the number is load-bearing for retry advice — a
# closed family, not an open axis. Kept byte-identical to the engine's pattern.
_AIGATEWAY_HTTP_CODE = re.compile(r"aigateway_http_[1-5][0-9]{2}")


def is_declared_failure_code(code: str) -> bool:
    """Whether a failure code belongs to the declared vocabulary (set or the one family)."""
    return code in DECLARED_FAILURE_CODES or _AIGATEWAY_HTTP_CODE.fullmatch(code) is not None


@dataclass(frozen=True, slots=True, init=False)
class Usage:
    """Observed token and monetary accounting for one execution subtree."""

    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    reasoning_tokens: int | None
    cost_usd: Decimal | None

    def __init__(
        self,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        cache_creation_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        cost_usd: Decimal | str | None = None,
    ) -> None:
        values = {
            "input_tokens": _optional_count(input_tokens, "input_tokens"),
            "output_tokens": _optional_count(output_tokens, "output_tokens"),
            "cache_read_tokens": _optional_count(cache_read_tokens, "cache_read_tokens"),
            "cache_creation_tokens": _optional_count(
                cache_creation_tokens, "cache_creation_tokens"
            ),
            "reasoning_tokens": _optional_count(reasoning_tokens, "reasoning_tokens"),
            "cost_usd": _cost(cost_usd),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, object]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cost_usd": None if self.cost_usd is None else str(self.cost_usd),
        }


@dataclass(frozen=True, slots=True, init=False)
class Failure:
    """One typed domain failure retained inside a valid Report."""

    stage: FailureStage
    code: str
    message: str
    retryable: bool | None
    operation_id: str | None
    case_id: CaseId | None
    metadata: Mapping[str, object]

    def __init__(
        self,
        *,
        stage: FailureStage,
        code: str,
        message: str,
        retryable: bool | None = None,
        operation_id: str | None = None,
        case_id: CaseId | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        if stage not in {"candidate", "grading", "aggregation"}:
            raise ValueError("Failure stage must be 'candidate', 'grading', or 'aggregation'")
        # INVARIANT (OME-1235): an undeclared code cannot enter a Report object — the
        # same refusal the Engine's Failure model makes, so the vocabulary a researcher
        # reads cannot drift one typo at a time.
        validated_code: str = _nonempty_text(code, "Failure code")
        if not is_declared_failure_code(validated_code):
            raise ValueError(f"undeclared failure code {validated_code!r}")
        values = {
            "stage": stage,
            "code": validated_code,
            "message": _nonempty_text(message, "Failure message"),
            "retryable": _optional_retryable(retryable),
            "operation_id": _optional_operation_id(operation_id),
            "case_id": _failure_case_id(case_id),
            "metadata": freeze_mapping(metadata or {}, "Failure metadata"),
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "case_id": self.case_id,
            "metadata": thaw_mapping(self.metadata),
        }
        if self.operation_id is not None:
            value["operation_id"] = self.operation_id
        return value


def _optional_retryable(value: object) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise TypeError("Failure retryable must be a boolean or None")
    return value


def _optional_operation_id(value: object) -> str | None:
    return None if value is None else _nonblank(value, "Failure operation_id")


def _failure_case_id(value: object) -> CaseId | None:
    if value is None:
        return None
    return _case_id(value, "Failure case_id")


def _optional_count(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Usage {label} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"Usage {label} must be a non-negative integer")
    return value


def _cost(value: Decimal | str | None, label: str = "Usage cost_usd") -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal | str):
        raise TypeError(f"{label} must be a decimal string or Decimal")
    try:
        selected = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label} must be a finite non-negative decimal") from exc
    if not selected.is_finite() or selected < 0:
        raise ValueError(f"{label} must be a finite non-negative decimal")
    return selected


def _nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _nonempty_text(value: object, label: str) -> str:
    """Validate min-length text while preserving the exact wire value."""

    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _nonblank_text(value: object, label: str) -> str:
    """Validate visible text while preserving leading and trailing whitespace."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _case_id(value: object, label: str = "Case Result case_id") -> CaseId:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise TypeError(f"{label} must be a non-boolean integer or non-blank string")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{label} must be a non-boolean integer or non-blank string")
    return value


def _duration(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} duration_ms must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{label} duration_ms must be a non-negative integer")
    return value


def _usage(value: object, label: str) -> Usage:
    if not isinstance(value, Usage):
        raise TypeError(f"{label} usage must be an sf.Usage value")
    return value


__all__: list[str] = []
