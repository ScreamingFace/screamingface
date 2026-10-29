"""Phase 7c (OME-479 §4.4/§6.2): Hugging Face detail-contract observation overlay.

FEATURE: Hugging Face P0 observation overlay — the detailed /v1/model-parameters
document. Proves the composition the route performs (build_model_parameter_document
over the plugin's OWN rules + observations) surfaces every labelled-static chat
field with an honest gateway status, from NO network.

STORY: as an API consumer, I can see that HF accepts top_p even though the gateway
does not yet project it (visible-but-DISABLED), while temperature and max_tokens are
ENABLED — so I know exactly what I may send to a Hugging Face model.

INVARIANT (§4.4): an observation NEVER enables a field; only a rule does. An
observed-but-unruled field stays visible-but-rejected (projection_not_implemented).
INVARIANT: no network — the detail endpoint composes from labelled-static evidence.
"""

from __future__ import annotations

from typing import Any

from aigateway.core.auth_types import AuthType
from aigateway.core.model_parameter_contract import build_model_parameter_document
from aigateway.plugins.huggingface_provider.plugin import HuggingFaceProviderPlugin

_MODEL = "huggingface/openai/gpt-oss-120b:cerebras"


def _parameters(auth_mode: AuthType = "api_key") -> dict[str, Any]:
    # Mirrors routes/model_parameters.py: the SAME plugin hooks, the SAME composer —
    # only the profile resolution (auth_mode) is supplied directly.
    plugin = HuggingFaceProviderPlugin()
    document = build_model_parameter_document(
        canonical_id=_MODEL,
        gateway_provider="huggingface",
        auth_mode=auth_mode,
        scope="account_connection",
        context_identity="acct:test|prof:1",
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=auth_mode),
        observations=plugin.chat_parameter_observations(model=_MODEL, auth_type=auth_mode),
        tools=plugin.chat_parameter_tools(model=_MODEL, auth_type=auth_mode),
        transport=plugin.chat_transport_capabilities(model=_MODEL, auth_type=auth_mode),
        freshness={"stale": False, "degraded": False},
    )
    return document["parameters"]


def test_ruled_and_observed_standard_fields_are_enabled_with_evidence() -> None:
    params = _parameters()
    for path in ("temperature", "max_tokens"):
        entry = params[path]
        assert entry["gateway"]["status"] == "enabled"
        # carries the observation's evidence, not "unknown/none".
        assert entry["provider"]["support"] == "supported"
        assert entry["provider"]["source"] == "huggingface:static"


def test_observed_but_unruled_fields_are_visible_but_disabled() -> None:
    params = _parameters()
    # OME-585/586: seed, frequency_penalty and presence_penalty retired from this disabled
    # set — each is now ruled → enabled because the installed transform carries it (§9
    # proof); top_p remains observed-but-disabled (no such proof yet).
    for path in ("top_p",):
        entry = params[path]
        # accepted by the endpoint (observed) but no gateway rule → visible, rejected.
        assert entry["provider"]["support"] == "supported"
        assert entry["provider"]["source"] == "huggingface:static"
        assert entry["gateway"]["status"] == "disabled"
        assert entry["gateway"]["reason"] == "projection_not_implemented"


def test_stop_is_enabled_with_evidence() -> None:
    # OME-582: stop is now RULED → ENABLED, still carrying the observation's provenance.
    entry = _parameters()["stop"]
    assert entry["provider"]["support"] == "supported"
    assert entry["provider"]["source"] == "huggingface:static"
    assert entry["gateway"]["status"] == "enabled"


def test_every_observed_sampling_field_is_visible_with_a_status() -> None:
    params = _parameters()
    # "expose ALL provider params": each labelled-static field is visible with a
    # status — enabled when ruled, disabled-but-visible otherwise.
    for path in (
        "temperature",
        "max_tokens",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
        "seed",
        "stop",
    ):
        assert path in params, path


def test_sources_are_labelled_static_or_rule_only() -> None:
    # every param observation is labelled-local static evidence; none claims to be
    # a live catalog fetch (`huggingface:router`) or a fabricated per-model truth.
    params = _parameters()
    sources = {entry["provider"]["source"] for entry in params.values()}
    assert sources <= {"huggingface:static", "none"}


def test_native_top_k_is_absent_from_the_contract() -> None:
    # HF's transform has no top_k, so it is neither observed nor ruled — it must not
    # appear as a parameter at all (no fabricated native support).
    params = _parameters()
    assert "top_k" not in params
    assert "provider_params.top_k" not in params


# --- OME-583: function calling (tools + tool_choice) overlay -----------------
#
# FEATURE: first-class function calling. HF's router is OpenAI-compatible; the installed
# HuggingFaceChatConfig transform forwards tools[] and tool_choice (§9), so both are
# ENABLED and evidenced from the same labelled-static source.


def _document(auth_mode: AuthType = "api_key") -> dict[str, Any]:
    plugin = HuggingFaceProviderPlugin()
    return build_model_parameter_document(
        canonical_id=_MODEL,
        gateway_provider="huggingface",
        auth_mode=auth_mode,
        scope="account_connection",
        context_identity="acct:test|prof:1",
        rules=plugin.chat_parameter_rules(model=_MODEL, auth_type=auth_mode),
        observations=plugin.chat_parameter_observations(model=_MODEL, auth_type=auth_mode),
        tools=plugin.chat_parameter_tools(model=_MODEL, auth_type=auth_mode),
        transport=plugin.chat_transport_capabilities(model=_MODEL, auth_type=auth_mode),
        freshness={"stale": False, "degraded": False},
    )


def test_tools_and_tool_choice_are_enabled_with_evidence() -> None:
    params = _parameters()
    for path in ("tools", "tool_choice"):
        entry = params[path]
        assert entry["gateway"]["status"] == "enabled", path
        assert entry["provider"]["support"] == "supported", path
        assert entry["provider"]["source"] == "huggingface:static", path


def test_tools_section_reports_function_enabled() -> None:
    assert _document()["tools"] == {
        "function": {"provider_support": "supported", "gateway_status": "enabled"}
    }


# --- OME-584: structured output (response_format) overlay --------------------
#
# FEATURE: structured output. HF's router is OpenAI-compatible; the installed
# HuggingFaceChatConfig transform forwards response_format VERBATIM (§9 probe: both
# json_object and json_schema land on the wire unchanged), so it is ENABLED and evidenced
# from the same labelled-static source.


def test_response_format_is_enabled_with_evidence() -> None:
    entry = _parameters()["response_format"]
    assert entry["gateway"]["status"] == "enabled"
    # carries the observation's evidence, not "unknown/none".
    assert entry["provider"]["support"] == "supported"
    assert entry["provider"]["source"] == "huggingface:static"


# --- OME-585: seed + n sampling controls overlay -----------------------------
#
# FEATURE: seed (deterministic sampling) + n (number of choices). HF's router is
# OpenAI-compatible; the installed HuggingFaceChatConfig transform forwards both VERBATIM
# (§9 probe), so both are ENABLED and evidenced from the labelled-static source (seed via
# the sampling observation constant already present; n via a direct observation).


def test_seed_and_n_are_enabled_with_evidence() -> None:
    params = _parameters()
    for path in ("seed", "n"):
        entry = params[path]
        assert entry["gateway"]["status"] == "enabled", path
        assert entry["provider"]["support"] == "supported", path
        assert entry["provider"]["source"] == "huggingface:static", path


# --- OME-586: frequency_penalty + presence_penalty overlay -------------------
#
# FEATURE: repetition controls. HF's router is OpenAI-compatible; the installed
# HuggingFaceChatConfig transform forwards both penalties VERBATIM (§9 probe), so both are
# ENABLED and evidenced from the labelled-static source (both already in the sampling constant).


def test_frequency_and_presence_penalty_are_enabled_with_evidence() -> None:
    params = _parameters()
    for path in ("frequency_penalty", "presence_penalty"):
        entry = params[path]
        assert entry["gateway"]["status"] == "enabled", path
        assert entry["provider"]["support"] == "supported", path
        assert entry["provider"]["source"] == "huggingface:static", path


# --- OME-595: logprobs + top_logprobs overlay --------------------------------
#
# FEATURE: output introspection. HF's router is OpenAI-compatible; the installed
# HuggingFaceChatConfig transform forwards both fields VERBATIM (§9 probe), so both are
# ENABLED and evidenced from the labelled-static source (each newly added via a direct
# observation — neither was in the sampling constant before).


def test_logprobs_and_top_logprobs_are_enabled_with_evidence() -> None:
    params = _parameters()
    for path in ("logprobs", "top_logprobs"):
        entry = params[path]
        assert entry["gateway"]["status"] == "enabled", path
        assert entry["provider"]["support"] == "supported", path
        assert entry["provider"]["source"] == "huggingface:static", path
