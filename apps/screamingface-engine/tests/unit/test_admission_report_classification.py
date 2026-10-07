import httpx
import pytest

from screamingface_engine.benchmarks.aggregation import SelectedCase, grading_failure_case_result
from screamingface_engine.benchmarks.contract import encode_candidate_invocation
from screamingface_engine.benchmarks.grading_endpoints import candidate_answer
from screamingface_engine.world import connector as c
from url4.core.errors import ResolutionError


@pytest.mark.parametrize(
    "status,code",
    [
        (503, "provider_queue_timeout"),
        (504, "provider_execution_timeout"),
        (504, "caller_deadline_exceeded"),
        (None, "aigateway_deadline_exceeded"),
    ],
)
def test_phase_classification_survives_evaluation_report(status, code):
    if status is None:
        error = c._deadline_exceeded(None)
    else:
        with pytest.raises(ResolutionError) as caught:
            c._raise_for_status(
                httpx.Response(
                    status, json={"detail": {"code": code, "message": "Safe timeout message"}}
                )
            )
        error = caught.value
    case = grading_failure_case_result(
        selected_case=SelectedCase(case_id=4, input="question", metadata={}),
        candidate=candidate_answer(encode_candidate_invocation("answer", "stop", None)),
        error={
            "kind": type(error).__name__,
            "code": error.code,
            "message": str(error),
            "permanent": error.permanent,
        },
        method="rubric",
    )
    assert case.failures[0].retryable is True
    assert case.failures[0].code == code
