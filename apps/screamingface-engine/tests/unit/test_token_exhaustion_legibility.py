"""Token exhaustion must say "not enough tokens", name the budget, and name the knob.

FEATURE: a reasoning model that spends its whole `max_tokens` budget thinking returns
`finish_reason="length"` with empty content. Before this feature that surfaced as
`malformed aigateway response` (wrong component) or as the check judge's generic
"no usable verdict" (no cause, no knob) — a researcher pays for the run and then
debugs the gateway instead of raising one parameter.
STORY: as a researcher whose candidate or check judge runs out of tokens, the failure
tells me the model hit its token budget, which budget, and where to raise it.

Two seams, mirroring where the signal exists:
  1. the connector holds `finish_reason` + the request's `max_tokens` — classification
     happens there (`model_token_cap`), like refusals already do (OME-679);
  2. `rubric_check._judged` holds the check judge's configured params — its failure
     message names the judge budget and the check_policy that pins it.

A separate module from `test_finish_reason_capture.py` per that file's own note: the
append-only gate reads growth of an existing test file as modification.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import httpx
import pytest

from screamingface_engine.benchmarks.rubric_check import (
    CHECK_ATTEMPTS,
    RubricCheck,
    RubricShape,
    _judged,
)
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, build_aigateway_world
from url4.core.errors import ResolutionError
from url4.dag import run as url4_run
from url4.peer.server import Url4Node

_MODEL = "anthropic/claude-haiku-4-5"


def _gateway(body: dict) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json=body)

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://aigateway.test"
    )


def _body(*, content: str | None, finish_reason: str | None) -> dict:
    choice = {"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}
    return {"choices": [choice], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


async def _run(body: dict, expression: str) -> str:
    cfg = AigatewayConfig(models=(ModelSpec(id=_MODEL),), default_model=_MODEL)
    async with _gateway(body) as client:
        world = await build_aigateway_world(cfg, client=client)
        return await url4_run(expression, io=world.node)


# ── seam 1: the connector classifies token exhaustion as its own model outcome ────────────


@pytest.mark.asyncio
async def test_token_exhausted_empty_turn_raises_model_token_cap() -> None:
    # The conflation this feature removes: an all-reasoning `length` turn used to collapse
    # into `aigateway_bad_response`, sending the reader off to debug the gateway.
    with pytest.raises(ResolutionError) as exc_info:
        await _run(_body(content=None, finish_reason="length"), f"/{_MODEL}(ctx)!go")

    assert exc_info.value.code == "model_token_cap"
    # WHY permanent: same budget in, same truncation out — a retry pays to fail identically.
    assert exc_info.value.permanent is True
    assert "max_tokens" in str(exc_info.value)


@pytest.mark.asyncio
async def test_token_exhausted_blank_turn_raises_model_token_cap() -> None:
    # Whitespace content is no answer either; without classification it silently became "".
    with pytest.raises(ResolutionError) as exc_info:
        await _run(_body(content=" ", finish_reason="length"), f"/{_MODEL}(ctx)!go")

    assert exc_info.value.code == "model_token_cap"


@pytest.mark.asyncio
async def test_token_cap_message_names_the_requested_budget() -> None:
    # The knob must be in the message: the request pinned max_tokens=4096, so the failure
    # names that number — the reader raises it without opening any source file.
    with pytest.raises(ResolutionError) as exc_info:
        await _run(
            _body(content=None, finish_reason="length"),
            f"(m:0.0:/{_MODEL}?max_tokens=4096&q=(ctx)!'go')!'$m'",
        )

    assert "max_tokens=4096" in str(exc_info.value)


@pytest.mark.asyncio
async def test_partially_truncated_answer_still_returns_content() -> None:
    # A truncated-but-present answer stays usable (grading may still want it); only the
    # no-answer case is an error. Don't regress this into a hard failure.
    text = await _run(_body(content="partial answer", finish_reason="length"), f"/{_MODEL}(ctx)!go")

    assert text == "partial answer"


@pytest.mark.asyncio
async def test_content_filter_still_wins_over_length() -> None:
    # INVARIANT (OME-679): refusal classification precedes emptiness AND token exhaustion —
    # a filtered turn that also reports `length` is a refusal, not a budget problem.
    body = {
        "choices": [
            {
                "message": {"role": "assistant", "content": None, "refusal": "nope"},
                "finish_reason": "content_filter",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    with pytest.raises(ResolutionError) as exc_info:
        await _run(body, f"/{_MODEL}(ctx)!go")

    assert exc_info.value.code == "provider_refusal"


# ── seam 2: the check judge's failure names its budget and the policy that pins it ────────


_CHECK = RubricCheck(
    label="DRACO",
    criterion="draco-pass.v1",
    threshold=0.7,
    shape=RubricShape(
        layout="flat",
        items="items",
        id_field="id",
        text_field="text",
        weight_field="weight",
    ),
    judge_model="openrouter/google/gemini-3.1-pro-preview",
    judge_params=(("temperature", "0.2"), ("max_tokens", "32768")),
    feedback="severity",
)

_CRITERIA = ({"id": "c1", "text": "says hi", "weight": 1.0, "area": ""},)


class _ProseJudge:
    """A judge whose replies never decode — the retry-exhaustion path."""

    async def evaluate(self, expression: str, *, env: dict) -> SimpleNamespace:
        return SimpleNamespace(text="I think the response is fine overall.")


class _StarvedJudge:
    """A judge whose model call itself dies on the token cap — the propagation path."""

    async def evaluate(self, expression: str, *, env: dict) -> SimpleNamespace:
        raise ResolutionError(
            "model ran out of tokens before completing an answer",
            code="model_token_cap",
            permanent=True,
        )


@pytest.mark.asyncio
async def test_unusable_verdicts_name_the_judge_budget_and_its_home() -> None:
    with pytest.raises(ResolutionError) as exc_info:
        # The fakes satisfy the one method _judged calls; cast supplies the port type.
        await _judged(
            cast(Url4Node, _ProseJudge()), _CHECK, question="q", answer="a", criteria=_CRITERIA
        )

    message = str(exc_info.value)
    assert f"in {CHECK_ATTEMPTS} attempts" in message
    # The knob and where it lives: the budget value and the policy module that sets it.
    assert "max_tokens=32768" in message
    assert "check_policy" in message


@pytest.mark.asyncio
async def test_starved_judge_failure_names_the_check_judge() -> None:
    # When the judge call itself dies on the cap, the message must still attribute the
    # failure to the CHECK JUDGE (not the candidate) and keep the token-cap cause.
    with pytest.raises(ResolutionError) as exc_info:
        await _judged(
            cast(Url4Node, _StarvedJudge()), _CHECK, question="q", answer="a", criteria=_CRITERIA
        )

    message = str(exc_info.value)
    assert "check judge" in message
    assert "ran out of tokens" in message
    assert "max_tokens=32768" in message
