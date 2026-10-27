"""Review fixes for the OpenRouter zero proofs (spec 2026-10-26 §9, after OME-1746).

FEATURE: cost of intelligence (OME-1287). Both proofs read only billing facts. The review of
PR #1571 found three gaps: a crash on odd values (#7), refusal output in a field the proof did not
read (#1), and the paid-stage rule only in the 429 proof (#2).

INVARIANT under test: any output or paid stage keeps the cost unknown in both proofs, and no value
of any shape makes a proof raise.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest

from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.openrouter_provider.pre_output_refusal import proves_pre_output_refusal
from aigateway.plugins.openrouter_provider.zero_insurance import proves_insured_zero
from aigateway.plugins.taxonomy import ProviderUsageAccountingEvidence

_REFUSAL: dict[str, Any] = {
    "id": "gen-1",
    "object": "chat.completion",
    "model": "anthropic/claude-opus-5.5",
    "choices": [
        {
            "index": 0,
            "finish_reason": "content_filter",
            "native_finish_reason": "refusal",
            "message": {"role": "assistant", "content": None, "refusal": None, "reasoning": None},
        }
    ],
    "openrouter_metadata": {"attempt": 1, "is_byok": False},
}
_RATE_LIMITED: dict[str, Any] = {
    "error": {"code": 429, "metadata": {"error_type": "rate_limit_exceeded"}},
    "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
}


def _refusal(*, message: dict[str, Any] | None = None, **top: Any) -> dict[str, Any]:
    body = copy.deepcopy(_REFUSAL)
    body["choices"][0]["message"].update(message or {})
    body.update(top)
    return body


def _with_pipeline(body: dict[str, Any], *stages: object) -> dict[str, Any]:
    body = copy.deepcopy(body)
    body["openrouter_metadata"]["pipeline"] = list(stages)
    return body


def _refusal_proven(body: dict[str, Any]) -> bool:
    return proves_pre_output_refusal(
        body, http_status=200, request_has_potential_auxiliary_charge=False
    )


def _insured(body: dict[str, Any]) -> bool:
    return proves_insured_zero(body, http_status=429, request_has_potential_auxiliary_charge=False)


def test_the_base_bodies_are_certified() -> None:
    assert _refusal_proven(_refusal())
    assert _insured(copy.deepcopy(_RATE_LIMITED))


# ── #1: output in any message field, or at the top level, is output ───────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_refusal(message={"audio": {"id": "a1", "data": "UklGR"}}), id="audio"),
        pytest.param(_refusal(message={"images": [{"type": "image_url"}]}), id="images"),
        pytest.param(_refusal(message={"annotations": [{"type": "url_citation"}]}), id="notes"),
        pytest.param(_refusal(message={"some_new_output": "text"}), id="unknown-field"),
        pytest.param(_refusal(message={"content": [{"type": "text"}]}), id="content-parts"),
        pytest.param(_refusal(output=[{"type": "output_text", "text": "x"}]), id="top-output"),
        pytest.param(_refusal(content="partial"), id="top-content"),
    ],
)
def test_a_refusal_with_output_in_any_field_stays_unknown(body: dict[str, Any]) -> None:
    assert not _refusal_proven(body)


@pytest.mark.parametrize(
    "message",
    [
        pytest.param({"annotations": []}, id="empty-list"),
        pytest.param({"audio": {}}, id="empty-object"),
        pytest.param({"images": None}, id="null"),
        pytest.param({"content": ""}, id="empty-text"),
        pytest.param({"role": "assistant"}, id="role-only"),
    ],
)
def test_an_empty_message_field_does_not_block_the_refusal_zero(message: dict[str, Any]) -> None:
    assert _refusal_proven(_refusal(message=message))


# ── #2: both proofs share the paid-stage rule ──────────────────────────────────────────────────


@pytest.mark.parametrize("stage_type", ["plugin", "server_tools"])
def test_a_paid_stage_keeps_both_proofs_unknown(stage_type: str) -> None:
    stage = {"type": stage_type, "name": "web"}

    assert not _refusal_proven(_with_pipeline(_REFUSAL, stage))
    assert not _insured(_with_pipeline(_RATE_LIMITED, stage))


def test_a_free_stage_keeps_both_proofs_certified() -> None:
    stage = {"type": "guardrail", "cost_usd": Decimal("0")}

    assert _refusal_proven(_with_pipeline(_REFUSAL, stage))
    assert _insured(_with_pipeline(_RATE_LIMITED, stage))


def test_the_refusal_with_a_paid_stage_keeps_the_base_evidence_end_to_end() -> None:
    evidence = OpenRouterProviderPlugin().supplement_chat_usage_accounting(
        evidence=ProviderUsageAccountingEvidence(supported=True),
        raw_response=_with_pipeline(_REFUSAL, {"type": "plugin"}),
        http_status=200,
        failed=False,
        request_has_potential_auxiliary_charge=False,
    )

    assert evidence.direct_cost.status == "unavailable"


# ── #7: no value makes a proof raise ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("stage_type", "paid"),
    [
        pytest.param(["plugin"], True, id="list-with-paid-name"),
        pytest.param({"name": "server_tools"}, True, id="object-with-paid-name"),
        pytest.param(["guardrail"], False, id="list-with-free-name"),
        pytest.param({"kind": "guardrail"}, False, id="object-with-free-name"),
        pytest.param(7, False, id="number"),
        pytest.param(None, False, id="null"),
    ],
)
def test_a_stage_type_of_any_shape_gives_a_result(stage_type: object, paid: bool) -> None:
    stage = {"type": stage_type}

    assert _refusal_proven(_with_pipeline(_REFUSAL, stage)) is not paid
    assert _insured(_with_pipeline(_RATE_LIMITED, stage)) is not paid


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({**_RATE_LIMITED, "usage": {"completion_tokens": "sNaN"}}, id="text-snan"),
        pytest.param(
            {**_RATE_LIMITED, "usage": {"completion_tokens": Decimal("sNaN")}}, id="count-snan"
        ),
        pytest.param({**_RATE_LIMITED, "usage": {"cost": Decimal("sNaN")}}, id="cost-snan"),
        pytest.param({**_RATE_LIMITED, "billing": {"cost_usd": Decimal("NaN")}}, id="cost-nan"),
    ],
)
def test_a_not_a_number_value_does_not_raise_and_is_not_a_zero(body: dict[str, Any]) -> None:
    assert not _insured(body)


def test_a_not_a_number_cost_on_a_refusal_does_not_raise_and_is_not_a_zero() -> None:
    body = _with_pipeline(_REFUSAL, {"type": "guardrail", "cost_usd": Decimal("sNaN")})

    assert not _refusal_proven(body)
