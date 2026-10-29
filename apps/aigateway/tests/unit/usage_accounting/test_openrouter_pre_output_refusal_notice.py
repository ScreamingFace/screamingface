"""A refusal notice is not output (spec 2026-10-26 §10).

FEATURE: cost of intelligence (OME-1287). Anthropic sometimes puts a fixed policy notice in
``message.refusal`` when it refuses before output. The prod cache backfill of 2026-10-27 found
8 such replies: no ``usage``, no output tokens, no cost. OpenRouter did not bill them.

STORY: as a reader of a board, I see a cost for a run of a model that refused a question with a
policy notice, instead of "—".

INVARIANT under test: text in ``refusal`` alone never makes the cost unknown, and every other
sign of billed work (``usage``, output, a paid stage, a cost) still does.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest

from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.openrouter_provider.pre_output_refusal import proves_pre_output_refusal
from aigateway.plugins.taxonomy import ProviderUsageAccountingEvidence

_ZERO = {
    "status": "provider_guaranteed_zero",
    "amount": "0",
    "unit": "openrouter_credits",
    "source": "openrouter.pre_output_refusal",
}
# WHY these texts: the two notices found in the prod cache on 2026-10-27, verbatim.
_CYBER_NOTICE = (
    "This request triggered restrictions on violative cyber content and was blocked under "
    "Anthropic's Usage Policy. To learn more, see "
    "https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback."
)
_EXPLOSIVES_NOTICE = (
    "This request triggered restrictions on content related to the development of high-yield "
    "explosives and was blocked under Anthropic's Usage Policy. To learn more, provide feedback, "
    "or request an exemption based on how you use Claude, visit our help center: "
    "https://support.claude.com/"
)


def _notice_refusal(
    notice: str = _CYBER_NOTICE, *, message: dict[str, Any] | None = None, **top: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "gen-1",
        "object": "chat.completion",
        "model": "anthropic/claude-opus-5.5",
        "choices": [
            {
                "index": 0,
                "finish_reason": "content_filter",
                "native_finish_reason": "refusal",
                "message": {"role": "assistant", "content": None, "refusal": notice},
            }
        ],
        "openrouter_metadata": {"attempt": 1, "is_byok": False, "pipeline": []},
    }
    body["choices"][0]["message"].update(message or {})
    body.update(top)
    return body


def _proven(body: dict[str, Any]) -> bool:
    return proves_pre_output_refusal(
        body, http_status=200, request_has_potential_auxiliary_charge=False
    )


def _supplement(raw_response: dict[str, Any]) -> ProviderUsageAccountingEvidence:
    return OpenRouterProviderPlugin().supplement_chat_usage_accounting(
        evidence=ProviderUsageAccountingEvidence(supported=True),
        raw_response=raw_response,
        http_status=200,
        failed=False,
        request_has_potential_auxiliary_charge=False,
    )


@pytest.mark.parametrize(
    "notice",
    [
        pytest.param(_CYBER_NOTICE, id="cyber-notice"),
        pytest.param(_EXPLOSIVES_NOTICE, id="explosives-notice"),
        pytest.param("I can't help with that.", id="plain-sentence"),
    ],
)
def test_a_refusal_notice_without_usage_is_a_certified_zero(notice: str) -> None:
    body = _notice_refusal(notice)

    assert _proven(body)
    assert _supplement(copy.deepcopy(body)).direct_cost.as_json() == _ZERO


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            _notice_refusal(usage={"completion_tokens": 0, "cost": Decimal("0.0042")}),
            id="usage-cost",
        ),
        pytest.param(_notice_refusal(usage={"completion_tokens": 37}), id="usage-output"),
        pytest.param(_notice_refusal(message={"content": "Partial answer"}), id="content"),
        pytest.param(_notice_refusal(message={"reasoning": "The user asks"}), id="reasoning"),
        pytest.param(
            _notice_refusal(message={"reasoning_details": [{"type": "reasoning.text"}]}),
            id="reasoning-details",
        ),
        pytest.param(
            _notice_refusal(openrouter_metadata={"pipeline": [{"type": "plugin", "name": "web"}]}),
            id="paid-stage",
        ),
        pytest.param(_notice_refusal(billing={"cost_usd": Decimal("0.01")}), id="charge"),
    ],
)
def test_a_refusal_notice_with_billed_work_stays_unknown(body: dict[str, Any]) -> None:
    assert not _proven(body)
    assert _supplement(copy.deepcopy(body)).direct_cost.status == "unavailable"
