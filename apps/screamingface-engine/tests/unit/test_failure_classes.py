"""The declared failure vocabulary and its class helpers (OME-1234, PR a).

FEATURE: tell the researcher what kind of failure ended their run (OME-1233).
STORY: as a researcher whose paid run died, I read which kind of thing went
wrong — and whether retrying can help — instead of one catch-all word.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.contract import DECLARED_FAILURE_CODES
from screamingface_engine.benchmarks.evaluation import benchmark_unavailable
from screamingface_engine.benchmarks.failure_classes import (
    UPSTREAM_FALLBACK_CODE,
    benchmark_contract_error,
    benchmark_definition_error,
    judge_failure,
)
from url4.core.errors import ResolutionError

# INVARIANT: every code a class helper can produce is on the declared list —
# a helper minting an undeclared code would defeat the whole gate.
HELPERS = (
    benchmark_contract_error,
    benchmark_definition_error,
    judge_failure,
    benchmark_unavailable,
)


@pytest.mark.parametrize("helper", HELPERS)
def test_every_helper_code_is_declared(helper) -> None:
    error: ResolutionError = helper("detail")
    assert error.code in DECLARED_FAILURE_CODES


def test_contract_error_is_permanent() -> None:
    # INVARIANT: a payload that violates the benchmark protocol cannot succeed
    # on retry — the same malformed envelope arrives again.
    error: ResolutionError = benchmark_contract_error("payload must carry exactly round and tie")
    assert error.code == "benchmark_contract_error"
    assert error.permanent is True
    assert str(error) == "payload must carry exactly round and tie"


def test_definition_error_is_permanent() -> None:
    # INVARIANT: a benchmark-author mistake (bad config, impossible selection)
    # is unfixable by the researcher — never advise a retry.
    error: ResolutionError = benchmark_definition_error(
        "selected_case_count cannot exceed available_case_count (4)"
    )
    assert error.code == "benchmark_definition_error"
    assert error.permanent is True


def test_judge_failure_is_retryable_and_uses_the_reconciled_spelling() -> None:
    # INVARIANT: a grader that ran dry can succeed on a re-resolve, so the class
    # is transient — matching the deliberate choice at gdpval/runtime.py and
    # healthbench/runtime.py. The reconciled spelling is judge_reply_invalid
    # (owner decision on OME-1234): one idea, one code.
    error: ResolutionError = judge_failure("the check judge returned no usable verdict")
    assert error.code == "judge_reply_invalid"
    assert error.permanent is False


def test_assets_keep_the_existing_catch_all_code() -> None:
    # INVARIANT (don't-regress, OME-1233): benchmark_unavailable survives for
    # the class it was invented for — genuinely missing/unreadable assets.
    error: ResolutionError = benchmark_unavailable("could not read rubric")
    assert error.code == "benchmark_unavailable"
    assert error.permanent is True


def test_retired_spellings_are_not_declared() -> None:
    # INVARIANT: reconciled-away and hatch codes cannot come back silently.
    assert "no_valid_judge_verdict" not in DECLARED_FAILURE_CODES
    assert "board_owned_code" not in DECLARED_FAILURE_CODES


def test_upstream_fallback_is_declared() -> None:
    # WHY: unknown upstream codes map to this class instead of crashing a paid
    # run mid-flight (owner decision on OME-1234).
    assert UPSTREAM_FALLBACK_CODE == "upstream_error"
    assert UPSTREAM_FALLBACK_CODE in DECLARED_FAILURE_CODES


def test_the_declared_vocabulary_is_exactly_the_agreed_set() -> None:
    # INVARIANT: the list only changes deliberately — an addition or removal
    # must edit this test too, which is the loud-failure the epic asks for.
    assert DECLARED_FAILURE_CODES == frozenset(
        {
            # engine-raised codes grandfathered from main@79ccc46e
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
            # contracteval codes declared by OME-1246 (landed in flight with the
            # OME-1233 close, so they missed the original agreed set)
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
            # upstream pass-through codes observed in reports today
            "resolution_failed",
            "judge_unavailable",
            "asset_unavailable",
            "provider_error",
            "rate_limited",
            "candidate_failed",
            "checker_failed",
            "judge_failed",
            # new classes introduced by OME-1234
            "benchmark_contract_error",
            "benchmark_definition_error",
            "upstream_error",
        }
    )
