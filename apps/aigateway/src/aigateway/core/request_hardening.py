"""Shared chat-ingress hardening (OME-428, plan D6).

Mode-independent and provider-neutral: applied at the /v1/chat/completions
ingress for EVERY provider, after JSON parsing and body-shape validation but
before profile lookup, cache planning, or credential access.

``DISPATCH_CONTROL_FIELDS`` is the known LiteLLM control plane: fields that
redirect routing (``api_base``/``base_url``/``fallbacks``/``model_list`` are
credential-exfiltration vectors), smuggle credentials (``api_key``,
``headers``/``extra_headers``), disable safety (``ssl_verify``), forge accounting
(``*_cost_per_*``), or bend dispatch behavior (retry/mock/drop controls).
Stripping is silent in local mode — legitimate provider fields (OpenRouter
``provider``/``plugins``/``route``/``models``, tools, sampling params) pass
through untouched.

``timeout`` is deliberately NOT in the list: gemini/codex/antigravity consume
it as an ordinary dispatch parameter.

Pure functions only — no FastAPI types — so hosted-mode policy (Checkpoint B)
can compose the same primitives.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_CALLBACK_DYNAMIC_FIELDS: frozenset[str] = frozenset(
    {
        "langfuse_public_key",
        "langfuse_secret",
        "langfuse_secret_key",
        "langfuse_host",
        "langfuse_prompt_version",
        "langsmith_api_key",
        "langsmith_project",
        "langsmith_base_url",
        "langsmith_sampling_rate",
        "langsmith_tenant_id",
        "humanloop_api_key",
        "arize_api_key",
        "arize_space_key",
        "arize_space_id",
        "posthog_api_key",
        "posthog_host",
        "braintrust_api_key",
        "braintrust_project",
        "braintrust_host",
        "slack_webhook_url",
        "lunary_public_key",
        # WHY: litellm 1.95 added the Datadog dynamic-callback params. `dd_api_key` is a
        # caller-injectable credential and `dd_agent_host`/`dd_agent_port`/`dd_site`
        # redirect where prompt/response telemetry is shipped — the same exfiltration
        # category as the langfuse/arize/braintrust host+key fields above.
        # INVARIANT: every name in litellm's `_supported_callback_params` must appear
        # here, so a client can never turn a chat request into a telemetry redirect.
        # test_litellm_dynamic_callback_parameter_set_is_covered is what caught these on
        # the 1.87 -> 1.95 upgrade; it will catch the next batch the same way.
        "dd_api_key",
        "dd_agent_host",
        "dd_agent_port",
        "dd_site",
        # WHY: litellm 1.100 added `langfuse_environment` (a further Langfuse dynamic
        # param alongside the block above) plus a New Relic dynamic-callback trio for
        # per-team trace routing. `newrelic_api_key` is a caller-injectable credential
        # and `langfuse_environment`/`newrelic_region` redirect where prompt/response
        # telemetry is shipped — the same exfiltration category as the langfuse/arize/
        # braintrust/dd_* host+key fields above.
        # INVARIANT: every name in litellm's `_supported_callback_params` must appear
        # here, so a client can never turn a chat request into a telemetry redirect.
        # test_litellm_dynamic_callback_parameter_set_is_covered is what caught these on
        # the 1.97 -> 1.100 upgrade; it will catch the next batch the same way.
        "langfuse_environment",
        "newrelic_api_key",
        "newrelic_region",
        "turn_off_message_logging",
        # WHY here and not only in DISPATCH_CONTROL_FIELDS: this filter strips dynamic
        # callback controls from BOTH the top-level body and `metadata` symmetrically —
        # every other name in this set gets that treatment. `litellm_trusted_callback_vars`
        # is reserved for LiteLLM's own proxy to stamp (see DISPATCH_CONTROL_FIELDS'
        # comment); a caller nesting it under `metadata` instead of the top level should
        # not get a free pass just because it lives in the smaller set.
        "litellm_trusted_callback_vars",
        # WHY: LiteLLM 1.100 OTel routing trusts this proxy-owned auth container
        # for project/service selection. Caller metadata must never impersonate it.
        # Strip the whole value at both ingress locations, regardless of its shape.
        "user_api_key_auth_metadata",
    }
)

_CALLBACK_METADATA_HEADER_FIELDS: frozenset[str] = frozenset(
    {
        "litellm-disable-message-redaction",
        "litellm-enable-message-redaction",
        "x-litellm-enable-message-redaction",
    }
)

DISPATCH_CONTROL_FIELDS: frozenset[str] = frozenset(
    {
        "api_key",
        "api_base",
        "base_url",
        "headers",
        "extra_headers",
        "model_list",
        "fallbacks",
        "context_window_fallbacks",
        "context_window_fallback_dict",
        "content_policy_fallbacks",
        "extra_body",
        "drop_params",
        "additional_drop_params",
        "use_litellm_proxy",
        "custom_llm_provider",
        "deployment_id",
        "ssl_verify",
        "max_retries",
        "num_retries",
        "cooldown_time",
        "no-log",
        "mock_response",
        "mock_tool_calls",
        "mock_timeout",
        "mock_delay",
        "provider_specific_header",
        "input_cost_per_token",
        "output_cost_per_token",
        "input_cost_per_second",
        "output_cost_per_second",
        # SEC-1: provider/mode-flip flags — litellm 1.87.0 flips onto the azure
        # branch on `azure: true` (main.py:1398) and flips completion mode on
        # `text_completion`/`atext_completion` (main.py:1327-1328); same
        # category as the stripped custom_llm_provider/deployment_id.
        "azure",
        "text_completion",
        "atext_completion",
        # Blocker A (third review): caller-injectable litellm logging/observability
        # control-plane. A truthy `litellm_request_debug` makes litellm 1.87.0 log
        # the raw curl (request data/prompt) and raw response at WARNING — "in all
        # environments" (litellm_logging.py:1143-1168) — defeating the gateway
        # sanitizer. `verbose`/`logger_fn`/`litellm_logging_obj` are the sibling
        # logging hooks read straight from kwargs (main.py:1264-1267). Classified
        # by behavior, not name: none is an OpenRouter generation parameter, so a
        # legitimate provider-level option is never caught here.
        "litellm_request_debug",
        "verbose",
        "logger_fn",
        "litellm_logging_obj",
        # Request-level callbacks mutate process-global LiteLLM callback lists;
        # dynamic credentials/hosts can route prompt/response telemetry. Strip
        # selectors and parameters before any provider sees the body.
        "callbacks",
        "success_callback",
        "failure_callback",
        "litellm_params",
        "litellm_metadata",
        # WHY only LiteLLM's proxy may stamp this trusted credential container. Passing
        # caller data here bypasses LiteLLM's ordinary callback filtering — it now lives
        # in `_CALLBACK_DYNAMIC_FIELDS` below (splatted in) so it is stripped from both
        # the top-level body and `metadata`, not just the top level.
        *_CALLBACK_DYNAMIC_FIELDS,
    }
)


def strip_dispatch_controls(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new body without any LiteLLM control-plane field."""
    stripped = {key: value for key, value in body.items() if key not in DISPATCH_CONTROL_FIELDS}
    metadata = stripped.get("metadata")
    if isinstance(metadata, Mapping):
        # LiteLLM also resolves callback credentials/hosts from request
        # metadata. Preserve unrelated provider metadata in a fresh mapping.
        sanitized_metadata = {
            key: value for key, value in metadata.items() if key not in _CALLBACK_DYNAMIC_FIELDS
        }
        metadata_headers = sanitized_metadata.get("headers")
        if isinstance(metadata_headers, Mapping):
            sanitized_metadata["headers"] = {
                key: value
                for key, value in metadata_headers.items()
                if key not in _CALLBACK_METADATA_HEADER_FIELDS
            }
        stripped["metadata"] = sanitized_metadata
    return stripped


def chat_body_shape_error(body: object) -> str | None:
    """Validate the untrusted chat body shape; return an error message or None.

    Guarantees the route can never 500 on malformed input (plan D6): after
    this returns None, ``model`` is a str, ``messages`` is a list of dicts,
    and ``stream`` is absent or a real boolean.
    """
    if not isinstance(body, dict) or "model" not in body or "messages" not in body:
        return "model and messages are required"
    if not isinstance(body["model"], str):
        return "model must be a string"
    if not isinstance(body["messages"], list):
        return "messages must be a list"
    if any(not isinstance(message, dict) for message in body["messages"]):
        return "each message must be an object"
    # bool is checked with `is not` on type: `stream: 1` must not pass as truthy.
    if "stream" in body and type(body["stream"]) is not bool:
        return "stream must be a boolean"
    tools = body.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, Mapping) or tool.get("type") != "function":
                continue
            function = tool.get("function")
            name = function.get("name") if isinstance(function, Mapping) else None
            # INVARIANT: an accepted function tool must survive provider adaptation;
            # Gemini-family adapters deliberately skip nameless declarations.
            if not isinstance(name, str) or not name.strip():
                return "each function tool must include a non-empty function.name"
    response_format = body.get("response_format")
    if isinstance(response_format, Mapping) and response_format.get("type") == "json_schema":
        json_schema = response_format.get("json_schema")
        schema = json_schema.get("schema") if isinstance(json_schema, Mapping) else None
        # INVARIANT: LiteLLM omits Ollama's `format` when this schema is absent,
        # silently turning a structured-output request into free-form generation.
        if not isinstance(schema, Mapping):
            return "response_format.json_schema.schema must be an object"
    return None
