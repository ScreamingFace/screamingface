"""Caller data must never impersonate LiteLLM's proxy-stamped callback settings."""

from copy import deepcopy

import pytest
from litellm.litellm_core_utils.initialize_dynamic_callback_params import (
    get_trusted_callback_params,
    initialize_standard_callback_dynamic_params,
)

from aigateway.core.request_hardening import strip_dispatch_controls


@pytest.mark.parametrize(
    "envelope",
    [
        {"newrelic_api_key": "caller-key", "newrelic_region": "EU"},
        {"dd_api_key": "caller-key", "dd_site": "example.invalid"},
        {},
        None,
        "malformed",
        ["malformed"],
    ],
)
def test_ingress_removes_the_entire_trusted_callback_envelope(envelope) -> None:
    body = {
        "model": "anthropic/example",
        "messages": [{"role": "user", "content": "hello"}],
        "metadata": {"trace_id": "ordinary-metadata"},
        "litellm_trusted_callback_vars": envelope,
    }
    original = deepcopy(body)

    stripped = strip_dispatch_controls(body)

    assert stripped == {
        "model": body["model"],
        "messages": body["messages"],
        "metadata": body["metadata"],
    }
    assert body == original
    # WHY: LiteLLM trusts this internal container even when it rejects the same
    # credentials as ordinary callback fields. Test the real downstream consumer.
    assert get_trusted_callback_params(stripped) == ()
    assert initialize_standard_callback_dynamic_params(stripped) == {}


def test_ingress_removes_the_envelope_when_nested_under_metadata_too() -> None:
    """A caller can plant this under `metadata` instead of the top level.

    WHY this is a separate test from the parametrized one above: this field is stripped
    via `_CALLBACK_DYNAMIC_FIELDS`, which `strip_dispatch_controls` applies to BOTH the
    top-level body and `metadata` — unlike most of `DISPATCH_CONTROL_FIELDS`, which is
    only ever read from the top level. A caller nesting the same envelope one level
    deeper must not get a free pass just because it is not at the top.
    """
    body = {
        "model": "anthropic/example",
        "messages": [{"role": "user", "content": "hello"}],
        "metadata": {
            "trace_id": "ordinary-metadata",
            "litellm_trusted_callback_vars": {
                "newrelic_api_key": "caller-key",
                "newrelic_region": "EU",
            },
        },
    }
    original = deepcopy(body)

    stripped = strip_dispatch_controls(body)

    assert stripped["metadata"] == {"trace_id": "ordinary-metadata"}
    assert body == original
    assert get_trusted_callback_params(stripped["metadata"]) == ()
    assert initialize_standard_callback_dynamic_params(stripped["metadata"]) == {}
