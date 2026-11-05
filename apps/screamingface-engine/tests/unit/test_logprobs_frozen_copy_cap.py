"""A frozen copy over the gateway cap reports `failed` and the answer still arrives (E4b part 3).

Pins LC#18 (CHAR): a large logprobs reply that the gateway cannot capture (its 2,000,000-byte cap,
owned by the gateway) is reported as a failed capture, and the engine still answers. A separate
module (append-only gate).
"""

from __future__ import annotations

import json

import httpx
import pytest
from frozen_copy_support import CHAT, MODEL, Gateway, capture_scope, run_call


@pytest.mark.asyncio
async def test_frozen_copy_entry_over_the_cap_reports_failed() -> None:
    entry = {
        "token": "t",
        "bytes": [116],
        "logprob": -0.5,
        "top_logprobs": [{"token": "t", "bytes": [116], "logprob": -0.5}] * 5,
    }
    body = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "an answer"},
                "finish_reason": "stop",
                "logprobs": {"content": [entry] * 10_000},
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 10_000},
    }
    assert len(json.dumps(body)) > 2_000_000
    gateway = Gateway([httpx.Response(200, headers={"X-AIGW-Capture": "failed"}, json=body)])
    tally, answer, failure = await run_call(
        gateway,
        capture_scope(),
        web_search=False,
        expressions=[f"/{MODEL}(ctx)!go;logprobs=true"],
    )
    assert failure is None
    assert answer == "an answer"
    assert [(o.lane, o.status) for o in tally.outcomes] == [("chat", "failed")]
    assert [body for _h, body in gateway.calls(CHAT)][0]["logprobs"] is True
