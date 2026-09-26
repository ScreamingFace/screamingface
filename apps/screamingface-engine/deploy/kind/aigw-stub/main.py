"""aigw-stub — a stand-in for aigateway inside the kind environment (uniform executor
test-plan §5). It answers `POST /v1/chat/completions` with a fixed OpenAI-shaped completion
that carries the `_aigw.usage_accounting` block the engine's connector reads
(`screamingface_engine/world/connector.py::_report_usage`,
`screamingface_engine/world/accounting.py::read_aigw`) — enough for a real run to complete and
be priced, never a real model.

Fault injection (`X-Stub-Fail`) and an oversized reply (`X-Stub-Bytes`) exist for the kind
cases that exercise them (K4, K5); they are unused by the cases this build makes pass (K1, K2,
K3, K6, K12) but are wired so the orchestrator's later K4/K5 tests need no stub change.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="aigw-stub")

_LATENCY_MS = float(os.environ.get("STUB_LATENCY_MS", "200"))

# Two ids the engine's builtin model registry already knows
# (`world/models/seeds/anthropic.py`) — declaring no custom model in url4.toml, the deployed
# world already routes both through this stub via `config.aigatewayBaseUrl` /
# `AIGATEWAY_BASE_URL`.
_MODELS = ["anthropic/claude-haiku-4-5", "anthropic/claude-sonnet-4-5"]


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models() -> dict[str, object]:
    return {"object": "list", "data": [{"id": model_id, "object": "model"} for model_id in _MODELS]}


def _usage_accounting(model: str) -> dict[str, object]:
    """The `_aigw` envelope — shaped to
    `apps/aigateway/src/aigateway/plugins/taxonomy/usage_accounting.schema.json`, read back by
    `world.accounting.read_aigw` / `usd_from_aigw`. `direct_cost_status: "unavailable"` prices
    the call at `None` (unpriced) rather than inventing a cost figure a stub has no basis for.
    """
    provider = model.split("/", 1)[0] if "/" in model else "anthropic"
    attempt = {
        "schema": "aigw.provider_attempt",
        "attempt_id": f"attempt_{uuid.uuid4().hex}",
        "sequence": 1,
        "dispatch_index": 1,
        "attempt_index": 1,
        "provider": provider,
        "requested_model": model,
        "response_model": model,
        "provider_response_id": f"stub_{uuid.uuid4().hex[:12]}",
        "transport": "litellm_async_http",
        "outcome": "succeeded",
        "http_status": 200,
        "latency_ms": int(_LATENCY_MS),
        "usage": {
            "status": "complete",
            "source": "provider_raw_response",
            "input": {
                "total": 10,
                "uncached": 10,
                "cache_read": 0,
                "cache_write": 0,
                "cache_write_by_ttl": [],
            },
            "output": {"total": 5, "reasoning": 0},
        },
        "pricing_context": {"service_tier": None, "backend": None},
        "direct_cost": {"status": "absent", "amount": None, "unit": None, "source": None},
        "provider_extensions": [],
        "provider_extensions_truncated": False,
        "redirect_hop_count": 0,
        "failure_code": None,
    }
    return {
        "usage_accounting": {
            "schema": "aigw.chat_usage_accounting",
            "capture_status": "complete",
            "gateway_call_id": f"call_{uuid.uuid4().hex}",
            "cache": {"status": "miss", "reference": None},
            "observed_attempts": 1,
            "rendered_attempts": 1,
            "omitted_attempts": 0,
            "attempts": [attempt],
        },
        "request_economics": {
            "schema": "aigw.request_economics",
            "observed_new_attempts": 1,
            "direct_cost_status": "unavailable",
            "known_direct_cost_subtotals": [],
        },
    }


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    x_stub_fail: str | None = Header(default=None, alias="X-Stub-Fail"),
    x_stub_bytes: str | None = Header(default=None, alias="X-Stub-Bytes"),
) -> JSONResponse:
    body = await request.json()
    model = str(body.get("model") or _MODELS[0])

    if x_stub_fail == "hang":
        # K5: the run's aigateway call never returns; the App's sync wait bounds at
        # `config.syncMaxWaitS` and the worker's own hard wall bounds the run itself.
        await asyncio.sleep(3600)
    await asyncio.sleep(_LATENCY_MS / 1000.0)

    if x_stub_fail == "429":
        return JSONResponse(
            status_code=429,
            content={"detail": {"code": "aigw_stub_rate_limited", "message": "stub: rate limited"}},
        )
    if x_stub_fail == "500":
        return JSONResponse(
            status_code=500,
            content={"detail": {"code": "aigw_stub_error", "message": "stub: internal error"}},
        )

    content = "stub answer"
    if x_stub_bytes:
        try:
            n = int(x_stub_bytes)
        except ValueError:
            n = 0
        if n > 0:
            # K4: a reply large enough that the mount route's 1 MiB inline limit spills it.
            content = "x" * n

    completion = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "refusal": None},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "_aigw": _usage_accounting(model),
    }
    return JSONResponse(status_code=200, content=completion)
