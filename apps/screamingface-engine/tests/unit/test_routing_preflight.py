"""The `/route-answer` preflight: four metadata reads before any paid call (OME-1822).

FEATURE: BYOM routing pilot (spec 3.3 step 4). Before the classifier runs, the handler reads the
classifier's details and each branch's parameter document with the caller's identity. A target
the caller cannot see, a Connection that cannot run, and a bound `max_tokens` the branch does not
accept are all refused here, so a known configuration error never costs a classification.

INVARIANT: every case here makes zero inference calls. `not_found` and a transient read stop the
preflight at once; a Connection or contract finding is decided only once all four targets are
visible, so a caller who cannot see every target learns nothing about the ones they can.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from routing_support import (
    CLASSIFIER,
    DETAILS_PATH,
    LABELS,
    MODELS,
    PARAMETERS_PATH,
    Gateway,
    classifier_document,
    max_tokens_rule,
    parameters_document,
    preflight_calls,
    run_direct,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.no_default_scope]

_TARGETS = [(DETAILS_PATH, CLASSIFIER)] + [(PARAMETERS_PATH, MODELS[label]) for label in LABELS]
_TARGET_IDS = ["classifier", *LABELS]


def _gets(gateway: Gateway) -> list[tuple[str, str, str]]:
    return [call for call in gateway.calls() if call[0] == "GET"]


async def _refused(gateway: Gateway) -> tuple[str, bool]:
    outcome = await run_direct(gateway)
    assert all(request.method == "GET" for request in gateway.requests)
    return outcome.code(), outcome.permanent()


def _json(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body)


# --- what is read ---------------------------------------------------------------------------------


async def test_the_preflight_reads_each_target_once_in_file_order_with_no_body() -> None:
    gateway = Gateway()

    await run_direct(gateway)

    assert _gets(gateway) == preflight_calls()
    for request in gateway.requests[:4]:
        assert request.content == b""
        assert set(request.url.params) == {"model"}


# --- stop at once ---------------------------------------------------------------------------------


@pytest.mark.parametrize("target", _TARGETS, ids=_TARGET_IDS)
@pytest.mark.parametrize(
    "step",
    [
        pytest.param(httpx.ConnectError("refused"), id="connect"),
        pytest.param(httpx.ReadTimeout("slow"), id="read-timeout"),
        pytest.param(_json(429, {"detail": "slow down"}), id="429"),
        pytest.param(_json(500, {"detail": "boom"}), id="500"),
        pytest.param(_json(503, {"detail": "unavailable"}), id="503"),
    ],
)
async def test_a_transient_read_is_unavailable_and_stops_at_once(
    target: tuple[str, str], step: Any
) -> None:
    gateway = Gateway(script={target: step})

    assert await _refused(gateway) == ("routing_preflight_unavailable", False)
    assert _gets(gateway)[-1][1:] == target


@pytest.mark.parametrize("target", _TARGETS, ids=_TARGET_IDS)
@pytest.mark.parametrize(
    "step",
    [
        pytest.param(_json(400, {"detail": "unknown provider: x"}), id="400"),
        pytest.param(_json(404, {"detail": {"code": "model_not_found", "model": "x"}}), id="404"),
    ],
)
async def test_a_target_the_caller_cannot_see_is_an_unknown_profile(
    target: tuple[str, str], step: Any
) -> None:
    gateway = Gateway(script={target: step})

    assert await _refused(gateway) == ("routing_profile_not_found", True)
    assert _gets(gateway)[-1][1:] == target


@pytest.mark.parametrize("target", _TARGETS, ids=_TARGET_IDS)
@pytest.mark.parametrize(
    "step",
    [
        pytest.param(httpx.Response(302, headers={"Location": "/login"}), id="redirect"),
        pytest.param(_json(403, {"detail": "forbidden"}), id="403"),
        pytest.param(_json(401, {"detail": {"code": "unauthenticated"}}), id="401-other"),
        pytest.param(_json(422, {"detail": "unprocessable"}), id="422"),
        pytest.param(httpx.Response(204), id="204"),
        pytest.param(httpx.Response(200, text="<html>login</html>"), id="not-json"),
        pytest.param(_json(200, ["not", "a", "document"]), id="not-an-object"),
    ],
)
async def test_any_other_answer_fails_the_preflight_at_once(
    target: tuple[str, str], step: Any
) -> None:
    gateway = Gateway(script={target: step})

    assert await _refused(gateway) == ("routing_preflight_failed", True)
    assert _gets(gateway)[-1][1:] == target


@pytest.mark.parametrize(
    ("target", "document"),
    [
        pytest.param(
            (DETAILS_PATH, CLASSIFIER), classifier_document(id=f"{CLASSIFIER}_v2"), id="classifier"
        ),
        pytest.param(
            (PARAMETERS_PATH, MODELS["code"]), parameters_document(MODELS["math"]), id="branch"
        ),
        pytest.param(
            (DETAILS_PATH, CLASSIFIER),
            {k: v for k, v in classifier_document().items() if k != "execution_access"},
            id="classifier-without-access",
        ),
        pytest.param(
            (PARAMETERS_PATH, MODELS["code"]),
            {**parameters_document(MODELS["code"]), "context": "configured"},
            id="branch-without-context",
        ),
        pytest.param(
            (PARAMETERS_PATH, MODELS["code"]),
            {**parameters_document(MODELS["code"]), "parameters": []},
            id="branch-parameters-not-a-table",
        ),
    ],
)
async def test_a_document_that_is_not_the_published_one_fails_at_once(
    target: tuple[str, str], document: dict[str, Any]
) -> None:
    gateway = Gateway(script={target: _json(200, document)})

    assert await _refused(gateway) == ("routing_preflight_failed", True)
    assert _gets(gateway)[-1][1:] == target


# WHY 20,000 levels in 40 KB: Python's JSON reader stops at about 1,000 levels with a
# `RecursionError`, which is not a `ValueError`.
_TOO_DEEP = b"[" * 20_000 + b"]" * 20_000


@pytest.mark.parametrize("target", _TARGETS, ids=_TARGET_IDS)
@pytest.mark.parametrize("status", [200, 401])
async def test_a_body_nested_too_deep_to_read_fails_the_preflight_at_once(
    target: tuple[str, str], status: int
) -> None:
    """WHY `401` too: the reauthentication check reads the body's code before the status decides."""
    gateway = Gateway(script={target: httpx.Response(status, content=_TOO_DEEP)})

    assert await _refused(gateway) == ("routing_preflight_failed", True)
    assert _gets(gateway)[-1][1:] == target


# --- decided once every target is visible ---------------------------------------------------------


@pytest.mark.parametrize("target", _TARGETS, ids=_TARGET_IDS)
@pytest.mark.parametrize(
    "step",
    [
        pytest.param(_json(409, {"detail": {"code": "connection_pending"}}), id="409"),
        pytest.param(
            _json(401, {"detail": {"code": "auth_required", "message": "sign in"}}),
            id="401-auth-required",
        ),
    ],
)
async def test_an_unusable_connection_is_noted_and_the_reads_go_on(
    target: tuple[str, str], step: Any
) -> None:
    gateway = Gateway(script={target: step})

    assert await _refused(gateway) == ("routing_connection_missing", True)
    assert _gets(gateway) == preflight_calls()


@pytest.mark.parametrize(
    ("target", "document"),
    [
        pytest.param(
            (DETAILS_PATH, CLASSIFIER), classifier_document(execution_access="missing"), id="clf"
        ),
        pytest.param(
            (PARAMETERS_PATH, MODELS["general"]),
            parameters_document(MODELS["general"], access="missing"),
            id="general",
        ),
        pytest.param(
            (PARAMETERS_PATH, MODELS["math"]),
            parameters_document(MODELS["math"], access="unknown"),
            id="math-unknown-value",
        ),
    ],
)
async def test_access_other_than_configured_is_a_missing_connection(
    target: tuple[str, str], document: dict[str, Any]
) -> None:
    gateway = Gateway(script={target: _json(200, document)})

    assert await _refused(gateway) == ("routing_connection_missing", True)
    assert _gets(gateway) == preflight_calls()


async def test_an_ungranted_later_branch_hides_an_earlier_pending_connection() -> None:
    gateway = Gateway(
        script={
            (DETAILS_PATH, CLASSIFIER): _json(409, {"detail": {"code": "connection_pending"}}),
            (PARAMETERS_PATH, MODELS["math"]): _json(404, {"detail": "not found"}),
        }
    )

    assert await _refused(gateway) == ("routing_profile_not_found", True)


async def test_a_missing_connection_is_reported_before_a_contract_mismatch() -> None:
    gateway = Gateway(
        script={
            (DETAILS_PATH, CLASSIFIER): _json(
                200, classifier_document(result_contract="classification-scores-v2")
            ),
            (PARAMETERS_PATH, MODELS["code"]): _json(
                200, parameters_document(MODELS["code"], access="missing")
            ),
        }
    )

    assert await _refused(gateway) == ("routing_connection_missing", True)


async def test_a_classifier_answering_another_contract_is_a_mismatch() -> None:
    gateway = Gateway(
        script={
            (DETAILS_PATH, CLASSIFIER): _json(
                200, classifier_document(result_contract="classification-scores-v2")
            )
        }
    )

    assert await _refused(gateway) == ("routing_profile_mismatch", True)
    assert _gets(gateway) == preflight_calls()


@pytest.mark.parametrize(
    "rule",
    [
        pytest.param(
            max_tokens_rule(gateway={"status": "disabled", "reason": "auth_mode"}), id="disabled"
        ),
        pytest.param(
            max_tokens_rule(schema={"type": "integer", "minimum": 1, "maximum": 1000}),
            id="above-maximum",
        ),
        pytest.param(
            max_tokens_rule(schema={"type": "integer", "minimum": 4096}), id="below-minimum"
        ),
        pytest.param(max_tokens_rule(schema={"type": "number", "minimum": 1}), id="not-integer"),
        pytest.param(max_tokens_rule(schema=None), id="no-schema"),
        pytest.param(max_tokens_rule(gateway="enabled"), id="gateway-not-a-table"),
        pytest.param(["max_tokens"], id="rule-not-a-table"),
    ],
)
async def test_a_branch_that_does_not_admit_its_max_tokens_is_a_mismatch(rule: object) -> None:
    # `code` binds 2048 (routing_support.MAX_TOKENS).
    gateway = Gateway(
        script={
            (PARAMETERS_PATH, MODELS["code"]): _json(
                200, parameters_document(MODELS["code"], rule=rule)
            )
        }
    )

    assert await _refused(gateway) == ("routing_profile_mismatch", True)
    assert _gets(gateway) == preflight_calls()


async def test_a_branch_publishing_no_max_tokens_is_a_mismatch() -> None:
    document = {**parameters_document(MODELS["code"]), "parameters": {}}
    gateway = Gateway(script={(PARAMETERS_PATH, MODELS["code"]): _json(200, document)})

    assert await _refused(gateway) == ("routing_profile_mismatch", True)


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param({"type": "integer", "minimum": 2048, "maximum": 2048}, id="both-bounds-equal"),
        pytest.param({"type": ["integer", "null"], "minimum": 1}, id="nullable-integer"),
        pytest.param({"type": "integer"}, id="unbounded"),
    ],
)
async def test_a_schema_that_admits_the_bound_value_passes(schema: dict[str, Any]) -> None:
    rule = max_tokens_rule(schema=schema)
    gateway = Gateway(
        script={
            (PARAMETERS_PATH, MODELS["code"]): _json(
                200, parameters_document(MODELS["code"], rule=rule)
            )
        }
    )

    document = (await run_direct(gateway)).document()

    assert document["selected"]["label"] == "code"
