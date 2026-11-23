"""MI-28: client.chat against the real local Engine and the FakeGateway (SDK unit U8).

FEATURE: SDK model inference, unit U8 (docs/spec/2026-11-18-sdk-model-inference,
prd/model-inference.md row MI-28; scenarios MI-S1, MI-S3, MI-S5). One plain call, one tool call
and one stream go through ``client.chat.completions.create`` to
POST /v1/chat/completions of a REAL local Engine (``EngineProcess``, the ``create_local_app``
subprocess). The Engine runs each call as a one-model recipe, and its gateway is the FakeGateway
with an authored in-memory tape. No paid call: the fake has no HTTP client and binds loopback only.

AIDEV-NOTE: this is the only test that reads the real Engine chat wire with the SDK reader. The
frame-reader unit tests read a hand copy of that wire (tests/_chat_frames.py). When this test
fails and those tests pass, the hand copy and the Engine are not the same any more.

Run it by hand (it needs docker, like the rest of the e2e lane)::

    SCREAMINGFACE_TEST_E2E=1 uv run pytest tests/e2e/test_model_inference_local_engine.py -rs
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from harness._gating import require_e2e_stack
from harness.fake_gateway import FakeGateway
from harness.stack import EngineProcess
from harness.tape import TAPE_SCHEMA, LoadedTape, TapeDocument

import screamingface as sf

pytestmark = pytest.mark.e2e

#: Both ids are declared Engine routes (world/models/seeds/openrouter.py), as in test_failures.
TEXT_MODEL = "openrouter/openai/gpt-5.5"
TOOL_MODEL = "openrouter/google/gemini-3.1-pro-preview"

ANSWER = "Paris"
ARGUMENTS = '{"city":"Paris"}'
TOOL_CALL: dict[str, Any] = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "get_weather", "arguments": ARGUMENTS},
}
TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "The weather in a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}
_TRACE_ID = re.compile(r"[0-9a-f]{32}")


def _gateway_body(message: dict[str, Any], finish_reason: str) -> dict[str, Any]:
    """A gateway chat completion that the Engine connector prices: 10 + 4 tokens, 0.001 credits.

    WHY this shape: it is a copy of the gateway body of the Engine chat tests
    (apps/screamingface-engine/tests/integration/test_chat_tools_sdk.py ``_body``), which the
    connector (world/model_response.py ``parse_choice``) and the cost reader (world/accounting.py,
    the ``_aigw`` block) accept as an answer and as a tool call.
    """
    cost = {"status": "reported", "amount": "0.001", "unit": "openrouter_credits", "source": "x"}
    attempt = {
        "outcome": "succeeded",
        "provider": "openrouter",
        "response_model": "m",
        "latency_ms": 30,
        "usage": {"input": {"total": 10}, "output": {"total": 4}},
        "direct_cost": cost,
    }
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        "_aigw": {
            "usage_accounting": {
                "capture_status": "complete",
                "omitted_attempts": 0,
                "attempts": [attempt],
                "cache": {"status": "miss", "reference": None},
            },
            "request_economics": {
                "direct_cost_status": "complete",
                "known_direct_cost_subtotals": [{"unit": "openrouter_credits", "amount": "0.001"}],
            },
        },
    }


def _exchange(model: str, fingerprint: str, body: dict[str, Any]) -> dict[str, object]:
    """One taped 200 answer for ``model``; the fake matches by model (one exchange each)."""
    return {
        "normalized": {"provider": "openrouter", "model": model, "fingerprint": fingerprint},
        "request": {
            "method": "POST",
            "path": "/v1/chat/completions",
            "body": {"model": model, "messages": []},
        },
        "response": {
            "status": 200,
            "media_type": "application/json",
            "body_b64": base64.b64encode(json.dumps(body).encode()).decode(),
        },
    }


def _tape() -> LoadedTape:
    """The authored tape: a text answer for TEXT_MODEL and a tool call for TOOL_MODEL."""
    text = _gateway_body({"role": "assistant", "content": ANSWER}, "stop")
    tool = _gateway_body(
        {"role": "assistant", "content": None, "tool_calls": [TOOL_CALL]}, "tool_calls"
    )
    document = {
        "schema": TAPE_SCHEMA,
        "provenance": {
            "board": "model-inference-mi28",
            "revision": "authored-mi28-2026-11",
            "expression_sha": "e" * 64,
            "engine_sha": "authored — no engine rendered this tape",
            "recorded_at": "2026-11-23T00:00:00Z",
            "run_ref": "in-memory MI-28 tape",
            "authored": True,
        },
        "exchanges": [
            _exchange(TEXT_MODEL, "c" * 64, text),
            _exchange(TOOL_MODEL, "d" * 64, tool),
        ],
    }
    return LoadedTape(TapeDocument.model_validate(document))


class _ToolListingGateway(FakeGateway):
    """The FakeGateway, with ``tools`` in the catalogue row of TOOL_MODEL.

    WHY: with ``tools`` in a request, the Engine chat route refuses a final model whose row in
    GET /v1/models does not list ``tools`` in ``supported_parameters`` (rest/chat_tools.py,
    TC-S10). The FakeGateway lists ``[]`` for each taped model. The tape answers TOOL_MODEL with a
    tool call, so the row claims only what the tape shows.
    AIDEV-NOTE: this overrides a private method of the harness, because the tests here are
    append-only and the harness file must not change. If the harness gets a public way to set the
    supported parameters, use it and delete this class.
    """

    def _catalog_projection(self) -> bytes:
        listing = json.loads(super()._catalog_projection())
        for row in listing["data"]:
            if row["id"] == TOOL_MODEL:
                row["supported_parameters"] = ["tools"]
        return json.dumps(listing).encode()


@dataclass(frozen=True, slots=True)
class _LocalEngine:
    """The booted stack: the SDK talks to ``engine_url``; ``fake`` records off-tape requests."""

    fake: FakeGateway
    engine_url: str


@pytest.fixture(scope="module")
def local_engine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_LocalEngine]:
    """Boot the FakeGateway and the real local Engine once for the module; stop both at the end."""
    require_e2e_stack()
    fake = _ToolListingGateway(_tape())
    base_url = fake.start_sync()
    # WHY no assets_dir: a chat call runs no Benchmark, so the Engine installs none.
    engine = EngineProcess(work_dir=tmp_path_factory.mktemp("mi28"))
    try:
        yield _LocalEngine(fake=fake, engine_url=engine.start(base_url))
    finally:
        engine.stop()
        fake.stop_sync()


def test_model_inference_with_the_real_local_engine_plain_call(local_engine: _LocalEngine) -> None:
    # MI-S1: a recipe as the model, one prompt, one answer with its usage and trace.
    with sf.Client(engine_url=local_engine.engine_url) as client:
        reply = client.chat.completions.create(
            "What is the capital of France?", model=sf.Model(TEXT_MODEL)
        )

    assert reply.text == ANSWER
    assert reply.model.startswith("(")
    assert reply.cost_usd == Decimal("0.001")
    assert reply.choices[0].finish_reason == "stop"
    assert reply.screamingface.status == "answered"
    assert reply.trace_id is not None
    assert _TRACE_ID.fullmatch(reply.trace_id)
    assert reply.usage.total_tokens > 0
    assert local_engine.fake.refusals == ()


def test_model_inference_with_the_real_local_engine_tool_call(local_engine: _LocalEngine) -> None:
    # MI-S3: the model per call, with one client tool; the answer is the tool call.
    with sf.Client(engine_url=local_engine.engine_url) as client:
        reply = client.chat.completions.create(
            model=TOOL_MODEL,
            messages=[{"role": "user", "content": "What is the weather in Paris?"}],
            tools=[TOOL],
        )

    assert reply.text is None
    assert reply.choices[0].finish_reason == "tool_calls"
    assert reply.tool_calls is not None
    call = reply.tool_calls[0]
    assert call.function.name == "get_weather"
    assert json.loads(call.function.arguments) == json.loads(ARGUMENTS)
    assert local_engine.fake.refusals == ()


def test_model_inference_with_the_real_local_engine_stream(local_engine: _LocalEngine) -> None:
    # MI-S5: the stream with its usage chunk; the text of the chunks is the answer.
    with (
        sf.Client(engine_url=local_engine.engine_url) as client,
        client.chat.completions.create(
            "What is the capital of France?",
            model=TEXT_MODEL,
            stream=True,
            stream_options={"include_usage": True},
        ) as stream,
    ):
        chunks = list(stream)

    assert "".join(chunk.text for chunk in chunks) == ANSWER
    with_choices = [chunk for chunk in chunks if chunk.choices]
    assert with_choices[-1].choices[0].finish_reason == "stop"
    assert chunks[-1].choices == ()
    assert chunks[-1].usage is not None
    assert local_engine.fake.refusals == ()
