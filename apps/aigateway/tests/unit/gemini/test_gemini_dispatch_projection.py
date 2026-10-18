"""Phase 9d (OME-479 §Phase 9 steps 4-5): Gemini dispatch capture — the wire proof.

FEATURE: Gemini P1 parameter projection, dispatch side. Every rule Phase 9 enabled
(temperature / top_p / max_tokens / the native top_k via provider_params.top_k) must
actually reach Google's wire body in BOTH dispatch shapes — the DIRECT
``generateContent`` body (api-key / generativelanguage) and the OAuth Code Assist
envelope (``request.generationConfig``). This is the "make it real" proof: a caller
request flows through the REAL classifier and the REAL ``plugin.chat_completion``
harvest into the REAL handler, and we capture the actual httpx request body — ONLY the
socket is faked (no reproduced pipeline, unlike the 9a helper).

STORY: as a caller on either a Gemini api-key or an OAuth (Code Assist) profile, the
temperature/top_p/max_tokens/top_k I send land in ``generationConfig`` on the wire, and
my chat messages become Gemini ``contents``.

INVARIANT (step 5): each enabled rule's projected value reaches ``generationConfig``
under BOTH auth modes; the OAuth path wraps the SAME inner body under ``request``, so
the inner ``generationConfig`` is byte-identical between the two paths (no fabricated
auth asymmetry — both call one builder).
INVARIANT (step 4): user/assistant messages project to Gemini ``contents``
(``[{role, parts:[{text}]}]``) and a system message to ``systemInstruction``; a
caller-forged ``contents`` field fails CLOSED at classification, before any dispatch.
INVARIANT (OME-582, end-to-end): ``stop`` is now RULED, so it reaches the wire as
``generationConfig.stopSequences`` under both auth modes — the ENABLED contract entry
genuinely means "reaches the wire", the dual of "observation never authorizes dispatch".
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

import aigateway.plugins.gemini_provider.plugin as plugin_module
from aigateway.core.auth_types import AuthType
from aigateway.core.parameter_projection import (
    UnsupportedParametersError,
    classify_and_project_chat_parameters,
)
from aigateway.plugins.gemini_provider.auth import GEMINI_PROFILE_HEADER
from aigateway.plugins.gemini_provider.chat_handler import (
    CODE_ASSIST_API_VERSION,
    CODE_ASSIST_ENDPOINT,
    GEMINI_API_BASE,
    GeminiCustomLLM,
)
from aigateway.plugins.gemini_provider.plugin import GeminiProviderPlugin

_MODEL = "gemini-cli/gemini-2.5-pro"
_MODEL_SLUG = "gemini-2.5-pro"

# One caller request exercising every enabled rule at once: the three OpenAI-standard
# sampling fields at their identity paths PLUS the provider-native top_k arriving under
# the provider_params wrapper (the only channel the native rule authorizes).
_TEMP, _TOP_P, _MAX, _TOP_K = 0.5, 0.9, 64, 40
# After classify → harvest → build_generate_content_body's config_map, those four land
# under their Gemini native names. Dict equality is order-insensitive.
_EXPECTED_GENERATION_CONFIG = {
    "temperature": _TEMP,
    "topP": _TOP_P,
    "maxOutputTokens": _MAX,
    "topK": _TOP_K,
}


def _http_factory(transport: httpx.MockTransport) -> Callable[[], httpx.AsyncClient]:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0))

    return factory


def _gemini_response(text: str = "pong") -> dict[str, Any]:
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}], "role": "model"}, "finishReason": "STOP"}
        ],
        "usageMetadata": {
            "promptTokenCount": 3,
            "candidatesTokenCount": 2,
            "totalTokenCount": 5,
        },
    }


def _caller_body(messages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "model": _MODEL,
        "messages": messages or [{"role": "user", "content": "ping"}],
        "temperature": _TEMP,
        "top_p": _TOP_P,
        "max_tokens": _MAX,
        "provider_params": {"top_k": _TOP_K},
    }


def _project(plugin: GeminiProviderPlugin, caller_body: dict[str, Any], auth_mode: AuthType):
    # The SAME call the route makes (routes/chat.py): the plugin's rule set for the REAL
    # auth mode, run against the CALLER body. Returns the fresh normalized dispatch body.
    return classify_and_project_chat_parameters(
        caller_body,
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=auth_mode),
        auth_mode=auth_mode,
    )


async def _dispatch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    caller_body: dict[str, Any],
    auth_mode: AuthType,
    handler_fn: Callable[[httpx.Request], httpx.Response],
    api_key: str | None = None,
    extra_headers: dict[str, Any] | None = None,
) -> None:
    """Run caller_body through the REAL classifier + REAL plugin.chat_completion into a
    handler whose ONLY fake is the httpx transport (handler_fn captures the wire body).

    Credential injection is a SEPARATE concern (its own tests); we model its OUTPUT by
    placing the resolved credential on the post-injection body exactly as the route's
    ``_inject_credentials`` would — api-key via env/handler, OAuth via ``api_key`` — so
    this test's boundary is honestly "post-injection body → wire".
    """
    plugin = GeminiProviderPlugin()
    dispatch_body = dict(_project(plugin, caller_body, auth_mode))
    if api_key is not None:
        dispatch_body["api_key"] = api_key
    if extra_headers is not None:
        dispatch_body["extra_headers"] = extra_headers
    fake = GeminiCustomLLM(http_client_factory=_http_factory(httpx.MockTransport(handler_fn)))
    monkeypatch.setattr(plugin_module, "get_litellm_gemini_handler", lambda: fake)
    await plugin.chat_completion(dispatch_body)


@pytest.mark.asyncio
async def test_api_key_dispatch_lands_every_enabled_rule_in_generation_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_gemini_response("from api key"))

    await _dispatch(
        monkeypatch, caller_body=_caller_body(), auth_mode="api_key", handler_fn=handler
    )

    # The DIRECT generativelanguage path: generationConfig at the body top level.
    assert captured["url"] == f"{GEMINI_API_BASE}/models/{_MODEL_SLUG}:generateContent"
    assert captured["headers"]["x-goog-api-key"] == "env-key"
    assert captured["payload"]["generationConfig"] == _EXPECTED_GENERATION_CONFIG
    # step 4: the caller message became a Gemini content turn.
    assert captured["payload"]["contents"] == [{"role": "user", "parts": [{"text": "ping"}]}]


@pytest.mark.asyncio
async def test_oauth_dispatch_lands_every_enabled_rule_in_wrapped_generation_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        calls.append({"url": str(request.url), "payload": payload})
        if str(request.url).endswith(f"/{CODE_ASSIST_API_VERSION}:loadCodeAssist"):
            return httpx.Response(200, json={"cloudaicompanionProject": "project-123"})
        return httpx.Response(
            200, json={"response": _gemini_response("from oauth"), "traceId": "t"}
        )

    await _dispatch(
        monkeypatch,
        caller_body=_caller_body(),
        auth_mode="oauth",
        handler_fn=handler,
        api_key="ya29.oauth",
        extra_headers={GEMINI_PROFILE_HEADER: "acct:default"},
    )

    generate = calls[-1]
    assert generate["url"] == f"{CODE_ASSIST_ENDPOINT}/{CODE_ASSIST_API_VERSION}:generateContent"
    # The OAuth Code Assist envelope wraps the SAME inner body under `request`.
    request_body = generate["payload"]["request"]
    assert request_body["generationConfig"] == _EXPECTED_GENERATION_CONFIG
    assert request_body["contents"] == [{"role": "user", "parts": [{"text": "ping"}]}]
    assert generate["payload"]["model"] == _MODEL_SLUG
    assert generate["payload"]["project"] == "project-123"


@pytest.mark.asyncio
async def test_both_paths_emit_identical_inner_generation_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The "no fabricated auth asymmetry" payoff at the WIRE: because both dispatch paths
    # call one build_generate_content_body, the inner generationConfig is byte-identical.
    direct: dict[str, Any] = {}
    wrapped: dict[str, Any] = {}

    def api_key_handler(request: httpx.Request) -> httpx.Response:
        direct.update(json.loads(request.content.decode())["generationConfig"])
        return httpx.Response(200, json=_gemini_response())

    def oauth_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if str(request.url).endswith(f"/{CODE_ASSIST_API_VERSION}:loadCodeAssist"):
            return httpx.Response(200, json={"cloudaicompanionProject": "p"})
        wrapped.update(payload["request"]["generationConfig"])
        return httpx.Response(200, json={"response": _gemini_response()})

    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    await _dispatch(
        monkeypatch, caller_body=_caller_body(), auth_mode="api_key", handler_fn=api_key_handler
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    await _dispatch(
        monkeypatch,
        caller_body=_caller_body(),
        auth_mode="oauth",
        handler_fn=oauth_handler,
        api_key="ya29.oauth",
        extra_headers={GEMINI_PROFILE_HEADER: "acct:default"},
    )

    assert direct == wrapped == _EXPECTED_GENERATION_CONFIG


@pytest.mark.asyncio
async def test_system_and_turns_project_to_contents_and_system_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # step 4 in full: a system message becomes systemInstruction; user/assistant turns
    # become ordered `contents` with Gemini roles (assistant -> model).
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode()))
        return httpx.Response(200, json=_gemini_response())

    messages = [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "bye"},
    ]
    await _dispatch(
        monkeypatch, caller_body=_caller_body(messages), auth_mode="api_key", handler_fn=handler
    )

    assert captured["systemInstruction"] == {"parts": [{"text": "be terse"}]}
    assert captured["contents"] == [
        {"role": "user", "parts": [{"text": "hi"}]},
        {"role": "model", "parts": [{"text": "hello"}]},
        {"role": "user", "parts": [{"text": "bye"}]},
    ]


def test_caller_supplied_contents_fails_closed_before_any_dispatch() -> None:
    # step 4 negative, at the DISPATCH gate: a caller cannot forge the provider-native
    # `contents` field to smuggle raw turns past the builder — it is unknown to the rule
    # set and rejected at classification, so chat_completion is never reached. (9a proves
    # the same rejection at the classifier-unit level; here it is the dispatch entry.)
    plugin = GeminiProviderPlugin()
    body = _caller_body()
    body["contents"] = "forged"
    with pytest.raises(UnsupportedParametersError) as exc:
        _project(plugin, body, "api_key")
    assert exc.value.rejected.get("contents") == "unknown"


@pytest.mark.asyncio
async def test_stop_reaches_the_wire_as_stop_sequences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # OME-582 end-to-end payoff: stop is now RULED, so a caller stop array flows through
    # the REAL classifier + plugin.chat_completion and lands on Gemini's wire body as
    # generationConfig.stopSequences — the dispatch teeth behind the enabled overlay.
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_gemini_response())

    body = _caller_body()
    body["stop"] = ["\n\n", "END"]
    await _dispatch(monkeypatch, caller_body=body, auth_mode="api_key", handler_fn=handler)

    assert captured["payload"]["generationConfig"]["stopSequences"] == ["\n\n", "END"]


# --- OME-583 (§9): tools reach the wire as functionDeclarations; tool_choice fails closed --

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather for a city",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        },
    }
]


@pytest.mark.asyncio
async def test_tools_reach_the_wire_as_function_declarations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # OME-583 end-to-end: a caller tools[] flows through the REAL classifier +
    # plugin.chat_completion and lands on Gemini's wire body as tools[].functionDeclarations
    # (build_generate_content_body maps the OpenAI tool onto Gemini's shape).
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_gemini_response())

    body = _caller_body()
    body["tools"] = _TOOLS
    await _dispatch(monkeypatch, caller_body=body, auth_mode="api_key", handler_fn=handler)

    declarations = captured["payload"]["tools"][0]["functionDeclarations"]
    assert declarations[0]["name"] == "get_weather"


def test_tool_choice_fails_closed_because_gemini_does_not_support_it() -> None:
    # §9: Gemini's builder emits no toolConfig, so tool_choice is intentionally UNRULED.
    # A caller tool_choice is unknown to the rule set and rejected at classification,
    # before any dispatch — the gateway never forwards a control it cannot honor.
    plugin = GeminiProviderPlugin()
    body = _caller_body()
    body["tools"] = _TOOLS
    body["tool_choice"] = "auto"
    with pytest.raises(UnsupportedParametersError) as exc:
        _project(plugin, body, "api_key")
    assert exc.value.rejected.get("tool_choice") == "unknown"


# --- OME-584 (§9): response_format is EXCLUDED on Gemini -----------------------


def test_response_format_fails_closed_because_gemini_has_no_wire_home() -> None:
    # §9: build_generate_content_body renders no response_format field (only
    # temperature/top_p/max_tokens/top_k/stop/tools), so it is intentionally UNRULED. A
    # caller response_format is unknown to the rule set and rejected at classification,
    # before any dispatch — the exclusion is pinned by a test, not silent omission.
    plugin = GeminiProviderPlugin()
    body = _caller_body()
    body["response_format"] = {"type": "json_object"}
    with pytest.raises(UnsupportedParametersError) as exc:
        _project(plugin, body, "api_key")
    assert exc.value.rejected.get("response_format") == "unknown"


# --- OME-585 (§9): seed + n are EXCLUDED on Gemini -----------------------------


def test_seed_and_n_fail_closed_because_gemini_has_no_wire_home() -> None:
    # §9: build_generate_content_body renders no seed/n field (only temperature/top_p/
    # max_tokens/top_k/stop/tools), so both are intentionally UNRULED. A caller seed or n
    # is unknown to the rule set and rejected at classification, before any dispatch — the
    # exclusion is pinned by a test, not silent omission.
    plugin = GeminiProviderPlugin()
    for path, value in (("seed", 42), ("n", 3)):
        body = _caller_body()
        body[path] = value
        with pytest.raises(UnsupportedParametersError) as exc:
            _project(plugin, body, "api_key")
        assert exc.value.rejected.get(path) == "unknown"


# --- OME-586 (§9): frequency_penalty + presence_penalty are EXCLUDED on Gemini --


def test_penalties_fail_closed_because_gemini_builder_renders_neither() -> None:
    # §9: build_generate_content_body's config_map renders only max_tokens/temperature/
    # top_p/top_k (+ stop/tools) — neither penalty has a wire home, so both are intentionally
    # UNRULED. A caller value is unknown to the rule set and rejected at classification,
    # before any dispatch — the exclusion is pinned by a test, not silent omission.
    plugin = GeminiProviderPlugin()
    for path in ("frequency_penalty", "presence_penalty"):
        body = _caller_body()
        body[path] = 0.5
        with pytest.raises(UnsupportedParametersError) as exc:
            _project(plugin, body, "api_key")
        assert exc.value.rejected.get(path) == "unknown"


# --- OME-595 (§9): logprobs + top_logprobs are EXCLUDED on Gemini ------------


def test_logprobs_fail_closed_because_gemini_builder_renders_neither() -> None:
    # §9: build_generate_content_body's config_map renders only max_tokens/temperature/
    # top_p/top_k (+ stop/tools) — neither logprobs field has a wire home, so both are
    # intentionally UNRULED. A caller value is unknown to the rule set and rejected at
    # classification, before any dispatch — the exclusion is pinned by a test, not silent.
    plugin = GeminiProviderPlugin()
    for path, value in (("logprobs", True), ("top_logprobs", 5)):
        body = _caller_body()
        body[path] = value
        with pytest.raises(UnsupportedParametersError) as exc:
            _project(plugin, body, "api_key")
        assert exc.value.rejected.get(path) == "unknown"
