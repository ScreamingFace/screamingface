"""OME-782/OME-787 — tool-bearing requests are cacheable, opt-in per provider.

FEATURE: ``tools``/``tool_choice`` presence used to bypass the global cache
unconditionally (OME-305 plan §1.3). An owner decision (D1) lifted the
STRUCTURAL carve-out: a cached entry represents ONE model call, and a tool
RESULT the caller sends back arrives in ``messages``, which is hashed
verbatim — so a differing tool result already yields a differing key. There
is nothing left for a blanket presence bypass to protect.

A second owner decision (OME-787) then scoped the ROLLOUT: whether
``tools``/``tool_choice`` actually key is now an ordinary per-provider
``cache_behavior`` choice, defaulted to ``"bypass"`` in
``function_calling_rules`` — a provider is promoted to ``"keyed"`` only once
its ``global_cache_projection`` can back the rule. This file exercises a
FABRICATED provider that has opted in (passes ``cache_behavior="keyed"``,
mirroring the one real provider that has today: OpenRouter).

STORY: as a benchmark operator I re-run the identical tool-bearing request —
same tools, same order, same choice — against a provider that has opted in,
from a second account, and the second call is answered from the first one's
stored response.

INVARIANT under test: an OPTED-IN provider's declared function-calling rules
govern whether ``tools``/``tool_choice`` key or bypass, exactly like any
other parameter — there is no longer a structural carve-out for their mere
presence. ``metadata`` keeps its own, unrelated, presence bypass (untouched
by D1) even on a request that also carries tools. A provider that has NOT
opted in keeps bypassing tools, via the ordinary declared-bypass path.

AIDEV-NOTE: copies the ``_build``/``_hash``/``_reason`` harness from
test_global_cache_key.py verbatim rather than importing it — that module's
helpers are private to it.
"""

from __future__ import annotations

from typing import Any

from aigateway.core.auth_types import AuthMode
from aigateway.core.chat_parameters import (
    ParameterProjectionRule,
    ParameterSchema,
    ToolCapability,
)
from aigateway.core.request_cache.global_eligibility import BYPASS_DECLARED
from aigateway.core.request_cache.global_keys import (
    CacheBypass,
    GlobalCacheKeyResult,
    build_global_cache_key,
)
from aigateway.core.standard_parameters import direct_rule, function_calling_rules

_AUTH: tuple[AuthMode, ...] = ("api_key",)
_REVISION = "rule-r1"
_CONTRACT_REVISION = "pc-1"
_ADAPTER_REVISION = "pa-1"

_TEMPERATURE_SCHEMA = ParameterSchema(type="number", minimum=0, maximum=2)

_PROVIDER = "fake"
_MODEL = "fake/m"
_MESSAGES = [{"role": "user", "content": "hi"}]

# A fabricated provider that has enabled exactly one tool type — "function" —
# through the gateway. ``provider_support="supported"`` + ``gateway_status="enabled"``
# is what makes ``supported_tool_types`` (and therefore ``function_calling_rules``)
# report it.
_FUNCTION_TOOL = ToolCapability(
    tool_type="function", provider_support="supported", gateway_status="enabled"
)


def _ordinary_rule() -> ParameterProjectionRule:
    """A plain keyed rule, so a tool-bearing body is otherwise cacheable."""
    return direct_rule(
        "temperature",
        auth_modes=_AUTH,
        projection_revision=_REVISION,
        cache_behavior="keyed",
        schema=_TEMPERATURE_SCHEMA,
    )


# The rule set for a provider that DOES declare function calling AND has opted
# it into caching (``cache_behavior="keyed"`` — the argument now REQUIRED to get
# anything but the default ``"bypass"``), plus one ordinary rule.
_RULES: tuple[ParameterProjectionRule, ...] = (
    *function_calling_rules(
        (_FUNCTION_TOOL,),
        auth_modes=_AUTH,
        projection_revision=_REVISION,
        cache_behavior="keyed",
    ),
    _ordinary_rule(),
)

# The rule set for a provider that declares the SAME function-calling
# capability but has NOT opted in — the default ``cache_behavior="bypass"``.
_UNPROMOTED_RULES: tuple[ParameterProjectionRule, ...] = (
    *function_calling_rules(
        (_FUNCTION_TOOL,),
        auth_modes=_AUTH,
        projection_revision=_REVISION,
    ),
    _ordinary_rule(),
)


def _projection(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
    """A pure, deterministic stand-in for a provider's own projection."""
    model = body["model"]
    return {
        "resolved_model": model.split("/", 1)[1],
        "provider_adapter_revision": _ADAPTER_REVISION,
        "prepared": {},
    }


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"model": _MODEL, "messages": [dict(m) for m in _MESSAGES]}
    body.update(overrides)
    return body


def _build(
    body: dict[str, Any] | None = None,
    *,
    provider: str = _PROVIDER,
    rules: tuple[ParameterProjectionRule, ...] = _RULES,
    projection: Any = _projection,
    provider_auth_modes: tuple[str, ...] = _AUTH,
    parameter_contract_revision: str = _CONTRACT_REVISION,
) -> GlobalCacheKeyResult | CacheBypass:
    return build_global_cache_key(
        provider=provider,
        body=_body() if body is None else body,
        rules=rules,
        projection=projection,
        provider_auth_modes=provider_auth_modes,
        parameter_contract_revision=parameter_contract_revision,
    )


def _hash(body: dict[str, Any] | None = None, **kwargs: Any) -> str:
    built = _build(body, **kwargs)
    assert isinstance(built, GlobalCacheKeyResult), built
    return built.key_hash


def _reason(body: dict[str, Any] | None = None, **kwargs: Any) -> str:
    built = _build(body, **kwargs)
    assert isinstance(built, CacheBypass), built
    return built.reason


def test_a_tool_bearing_request_is_keyed() -> None:
    """D1: a provider that declares function-calling rules keys ``tools`` and
    ``tool_choice`` instead of bypassing on their mere presence."""
    tools = [{"type": "function", "function": {"name": "f"}}]
    tools_built = _build(_body(tools=tools))
    assert isinstance(tools_built, GlobalCacheKeyResult), tools_built

    choice_built = _build(_body(tool_choice="auto"))
    assert isinstance(choice_built, GlobalCacheKeyResult), choice_built


def test_the_same_tool_bearing_request_yields_one_key() -> None:
    def _tools() -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": "f"}}]

    assert _hash(_body(tools=_tools())) == _hash(_body(tools=_tools()))


def test_reordering_the_tools_array_changes_the_key() -> None:
    """Deliberate, not an oversight: tool order plausibly affects what the model
    does with them (a provider may present them to the model in list order, and
    the model may weight earlier tools more), and canonical JSON preserves ARRAY
    order — only object keys sort (see ``canonical_key_material``). Keying the
    tools array verbatim, order included, is what keeps a served cache hit and a
    freshly dispatched request the SAME call. Normalizing the order here (e.g.
    sorting by name) would key one payload while dispatching a differently-
    ordered one — Ruling 34.

    # AIDEV-NOTE: do not "optimize" this by sorting the tools array before it is
    # hashed. That would silently violate Ruling 34: two callers who order their
    # tools differently get, today, two different upstream requests, and the
    # cache must never collapse them into one shared entry.
    """
    first = [
        {"type": "function", "function": {"name": "a"}},
        {"type": "function", "function": {"name": "b"}},
    ]
    second = list(reversed(first))
    assert _hash(_body(tools=first)) != _hash(_body(tools=second))


def test_a_different_tool_schema_changes_the_key() -> None:
    first = [{"type": "function", "function": {"name": "f"}}]
    second = [{"type": "function", "function": {"name": "g"}}]
    assert _hash(_body(tools=first)) != _hash(_body(tools=second))


def test_tool_choice_object_and_string_forms_both_key() -> None:
    string_form = _build(_body(tool_choice="auto"))
    object_form = _build(_body(tool_choice={"type": "function", "function": {"name": "f"}}))
    assert isinstance(string_form, GlobalCacheKeyResult), string_form
    assert isinstance(object_form, GlobalCacheKeyResult), object_form
    assert string_form.key_hash != object_form.key_hash


def test_caller_metadata_still_bypasses_alongside_tools() -> None:
    # Scope guard: D1 lifted tools/tool_choice, NOT metadata — its presence bypass
    # (untouched) must still win even on a request that also carries tools.
    tools = [{"type": "function", "function": {"name": "f"}}]
    assert _reason(_body(tools=tools, metadata={})) == "metadata"


def test_an_unpromoted_provider_still_bypasses_a_tool_bearing_request() -> None:
    """The opt-in guard (OME-787): the DEFAULT ``cache_behavior`` is ``"bypass"``.

    Same tool capability, same rule count as ``_RULES`` — the only difference is
    that ``cache_behavior`` was never raised to ``"keyed"``. Proves promotion is
    an explicit, per-provider act rather than something a provider gets merely by
    declaring function-calling support at all (see
    test_a_provider_without_function_calling_bypasses_a_tool_bearing_request below
    for the "no rule exists at all" case, which is a different reason).
    """
    tools = [{"type": "function", "function": {"name": "f"}}]
    assert _reason(_body(tools=tools), rules=_UNPROMOTED_RULES) == BYPASS_DECLARED


def test_a_provider_without_function_calling_bypasses_a_tool_bearing_request() -> None:
    """A provider that has enabled no tool type declares no ``tools``/
    ``tool_choice`` rule at all (``function_calling_rules`` returns ``()``), so a
    caller of THAT provider sending ``tools`` must still bypass: honouring
    function calling is a provider-declared capability, not a gateway-wide
    default, and keying it anyway would answer "yes" via a cached hit to a
    provider that cannot honour it.
    """
    no_tool_rules = function_calling_rules((), auth_modes=_AUTH, projection_revision=_REVISION)
    assert no_tool_rules == ()
    tools = [{"type": "function", "function": {"name": "f"}}]
    assert _reason(_body(tools=tools), rules=(_ordinary_rule(),)) == "unknown_parameter"
