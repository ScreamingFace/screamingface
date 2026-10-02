"""A gateway catch-all 500 keeps a gateway-attributed, retryable code in reports (OME-939).

FEATURE: aigateway answers an unhandled route exception with a structured 500 whose
`detail.code` is `gateway_internal_error` (owner decision 2026-10-02). Before, a bare-text
500 became `aigateway_http_500`; a plain `internal_error` would have read as an ENGINE fault
(url4's default) and folded into `upstream_error` in reports, losing the retry advice.
"""

from __future__ import annotations

import pytest
from test_aigateway_connector import _MockAigateway

from screamingface_engine.benchmarks.aggregation import public_error
from screamingface_engine.benchmarks.contract import Failure, is_declared_failure_code
from screamingface_engine.error_text import ENGINE_RESERVED_CODES
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run

_CODE = "gateway_internal_error"
_MODEL = "anthropic/claude-haiku-4-5"


@pytest.mark.asyncio
async def test_a_gateway_500_keeps_its_code_and_stays_retryable() -> None:
    gw = _MockAigateway(
        (_MODEL,),
        responses={
            _MODEL: (500, {"code": _CODE, "message": "The gateway hit an unexpected error."})
        },
    )
    cfg = AigatewayConfig(models=gw.models, default_model=_MODEL)
    async with gw.client() as client:
        world = await build_aigateway_world(cfg, client=client)
        with pytest.raises(ResolutionError) as exc_info:
            await url4_run(f"/{_MODEL}(ctx)!go", io=world.node)

    assert exc_info.value.code == _CODE
    assert exc_info.value.permanent is False


def test_the_code_is_not_engine_reserved() -> None:
    # INVARIANT: the gateway legitimately mints it, so the connector must pass it through.
    assert _CODE not in ENGINE_RESERVED_CODES


def test_a_report_keeps_the_gateway_code_and_its_retry_advice() -> None:
    error = public_error(
        {"kind": "ResolutionError", "code": _CODE, "message": "gateway fault", "permanent": False},
        default_code="case_execution_failed",
        default_message="Candidate Case execution failed",
    )

    assert error.code == _CODE
    assert error.code not in {"upstream_error", "internal_error"}
    assert error.source_code is None
    assert error.retryable is True


def test_the_code_is_declared_for_a_published_failure() -> None:
    assert is_declared_failure_code(_CODE)
    failure = Failure(
        stage="candidate", code=_CODE, message="m", retryable=True, case_id=1, metadata={}
    )
    assert failure.code == _CODE
