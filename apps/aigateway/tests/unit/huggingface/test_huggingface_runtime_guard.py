"""OME-791 (B2, M1, M2, M5, M8) — the Hugging Face ambient-state guard.

FEATURE: one globally shared exact-request cache (OME-305). A row is replayed to any caller
whose request keys identically, so sharing is only safe while this process will actually send
what the projection claims. ``runtime_guard`` is that certification; this file is its contract.

STORY: as an operator I flip a LiteLLM process global — a proxy switch, a stop-limit override, a
schema validator — and Hugging Face stops sharing rows, instead of quietly storing answers that
do not match their key.

What these tests pin, and why each earns its place:
- every guarded litellm global still EXISTS (M8). ``raising=False`` previously let a renamed or
  deleted attribute be silently CREATED by the test, so the guard could stop protecting anything
  while the suite stayed green. Drift must be red, not invisible.
- BOTH LiteLLM Proxy controls (B2). litellm consults the environment secret FIRST and returns on
  it alone, so guarding only the module attribute leaves a live reroute unguarded.
- each positive control is proven to change REAL DISPATCH, not merely to be a variable this
  repository decided to fear.
- ``disable_stop_sequence_limit`` (M1) and ``enable_json_schema_validation`` (M2), each shown to
  change behaviour behind an UNCHANGED request body — the precise shape of hazard a cache key
  cannot see.

AIDEV-NOTE: the expected inventory below is authored INDEPENDENTLY of the production tuples and
compared against them (M8). Deriving it from ``runtime_guard`` would make the conformance test
tautological: production could drop a field and its own test would agree.
"""

from __future__ import annotations

import inspect
from typing import Any

import litellm
import pytest

from aigateway.plugins.huggingface_provider import runtime_guard
from aigateway.plugins.huggingface_provider.plugin import HuggingFaceProviderPlugin
from aigateway.plugins.huggingface_provider.settings import HuggingFacePluginSettings

_PINNED = "huggingface/deepseek-ai/DeepSeek-R1:novita"

# --- independently authored expectations (M8) ---------------------------------------------
#
# Hand-written from the hazards this provider claims to guard. NOT imported from production.
_EXPECTED_DISPATCH_GLOBALS = (
    "model_fallbacks",
    "model_alias_map",
    "headers",
    "use_litellm_proxy",
    "disable_stop_sequence_limit",
    "enable_json_schema_validation",
)
_EXPECTED_RULE_GLOBALS = ("pre_call_rules", "post_call_rules", "drop_params")
_EXPECTED_PRESENCE_GLOBALS = ("proxy_auth",)
_EXPECTED_CALLBACK_GLOBALS = (
    "callbacks",
    "input_callback",
    "success_callback",
    "failure_callback",
    "_async_input_callback",
    "_async_success_callback",
    "_async_failure_callback",
)
_EXPECTED_GUARDED = (
    _EXPECTED_DISPATCH_GLOBALS
    + _EXPECTED_RULE_GLOBALS
    + _EXPECTED_PRESENCE_GLOBALS
    + _EXPECTED_CALLBACK_GLOBALS
)

# A truthy value per guarded field, chosen to be representative of a real deployment setting.
_TRUTHY_VALUE: dict[str, Any] = {
    "model_fallbacks": ["openai/gpt-4o"],
    "model_alias_map": {"x": "y"},
    "headers": {"x-tenant": "acme"},
    "use_litellm_proxy": True,
    "disable_stop_sequence_limit": True,
    "enable_json_schema_validation": True,
    "pre_call_rules": [lambda _: True],
    "post_call_rules": [lambda _: True],
    "drop_params": True,
}


def _plugin(**settings: Any) -> HuggingFaceProviderPlugin:
    """A FRESH plugin instance, so one test's settings cannot leak into another."""
    return HuggingFaceProviderPlugin(HuggingFacePluginSettings(**settings))


@pytest.fixture(autouse=True)
def _quiet_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutral ambient state, and a decline memo that cannot leak between tests.

    WHY autouse: several of these tests assert PARTICIPATION, which any leftover global from a
    sibling test would silently falsify into a pass-looking decline.
    """
    monkeypatch.delenv(runtime_guard.PROXY_SECRET_NAME, raising=False)
    runtime_guard.reset_decline_log()


# --- M8: the inventory is real, complete, and fails on drift --------------------------------


def test_every_guarded_global_exists_on_litellm() -> None:
    # INVARIANT: a guard that reads a non-existent attribute protects nothing while reading like
    # coverage. ``getattr(litellm, field, None)`` returns None for a typo just as it does for an
    # unset global, so only an existence assertion can tell the two apart.
    missing = [
        field for field in runtime_guard.GUARDED_LITELLM_GLOBALS if not hasattr(litellm, field)
    ]

    assert missing == [], f"litellm no longer defines: {missing}"


def test_the_production_inventory_matches_the_independently_authored_one() -> None:
    # Set equality in BOTH directions: an addition to production that nobody reviewed is as much
    # a finding as a removal. This is the test that would have caught ``additional_drop_params``.
    assert set(runtime_guard.GUARDED_LITELLM_GLOBALS) == set(_EXPECTED_GUARDED)
    assert len(runtime_guard.GUARDED_LITELLM_GLOBALS) == len(_EXPECTED_GUARDED), "duplicate entry"


def test_additional_drop_params_is_not_a_litellm_module_global() -> None:
    # M8's original finding, pinned so it cannot be re-added by memory. It is a per-request
    # kwarg, never a module global; guarding it was a no-op that survived only because the old
    # test used ``raising=False`` and CREATED the attribute it claimed to check.
    assert not hasattr(litellm, "additional_drop_params")
    assert "additional_drop_params" not in runtime_guard.GUARDED_LITELLM_GLOBALS


def test_monkeypatching_a_misspelled_global_now_fails_instead_of_creating_it() -> None:
    # The falsification for M8: this is the exact mechanism that used to hide drift. With
    # ``raising=True`` a guarded name that litellm removed becomes an AttributeError — a red
    # test — rather than a freshly invented attribute that makes the guard look alive.
    with pytest.MonkeyPatch.context() as patch:
        with pytest.raises(AttributeError):
            patch.setattr(litellm, "model_fallbacks_typo", ["x"], raising=True)


# --- the guarded conditions, one test per declared hazard ------------------------------------


@pytest.mark.parametrize("field", _EXPECTED_DISPATCH_GLOBALS + _EXPECTED_RULE_GLOBALS)
def test_a_truthy_guarded_global_declines_participation(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(litellm, field, _TRUTHY_VALUE[field], raising=True)

    assert _plugin().participates_in_global_cache() is False


@pytest.mark.parametrize("field", _EXPECTED_PRESENCE_GLOBALS)
def test_a_present_guarded_global_declines_participation(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Guarded on PRESENCE, not truthiness: a configured-but-falsy auth object still means a proxy
    # auth path is wired up.
    monkeypatch.setattr(litellm, field, object(), raising=True)

    assert _plugin().participates_in_global_cache() is False


@pytest.mark.parametrize("field", _EXPECTED_CALLBACK_GLOBALS)
def test_every_callback_field_declines_including_the_async_ones(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY the async fields matter as much as ``success_callback``: an observer registered on an
    # async hook sees exactly the dispatches a cache hit skips, so a row filled under one
    # observer configuration is not equivalent to one filled under another.
    monkeypatch.setattr(litellm, field, ["langfuse"], raising=True)

    assert _plugin().participates_in_global_cache() is False


@pytest.mark.parametrize("field", _EXPECTED_CALLBACK_GLOBALS)
def test_the_cache_callback_exemption_is_preserved_on_every_callback_field(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``"cache"`` is litellm's own bookkeeping entry, not a third-party observer. Declining on it
    # would decline in ordinary deployments, which is a silent loss of the whole feature.
    monkeypatch.setattr(litellm, field, [runtime_guard.EXEMPT_CALLBACK], raising=True)

    assert _plugin().participates_in_global_cache() is True


def test_a_clean_process_participates() -> None:
    # The mirror of every decline above: without this, they could all pass vacuously.
    assert _plugin().participates_in_global_cache() is True


# --- B2: BOTH LiteLLM Proxy controls ---------------------------------------------------------


def test_the_module_attribute_proxy_switch_declines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "use_litellm_proxy", True, raising=True)

    assert _plugin().participates_in_global_cache() is False


def test_the_environment_proxy_switch_declines_while_the_attribute_stays_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # THE B2 ESCALATION, and the reason an attribute-only guard was insufficient:
    # ``_should_use_litellm_proxy_by_default`` checks ``get_secret_bool("USE_LITELLM_PROXY")``
    # FIRST (``llms/litellm_proxy/chat/transformation.py:73``) and returns True on it alone.
    monkeypatch.setattr(litellm, "use_litellm_proxy", False, raising=True)
    monkeypatch.setenv(runtime_guard.PROXY_SECRET_NAME, "true")

    assert litellm.use_litellm_proxy is False, (
        "the attribute must stay false for this to mean anything"
    )
    assert _plugin().participates_in_global_cache() is False


@pytest.mark.parametrize("value", ["false", "0", ""])
def test_a_falsey_environment_proxy_value_does_not_decline(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The guard must narrow participation, not abolish it. A present-but-off switch is off.
    monkeypatch.setenv(runtime_guard.PROXY_SECRET_NAME, value)

    assert _plugin().participates_in_global_cache() is True


def test_an_absent_environment_proxy_value_does_not_decline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(runtime_guard.PROXY_SECRET_NAME, raising=False)

    assert _plugin().participates_in_global_cache() is True


@pytest.mark.parametrize("control", ["attribute", "environment"])
def test_each_proxy_control_really_reroutes_dispatch(
    control: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each guarded control protects a REAL routing change, not an inert variable.

    INVARIANT: this is what separates a guard from superstition. If the flag did not move
    dispatch off ``router.huggingface.co``, declining on it would be unjustified caution — and
    the reviewer's question "does this actually do anything?" would have no answer in the suite.
    """
    assert litellm.get_llm_provider(model=_PINNED)[1] == "huggingface"

    if control == "attribute":
        monkeypatch.setattr(litellm, "use_litellm_proxy", True, raising=True)
    else:
        monkeypatch.setattr(litellm, "use_litellm_proxy", False, raising=True)
        monkeypatch.setenv(runtime_guard.PROXY_SECRET_NAME, "true")

    # The provider litellm would actually dispatch to is no longer Hugging Face, so the projected
    # ``api_base`` would describe an endpoint the request never reached.
    assert litellm.get_llm_provider(model=_PINNED)[1] == "litellm_proxy"
    assert _plugin().participates_in_global_cache() is False


def test_an_unreadable_proxy_secret_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``get_secret`` can reach a configured key-management system, so it may raise. An unknown
    # answer must decline: the cache is the thing that gives way, never the request.
    def _explode(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("secret backend unavailable")

    monkeypatch.setattr(runtime_guard, "get_secret_bool", _explode, raising=True)

    assert _plugin().participates_in_global_cache() is False


def test_an_unreadable_litellm_global_declines_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ExplodingTruthiness:
        def __bool__(self) -> bool:
            raise RuntimeError("ambient global is unreadable")

    monkeypatch.setattr(litellm, "headers", _ExplodingTruthiness(), raising=True)

    assert _plugin().participates_in_global_cache() is False


# --- M1: disable_stop_sequence_limit changes the WIRE while the body stays identical ----------


def test_the_stop_limit_flag_changes_the_final_wire_value_for_an_unchanged_body() -> None:
    """The hazard M1 names: same caller body, same cache key, different upstream call.

    ``litellm.utils.validate_openai_optional_params`` truncates a ``stop`` list to four entries
    unless ``disable_stop_sequence_limit`` is set (``utils.py:7618-7622``). Nothing about the
    request distinguishes the two processes, so a row filled by one is served to the other.
    """
    caller_stop = ["a", "b", "c", "d", "e", "f"]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(litellm, "disable_stop_sequence_limit", False, raising=True)
        truncated = litellm.utils.validate_openai_optional_params(stop=list(caller_stop))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(litellm, "disable_stop_sequence_limit", True, raising=True)
        untruncated = litellm.utils.validate_openai_optional_params(stop=list(caller_stop))

    assert truncated == ["a", "b", "c", "d"]
    assert untruncated == caller_stop
    assert truncated != untruncated, "the flag must change the wire value for this guard to matter"
    # The caller's body never changed — which is exactly why the key cannot see this.
    assert caller_stop == ["a", "b", "c", "d", "e", "f"]


def test_the_stop_limit_flag_governs_participation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "disable_stop_sequence_limit", False, raising=True)
    assert _plugin().participates_in_global_cache() is True

    monkeypatch.setattr(litellm, "disable_stop_sequence_limit", True, raising=True)
    assert _plugin().participates_in_global_cache() is False


# --- M2: enable_json_schema_validation governs acceptance of a KEYED response_format ----------


def test_json_schema_validation_accepts_and_refuses_a_keyed_response_format() -> None:
    """M2's hazard: ``response_format`` is KEYED by this provider, and a hit skips this check.

    ``utils.py:1198`` runs ``validate_schema`` only when the flag is on, AFTER dispatch. A cache
    hit returns at ``routes/chat.py:351`` — before any of it — so a row stored by a process with
    validation off would be replayed, unvalidated, to a process that switched it on.
    """
    from litellm.litellm_core_utils.json_validation_rule import validate_schema

    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}

    assert validate_schema(schema=schema, response='{"n": 1}') is None
    with pytest.raises(Exception, match="JSONSchemaValidationError|does not match"):
        validate_schema(schema=schema, response='{"n": "not-an-integer"}')


def test_the_json_schema_validation_flag_governs_participation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(litellm, "enable_json_schema_validation", False, raising=True)
    assert _plugin().participates_in_global_cache() is True

    monkeypatch.setattr(litellm, "enable_json_schema_validation", True, raising=True)
    assert _plugin().participates_in_global_cache() is False


# --- structural guarantees --------------------------------------------------------------------


def test_the_guard_cannot_read_caller_identity_or_credentials() -> None:
    # INVARIANT: identity is STRUCTURALLY absent, not merely unused. The guard's only input is a
    # deployment-local URL, so no account, profile, auth mode or credential is expressible —
    # which is what keeps participation a local yes/no that never varies by caller.
    parameters = inspect.signature(runtime_guard.global_cache_decline_reason).parameters

    assert list(parameters) == ["configured_router_api_base"]
    assert inspect.signature(runtime_guard.unsafe_litellm_global_state).parameters == {}


def test_a_decline_logs_the_token_and_never_the_configured_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_base = "https://internal-proxy.corp.example/v1"
    runtime_guard.reset_decline_log()

    with caplog.at_level("WARNING"):
        assert _plugin(router_api_base=secret_base).participates_in_global_cache() is False

    messages = [record.getMessage() for record in caplog.records]
    assert any(runtime_guard.ROUTER_API_BASE_REASON in message for message in messages)
    assert all(secret_base not in message for message in messages)


def test_the_decline_log_is_once_per_condition_not_once_per_process(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two DIFFERENT conditions must both be reported.

    A memo keyed on "have we logged at all" would report the first decline and hide every later
    one — leaving an operator who fixed the first condition with no signal about the second.
    """
    runtime_guard.reset_decline_log()

    with caplog.at_level("WARNING"):
        for _ in range(3):
            _plugin(router_api_base="https://proxy.internal/v1").participates_in_global_cache()
        monkeypatch.setattr(litellm, "model_fallbacks", ["openai/gpt-4o"], raising=True)
        for _ in range(3):
            _plugin().participates_in_global_cache()

    declines = [r.getMessage() for r in caplog.records if "global cache" in r.getMessage()]
    assert len(declines) == 2, declines
    assert any(runtime_guard.ROUTER_API_BASE_REASON in m for m in declines)
    assert any("litellm.model_fallbacks" in m for m in declines)
