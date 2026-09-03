"""OME-884 — the exact bytes direct OpenAI puts on the wire, characterized no-network.

FEATURE: one global exact-request cache (OME-305). ``prepared`` and
``GLOBAL_CACHE_ADAPTER_REVISION`` between them claim to describe every output-affecting
thing this boundary adds. A claim about the wire is only worth what a measurement of the
wire says, so this suite measures it.

INVARIANT under test: one POST to ``https://api.openai.com/v1/chat/completions``, the
selected account's key in ``Authorization``, no ``OpenAI-Organization`` and no
``OpenAI-Project`` header (the explicit condition that licenses cross-account replay), and
— for every one of the fourteen published models — the token-ceiling field spelled the way
this cache's rows were keyed.

WHY the token spelling is pinned MODEL BY MODEL with a written-down expectation rather than
a spelling-agnostic "one of the two": LiteLLM maps the ceiling to ``max_tokens`` for
GPT-4/4o and to ``max_completion_tokens`` for GPT-5/o-series, and an upgrade that moves
even one model between them changes the request without changing the key. A generic check
would stay green through exactly that.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import litellm
import pytest

from aigateway.plugins.openai_provider.plugin import PLUGIN

# Bound to the original private names so every relocated test body below reads unchanged.
from .dispatch_harness import SELECTED_KEY as _SELECTED_KEY
from .dispatch_harness import capture_client_factory as _capture_client_factory
from .dispatch_harness import completion_response as _completion_response


@pytest.mark.parametrize(
    ("model", "expected_token_field"),
    [
        ("openai/gpt-4o", "max_tokens"),
        ("openai/gpt-5.6-sol", "max_completion_tokens"),
        ("openai/gpt-5.6-terra", "max_completion_tokens"),
        ("openai/gpt-5.6-luna", "max_completion_tokens"),
    ],
)
@pytest.mark.asyncio
async def test_dispatch_pins_chat_completions_and_selected_account_context(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    expected_token_field: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_completion_response(model.split("/", 1)[1]))

    clients, constructor_kwargs, http_client = _capture_client_factory(monkeypatch, handler)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-ambient-wrong-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ambient.invalid/v1")
    monkeypatch.setenv("OPENAI_ORGANIZATION", "org-ambient")
    monkeypatch.setenv("OPENAI_ORG_ID", "org-ambient-fallback")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "proj-ambient")
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(litellm, "api_key", "sk-litellm-wrong-key")
    monkeypatch.setattr(litellm, "openai_key", "sk-litellm-openai-wrong-key")
    monkeypatch.setattr(litellm, "api_base", "https://litellm.invalid/v1")
    monkeypatch.setattr(litellm, "headers", None)
    monkeypatch.setattr(litellm, "route_all_chat_openai_to_responses", True)

    body = PLUGIN.prepare_chat_body(
        {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 7,
        }
    )
    body["api_key"] = _SELECTED_KEY

    result = await PLUGIN.chat_completion(body)
    # LiteLLM schedules best-effort success logging; let its queue drain before
    # pytest closes this parametrized case's event loop.
    await asyncio.sleep(0.05)

    assert result["choices"][0]["message"]["content"] == "ok"
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {_SELECTED_KEY}"
    assert "openai-organization" not in request.headers
    assert "openai-project" not in request.headers
    assert "x-ambient" not in request.headers
    payload = json.loads(request.content)
    assert payload["model"] == model.split("/", 1)[1]
    assert payload[expected_token_field] == 7
    assert ({"max_tokens", "max_completion_tokens"} - {expected_token_field}).isdisjoint(payload)
    assert "ssl_verify" not in payload
    assert _SELECTED_KEY not in request.content.decode()
    assert constructor_kwargs[0]["api_key"] == _SELECTED_KEY
    assert constructor_kwargs[0]["base_url"] == "https://api.openai.com/v1"
    assert constructor_kwargs[0]["max_retries"] == 0
    assert constructor_kwargs[0]["http_client"] is http_client
    assert clients[0].is_closed() is True


@pytest.mark.parametrize("model", [entry.model_name for entry in PLUGIN.register_models()])
@pytest.mark.asyncio
async def test_every_default_model_pins_its_token_field_at_the_final_http_wire(
    monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    """All fourteen seeds, at the wire — an adapter-revision input, not a nicety.

    INVARIANT (OME-884): ``max_tokens`` is KEYED, and LiteLLM decides on its own whether
    the ceiling reaches OpenAI as ``max_tokens`` (GPT-4/4o) or ``max_completion_tokens``
    (GPT-5/o-series). Both spellings mean one ceiling, so one key is correct — but only
    while the mapping is the one this revision was pinned against. A LiteLLM upgrade
    that moves a model between the two spellings changes what an unchanged request
    sends, and MUST bump ``GLOBAL_CACHE_ADAPTER_REVISION`` before rows are reused.

    WHY the wire and not the ``litellm.acompletion`` kwargs: the mapping happens INSIDE
    litellm, so the boundary above it shows ``max_tokens`` for every model and would
    pin nothing at all.
    """
    requests: list[httpx.Request] = []
    upstream = model.split("/", 1)[1]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_completion_response(upstream))

    _capture_client_factory(monkeypatch, handler)
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(litellm, "headers", None)

    body = PLUGIN.prepare_chat_body(
        {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 7}
    )
    body["api_key"] = _SELECTED_KEY
    await PLUGIN.chat_completion(body)
    await asyncio.sleep(0.05)

    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.openai.com/v1/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["model"] == upstream
    fields = {"max_tokens", "max_completion_tokens"} & set(payload)
    assert len(fields) == 1, (model, sorted(fields))
    assert payload[fields.pop()] == 7


# --- OME-884 review cycle 2: every seed's token spelling, written down ---------
#
# WHY an explicit table rather than the spelling-agnostic assertion beside it: that one
# proves exactly one of the two fields is present, which stays true when LiteLLM moves a
# model from one spelling to the other — the very upgrade that changes what an unchanged
# request sends and therefore MUST bump ``GLOBAL_CACHE_ADAPTER_REVISION``. Ten of the
# fourteen seeds had no committed expectation at all.
#
# INVARIANT: these expectations are OBSERVED FACTS about installed LiteLLM 1.97.0,
# captured at the final HTTP payload and written down by hand. They are deliberately NOT
# derived at runtime from the same litellm being tested — a table computed from the system
# under test asserts only that it agrees with itself.
_EXPECTED_TOKEN_FIELD: dict[str, str] = {
    "openai/gpt-5.6-sol": "max_completion_tokens",
    "openai/gpt-5.6-terra": "max_completion_tokens",
    "openai/gpt-5.6-luna": "max_completion_tokens",
    "openai/gpt-5.5": "max_completion_tokens",
    "openai/gpt-5.1": "max_completion_tokens",
    "openai/gpt-5": "max_completion_tokens",
    "openai/gpt-5-mini": "max_completion_tokens",
    "openai/gpt-5-nano": "max_completion_tokens",
    "openai/gpt-4.1": "max_tokens",
    "openai/gpt-4.1-mini": "max_tokens",
    "openai/gpt-4o": "max_tokens",
    "openai/gpt-4o-mini": "max_tokens",
    "openai/o3": "max_completion_tokens",
    "openai/o4-mini": "max_completion_tokens",
}


def test_the_token_field_table_covers_every_published_model() -> None:
    """A table that silently stopped covering a seed would prove nothing about it."""
    assert set(_EXPECTED_TOKEN_FIELD) == {entry.model_name for entry in PLUGIN.register_models()}


@pytest.mark.parametrize(("model", "expected_field"), sorted(_EXPECTED_TOKEN_FIELD.items()))
@pytest.mark.asyncio
async def test_each_default_model_sends_its_committed_token_field(
    monkeypatch: pytest.MonkeyPatch, model: str, expected_field: str
) -> None:
    """One seed, one committed spelling, asserted at the wire.

    A LiteLLM upgrade that moves ANY single model between ``max_tokens`` and
    ``max_completion_tokens`` fails here by name, which is the signal to re-verify the
    table and bump ``GLOBAL_CACHE_ADAPTER_REVISION`` before stored rows are reused.
    """
    requests: list[httpx.Request] = []
    upstream = model.split("/", 1)[1]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_completion_response(upstream))

    _capture_client_factory(monkeypatch, handler)
    monkeypatch.delenv("OPENAI_CUSTOM_HEADERS", raising=False)
    monkeypatch.setattr(litellm, "headers", None)

    body = PLUGIN.prepare_chat_body(
        {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 7}
    )
    body["api_key"] = _SELECTED_KEY
    await PLUGIN.chat_completion(body)
    await asyncio.sleep(0.05)

    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload["model"] == upstream
    other = ({"max_tokens", "max_completion_tokens"} - {expected_field}).pop()
    assert payload[expected_field] == 7, model
    assert other not in payload, (model, other)
