"""An upstream code is lifted only when the Gateway declares it (spec 3.3, gateway code provenance).

FEATURE: Gateway code provenance (`docs/spec/2026-11-23-gateway-code-provenance.md`).
`connector._raise_for_status` lifts `detail.code` from a Gateway body, or from a proxy in front of
the Gateway. The lifted code reaches the model-call log line, the call's observation and the
benchmark report before any route's own policy runs, so only a code in `GATEWAY_CODES` is lifted;
any other keeps the connector's `aigateway_http_<status>`.

STORY: as an operator, a body that puts a path, a key or a private ID into `detail.code` never
puts it into my logs, my observations or a caller's report.

INVARIANT: every declared Gateway code is lifted unchanged and no Engine-reserved code is
(OME-941); permanence stays `False` only for 429 and 5xx.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext

import httpx
import pytest
from frozen_copy_support import Gateway, error, replay_scope, run_call

from screamingface_engine.benchmarks.aggregation import PublicError, public_error
from screamingface_engine.benchmarks.contract import DECLARED_FAILURE_CODES
from screamingface_engine.error_text import ENGINE_RESERVED_CODES
from screamingface_engine.observations import RunObservations
from screamingface_engine.request_scope import RequestScope
from screamingface_engine.world.attachment_parts import INTENT_ERROR, UNSUPPORTED_CONTENT_PART
from screamingface_engine.world.gateway_codes import GATEWAY_CODES
from screamingface_engine.world.gateway_transport import _raise_for_status
from url4.core.errors import ResolutionError

_SECRET_ID = "byom_secret_deployment_alpha"

_UNDECLARED_CODES = [
    "/private/origin",
    "../relative/secret_dir",
    "sk-secret123456",
    "byom_" + "f" * 32 + "/secret_model",
    "Authorization: Bearer sk-secret123456",
    "https://byom-origin.internal.test:8443",
    "provider error",
    " provider_error",
    "a" * 81,
    "",
    # Review counterexamples (2026-11-23): plain identifiers a shape screen would keep.
    _SECRET_ID,
    "byom-origin.internal.test:8443",
    "hf_" + "A" * 32,
    "ghp_" + "A" * 36,
    "sk_live_abcdef123456",
    # Plain identifiers the Gateway does not write.
    "boom",
    "model_token_cap",
    "invalid_credential",
    # Not a string at all.
    42,
    None,
    ["provider_error"],
]


def _refused(status: int, code: object) -> ResolutionError:
    response = httpx.Response(status, json={"detail": {"code": code, "message": "m"}})
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(response)
    return caught.value


@pytest.mark.parametrize("code", _UNDECLARED_CODES)
@pytest.mark.parametrize("status", [400, 429, 502])
def test_an_undeclared_code_takes_the_status_code(code: object, status: int) -> None:
    refused = _refused(status, code)
    assert refused.code == f"aigateway_http_{status}"
    assert refused.permanent is (status == 400)


@pytest.mark.parametrize("code", sorted(GATEWAY_CODES))
def test_every_declared_gateway_code_is_lifted_unchanged(code: str) -> None:
    # WHY the one exception: the Gateway's content-part refusal is translated to `intent_error`
    # (spec #1450 section 4), which the closed rule leaves as it was.
    expected = INTENT_ERROR if code == UNSUPPORTED_CONTENT_PART else code
    assert _refused(502, code).code == expected


@pytest.mark.parametrize("code", sorted(ENGINE_RESERVED_CODES))
def test_no_engine_reserved_code_is_lifted(code: str) -> None:
    assert _refused(502, code).code == "aigateway_http_502"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "expected", "permanent"),
    [
        # A retired code: written by a Gateway build since capture began, held by a sealed copy.
        (409, "profile_index_conflict", "profile_index_conflict", True),
        (500, "boom", "aigateway_http_500", False),
    ],
    ids=["retired", "undeclared"],
)
async def test_a_replayed_error_keeps_a_retired_code_and_drops_an_undeclared_one(
    status: int, code: str, expected: str, permanent: bool
) -> None:
    captured = httpx.Response(
        status,
        headers={"X-AIGW-Replay": "error"},
        json={"detail": {"code": code, "message": "m"}},
    )

    _tally, _answer, failure = await run_call(Gateway(replay_steps=[captured]), replay_scope())

    assert failure is not None
    assert (failure.code, failure.permanent) == (expected, permanent)


class _FailedCodes:
    """A run observer that records only the code each failed model call reports."""

    def __init__(self) -> None:
        self.codes: list[str] = []

    def bind(self) -> nullcontext[None]:
        return nullcontext()

    async def aclose(self) -> None:
        return None

    def model_call(self, model_id: str, emit: object) -> _FailedCodes:
        return self

    def bridge_loss(self, dropped: int) -> dict[str, int]:
        return {}

    async def start(self) -> None:
        return None

    async def close(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def completed(self, finish_reason: str | None) -> None:
        return None

    def failed(self, code: str) -> None:
        self.codes.append(code)

    def retry(self, *, attempt: int, delay_seconds: float) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "reported"),
    [(_SECRET_ID, "aigateway_http_400"), ("auth_required", "auth_required")],
    ids=["undeclared", "declared"],
)
async def test_the_log_line_and_the_observation_carry_only_a_declared_code(
    code: str, reported: str, caplog: pytest.LogCaptureFixture
) -> None:
    observer = _FailedCodes()
    run = RunObservations((lambda: observer,))

    with caplog.at_level(logging.WARNING), run.bind():
        _tally, _answer, failure = await run_call(
            Gateway(chat_steps=[error(400, code)]), RequestScope(origin="run")
        )

    assert failure is not None and failure.code == reported
    assert observer.codes == [reported]
    failed = [r.getMessage() for r in caplog.records if "model call failed" in r.getMessage()]
    assert len(failed) == 1 and f"code={reported}" in failed[0]
    if code != reported:
        assert code not in caplog.text


def _report(status: int, code: str) -> PublicError:
    refused = _refused(status, code)
    return public_error(
        {
            "kind": type(refused).__name__,
            "code": refused.code,
            "message": str(refused),
            "permanent": refused.permanent,
        },
        default_code="case_execution_failed",
        default_message="Candidate Case execution failed",
    )


@pytest.mark.parametrize(("status", "retryable"), [(502, True), (400, False)])
def test_the_report_gives_exactly_the_status_code_for_an_undeclared_code(
    status: int, retryable: bool
) -> None:
    # WHY no `upstream_error`: `aigateway_http_<status>` is itself a declared failure code
    # (`benchmarks/contract.py`), so it reaches the report as itself with no `source_code`.
    failure = _report(status, _SECRET_ID)

    assert failure.code == f"aigateway_http_{status}"
    assert failure.source_code is None
    assert failure.retryable is retryable
    assert _SECRET_ID not in repr(failure)


def test_a_declared_gateway_code_outside_the_failure_axis_stays_the_source_code() -> None:
    assert "auth_required" in GATEWAY_CODES
    assert "auth_required" not in DECLARED_FAILURE_CODES

    failure = _report(401, "auth_required")

    assert (failure.code, failure.source_code, failure.retryable) == (
        "upstream_error",
        "auth_required",
        False,
    )


def test_a_404_unsupported_parameters_still_maps_to_logprobs_unsupported() -> None:
    response = httpx.Response(
        404, json={"detail": {"code": "unsupported_parameters", "message": "m"}}
    )
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(response, logprobs_requested=True)
    assert caught.value.code == "logprobs_unsupported"
