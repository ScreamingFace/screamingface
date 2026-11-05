"""The SDK declares `logprobs_unsupported` as a failure code (E4b part 3, P13).

Pins LC#10 (SDK half): the SDK mirror of the engine's declared vocabulary carries the code, and a
`Failure` can name it. A separate module (append-only gate).
"""

from __future__ import annotations

from screamingface._report_primitives import (
    DECLARED_FAILURE_CODES,
    Failure,
    is_declared_failure_code,
)


def test_logprobs_unsupported_is_a_declared_sdk_code() -> None:
    assert "logprobs_unsupported" in DECLARED_FAILURE_CODES
    assert is_declared_failure_code("logprobs_unsupported")
    assert Failure(stage="candidate", code="logprobs_unsupported", message="m").code == (
        "logprobs_unsupported"
    )
