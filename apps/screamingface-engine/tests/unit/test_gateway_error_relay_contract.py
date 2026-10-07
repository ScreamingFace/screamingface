"""OME-1136: the gateway's relayed provider message survives into the report.

The gateway composes `detail.message` from a sanitized upstream explanation. These tests prove
the engine side carries it — unchanged — through `_raise_for_status`, URL4 collection and
`public_error` into the case failure's message, with the gateway code kept as `source_code`.

The input is ``apps/aigateway/tests/fixtures/provider_error_relay/relayed_detail.json``, which
the gateway's own route test asserts it produces byte-for-byte; the Gate-1 parity list lives
beside it and is read by both apps' suites.

INVARIANT: the gateway never sends a message the engine's `public_message` would withhold — a
withheld message silently becomes the engine's generic default in the report.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from test_ifeval_provider_failure_stage import _aggregate, _collect_candidate_error

from screamingface_engine.error_text import public_message
from screamingface_engine.world.connector import _raise_for_status
from url4.core.errors import ResolutionError

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIXTURES = _REPO_ROOT / "apps/aigateway/tests/fixtures/provider_error_relay"
_DETAIL = json.loads((_FIXTURES / "relayed_detail.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_relayed_gateway_message_reaches_the_case_failure() -> None:
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(httpx.Response(400, json={"detail": _DETAIL}))
    assert caught.value.code == "bad_request"

    result = _aggregate(await _collect_candidate_error(caught.value))

    failure = result["cases"][0]["failures"][0]
    assert failure["message"] == _DETAIL["message"]
    assert "Unsupported parameter: 'temperature'" in failure["message"]
    assert failure["metadata"]["source_code"] == "bad_request"
    assert failure["retryable"] is False


def test_the_relayed_message_passes_public_message_unchanged() -> None:
    sentinel = "\x00withheld"
    assert public_message(_DETAIL["message"], default=sentinel) == _DETAIL["message"]


def test_gateway_gate_1_parity_fixture_matches_public_message() -> None:
    cases = json.loads((_FIXTURES / "public_message_parity.json").read_text(encoding="utf-8"))
    sentinel = "\x00withheld"
    for case in cases:
        withheld = public_message(case["text"], default=sentinel) == sentinel
        assert withheld is case["withheld"], case["text"]
