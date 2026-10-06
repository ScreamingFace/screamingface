"""The SDK accepts the gateway catch-all code in a Report Failure (OME-939)."""

from __future__ import annotations

from screamingface._report_primitives import Failure, is_declared_failure_code


def test_the_gateway_internal_error_code_is_declared() -> None:
    # WHY: the engine publishes it for a structured aigateway 500 (owner decision
    # 2026-10-02); a consumer refusing it would fail to load a valid report.
    assert is_declared_failure_code("gateway_internal_error")
    failure = Failure(stage="candidate", code="gateway_internal_error", message="m")
    assert failure.code == "gateway_internal_error"
