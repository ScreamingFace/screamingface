"""OME-1177: callers cannot impersonate proxy-owned telemetry configuration."""

from copy import deepcopy
from typing import cast

import pytest
from litellm.integrations.otel.model.metadata import auth_metadata
from litellm.litellm_core_utils.get_litellm_params import get_litellm_params
from litellm.types.utils import StandardLoggingPayload

from aigateway.core.parameter_projection import classify_and_project_chat_parameters
from aigateway.core.request_hardening import strip_dispatch_controls
from aigateway.plugins.anthropic_provider.plugin import AnthropicProviderPlugin


@pytest.mark.parametrize("location", ["body", "metadata"])
@pytest.mark.parametrize(
    "envelope",
    [
        {"phoenix_project_name": "caller-project"},
        {"phoenix_project_name_override": "caller-project", "otel_service_name": "caller"},
        {},
        None,
        "malformed",
        ["malformed"],
    ],
)
def test_reserved_auth_metadata_is_removed_before_projection_and_otel(location, envelope):
    body = {
        "model": "anthropic/claude-haiku-4-5",
        "messages": [{"role": "user", "content": "hello"}],
        "metadata": {"trace_id": "ordinary", "custom": {"label": "keep"}},
    }
    target = body if location == "body" else body["metadata"]
    target["user_api_key_auth_metadata"] = envelope
    original = deepcopy(body)

    stripped = strip_dispatch_controls(body)

    assert "user_api_key_auth_metadata" not in stripped
    assert stripped["metadata"] == {"trace_id": "ordinary", "custom": {"label": "keep"}}
    assert body == original
    # WHY: the direct LiteLLM handler is not the gateway boundary. Exercise its
    # parameter projection as well, so a rejection cannot be mistaken for a bypass.
    plugin = AnthropicProviderPlugin()
    projected = classify_and_project_chat_parameters(
        plugin.strip_provider_dispatch_controls(stripped),
        rules=plugin.chat_parameter_rules(model=body["model"], auth_type="api_key"),
        auth_mode="api_key",
    )
    prepared = plugin.prepare_chat_body(projected)
    params = get_litellm_params(metadata=prepared["metadata"])
    assert prepared["messages"] == original["messages"]
    assert prepared["metadata"] == {"trace_id": "ordinary", "custom": {"label": "keep"}}
    # INVARIANT: neither pre-call kwargs nor closed-call payload may supply
    # the new OTel reader with caller-controlled proxy auth configuration.
    assert auth_metadata(None, {"litellm_params": params}) is None
    # WHY: this reader only consumes metadata; omit unrelated logging fields
    # to verify it also handles a partial closed-call payload safely.
    payload = cast(StandardLoggingPayload, {"metadata": prepared["metadata"]})
    assert auth_metadata(payload, {}) is None
