"""Reusable OpenAI-compatible parameter schemas + rule builders (OME-479 §4.2).

Provider plugins SELECT from these to compose their own rule sets. Defining the
bounded schema for a standard field ONCE stops providers from disagreeing about
what ``temperature`` means, while each plugin still owns which fields it enables,
under which auth modes, and where each value projects.

INVARIANT (SOLID/hexagonal): no provider names appear here. This module is the
shared vocabulary; the choice of which words to speak stays provider-local, so
enabling a new parameter is a provider-local edit, never a change here.
"""

from __future__ import annotations

from collections.abc import Iterable

from .auth_types import AuthMode
from .chat_parameters import (
    CacheBehavior,
    ParameterProjectionRule,
    ParameterSchema,
    ProviderParameterObservation,
    ToolCapability,
    supported_tool_types,
)

# Bounded schemas for the standard OpenAI-compatible optional fields the gateway
# forwards; ranges follow the OpenAI Chat Completions contract.
TEMPERATURE_SCHEMA = ParameterSchema(type="number", minimum=0, maximum=2)
TOP_P_SCHEMA = ParameterSchema(type="number", minimum=0, maximum=1)
MAX_TOKENS_SCHEMA = ParameterSchema(type="integer", minimum=1)
TOP_K_SCHEMA = ParameterSchema(type="integer", minimum=1)
# ``frequency_penalty`` and ``presence_penalty`` (OME-586) share the OpenAI-compatible
# [-2, 2] range; one shared schema keeps the two repetition controls consistent (DRY). A
# value outside the range, or a non-number, fails closed at classification.
PENALTY_SCHEMA = ParameterSchema(type="number", minimum=-2, maximum=2)
# Union of the OpenAI reasoning-effort ladder and Anthropic's "none" (disable
# thinking); a value outside this set fails closed at classification.
REASONING_EFFORT_SCHEMA = ParameterSchema(
    type="string", enum=("none", "minimal", "low", "medium", "high")
)
# ``stop`` is the OpenAI top-level UNION string | array[string]: a single stop
# string, or an array of them. The scalar form skips item validation; the array
# form requires every item to be a string, so a wrong-typed item (e.g. [123])
# fails closed as malformed at classification, before any credential access.
STOP_SCHEMA = ParameterSchema(type=("string", "array"), item_type="string")
# ``response_format`` (OME-584): the OpenAI structured-output object, gated by its
# ``type`` discriminator over the FULL documented range (plain text, json_object, or a
# named json_schema) — so the gateway does not narrow the provider's valid set. Only the
# top-level shape + ``type`` are validated; the nested json_schema body is a provider
# concern. A non-object, or an unknown/absent ``type``, fails closed at classification.
RESPONSE_FORMAT_SCHEMA = ParameterSchema(
    type="object",
    object_discriminator="type",
    object_discriminator_enum=("text", "json_object", "json_schema"),
)
# ``seed`` (OME-585): OpenAI's deterministic-sampling seed is an ARBITRARY integer
# (0 and negatives included) — the gateway deliberately sets no numeric bound so it
# never rejects a value the provider would accept. A non-integer fails closed.
SEED_SCHEMA = ParameterSchema(type="integer")
# ``n`` (OME-585): the number of chat completions to generate — at least one. A value
# below 1 (e.g. 0) or a non-integer fails closed at classification.
N_SCHEMA = ParameterSchema(type="integer", minimum=1)
# ``logprobs`` (OME-595): OpenAI's on/off switch for returning per-token log
# probabilities. A boolean — an int (even 0/1) or any other type fails closed, so the
# gateway never forwards a mistyped value the provider would reject.
LOGPROBS_SCHEMA = ParameterSchema(type="boolean")
# ``top_logprobs`` (OME-595): how many alternative tokens to return per position, each with
# its log probability. OpenAI's documented range is an integer 0..20 INCLUSIVE; a value
# outside it, a boolean, or a non-integer fails closed at classification.
TOP_LOGPROBS_SCHEMA = ParameterSchema(type="integer", minimum=0, maximum=20)
# ``web_search``: ask the PROVIDER to retrieve before answering. A plain boolean on purpose.
#
# Providers spell server-side retrieval differently and each spelling is an extensibility
# ENVELOPE — OpenRouter's is `plugins: [...]`, a list of arbitrary provider extensions. An
# envelope cannot be meaningfully bounded, because carrying anything is the point of it, so a
# rule enabling one authorizes a path and forwards nested JSON verbatim: exactly what OME-646
# removed. A boolean is bounded COMPLETELY, and the provider translates it into its own
# spelling in `prepare_chat_body`, where a gateway-owned value is assigned rather than merged.
#
# This is the shared vocabulary, so the word is provider-agnostic: any provider that can
# retrieve enables the same field, and one that cannot simply does not — a caller asking then
# gets a named 400 from the authority on capability, rather than silence.
WEB_SEARCH_SCHEMA = ParameterSchema(type="boolean")
# ``web_search_excluded_domains``: domains the caller asks the provider to exclude.
#
# INVARIANT: this can only ever ADD to the deployment's own requested exclusions — a provider
# composes the two as a UNION (see the OpenRouter plugin). Whether the upstream engine enforces
# exclusions is model-specific, so a protocol requiring a hard block must choose a compatible
# Engine route rather than treating this wire field as universal enforcement.
WEB_SEARCH_EXCLUDED_DOMAINS_SCHEMA = ParameterSchema(type="array", item_type="string")


def direct_rule(
    request_path: str,
    *,
    auth_modes: tuple[AuthMode, ...],
    projection_revision: str,
    cache_behavior: CacheBehavior,
    schema: ParameterSchema | None = None,
    provider_target: str | None = None,
    output_affecting: bool = True,
) -> ParameterProjectionRule:
    """A standard field kept on the request under ``request_path`` (or a target).

    # WHY ``cache_behavior`` is REQUIRED and has no default (OME-305, owner decision
    # 52): it used to default to ``"bypass"``, which made silence indistinguishable
    # from a judgment. Every parameter that reached this factory without the argument
    # was recorded as a deliberate bypass by a caller who had never considered the
    # question, and the audit could not tell the two apart. A required argument forces
    # a NEW parameter's author to answer "must two callers sending this same value get
    # the same upstream request?" at the moment they add the rule, which is the only
    # time the answer is cheap to establish.
    # INVARIANT: a rule may only be keyed on a provider that implements
    # ``global_cache_projection``. Keying a parameter on a provider without one is
    # unobservable — the missing projection bypasses the request regardless of its
    # rules' dispositions — and it is refused by
    # ``test_a_provider_that_declares_a_keyed_rule_backs_it_with_a_real_projection``.
    """
    return ParameterProjectionRule(
        request_path=request_path,
        applicable_auth_modes=auth_modes,
        projection_kind="direct",
        provider_target=provider_target,
        cache_behavior=cache_behavior,
        output_affecting=output_affecting,
        projection_revision=projection_revision,
        schema=schema,
    )


def provider_native_rule(
    request_path: str,
    *,
    provider_target: str,
    auth_modes: tuple[AuthMode, ...],
    projection_revision: str,
    cache_behavior: CacheBehavior,
    schema: ParameterSchema | None = None,
    output_affecting: bool = True,
) -> ParameterProjectionRule:
    """A ``provider_params.*`` field projected to a provider-native ``target``.

    # WHY ``cache_behavior`` is required here too — see ``direct_rule`` above for the
    # full rationale (owner decision 52). This factory carries an extra hazard worth
    # naming: a ``provider_params.*`` rule restricted to SOME of the provider's auth
    # modes can never actually be keyed, because the key is built before any credential
    # exists. Owner decision 59 therefore requires such a rule to declare ``bypass``;
    # the mode-restriction check in ``global_eligibility`` remains defence in depth.
    """
    return ParameterProjectionRule(
        request_path=request_path,
        applicable_auth_modes=auth_modes,
        projection_kind="provider_native",
        provider_target=provider_target,
        cache_behavior=cache_behavior,
        output_affecting=output_affecting,
        projection_revision=projection_revision,
        schema=schema,
    )


# --- function calling: tools / tool_choice (OME-583) -------------------------
# FEATURE: first-class OpenAI-style function calling. These builders are the
# shared vocabulary for the two tool request paths; a provider SELECTS them (with
# its own enabled tool types, auth modes, and source label), so enabling function
# calling stays a provider-local edit and the no-provider-names invariant holds.


def tools_schema(tool_types: tuple[str, ...]) -> ParameterSchema:
    """``tools``: an array of OpenAI tool objects, each gated by its ``type``.

    INVARIANT: every array item's ``type`` discriminator must be one of the
    provider's enabled tool types, so a caller sending an unadvertised tool (e.g. a
    hosted ``web_search``) fails closed at classification, before credential access.
    """
    return ParameterSchema(
        type="array",
        item_type="object",
        object_discriminator="type",
        object_discriminator_enum=tool_types,
    )


def tool_choice_schema(tool_types: tuple[str, ...]) -> ParameterSchema:
    """``tool_choice``: the OpenAI ``string | object`` union.

    The string form (``"auto"`` / ``"none"`` / ``"required"``) carries no ``type``,
    so the discriminator is skipped; the object form (``{"type": "function", …}``)
    must name an enabled tool type or it fails closed.
    """
    return ParameterSchema(
        type=("string", "object"),
        object_discriminator="type",
        object_discriminator_enum=tool_types,
    )


def function_calling_rules(
    tool_capabilities: Iterable[ToolCapability],
    *,
    auth_modes: tuple[AuthMode, ...],
    projection_revision: str,
    tool_choice: bool = True,
    cache_behavior: CacheBehavior = "bypass",
) -> tuple[ParameterProjectionRule, ...]:
    """The ``tools`` [and ``tool_choice``] rules for a provider's enabled tools.

    Empty when no tool type is enabled — a provider with no function-calling support
    gets no phantom rule. ``tool_choice=False`` enables ``tools`` alone (Gemini: its
    builder maps ``tools[]`` but emits no tool-selection control, §9), so the gateway
    never advertises a control it cannot honor on the wire.

    INVARIANT: authorization lives in ONE place — these rules. There is no separate
    tools dispatch path, so the classifier and the published contract cannot drift.

    # WHY ``cache_behavior`` defaults to ``"bypass"`` (OME-782/OME-787): a provider may
    # only declare these rules ``keyed`` if its ``global_cache_projection`` can back
    # them — ``ProviderPluginBase`` returns ``CacheBypass`` by default, so promoting a
    # provider that has not implemented the projection would advertise a cacheable
    # parameter to callers who can never actually be served from cache.
    # ``test_a_provider_that_declares_a_keyed_rule_backs_it_with_a_real_projection`` in
    # ``tests/unit/test_global_cache_registry_conformance.py`` enforces that. The
    # promotion order (implement the projection FIRST, then flip this argument) is
    # documented at ``plugins/antigravity_provider/parameters.py:68``. Caching tools is
    # therefore opt-in PER PROVIDER: pass ``cache_behavior="keyed"`` explicitly once a
    # provider's projection is ready — see ``plugins/openrouter_provider/parameters.py``
    # for the first provider to do so.
    """
    tool_types = supported_tool_types(tool_capabilities)
    if not tool_types:
        return ()
    rules = [
        direct_rule(
            "tools",
            auth_modes=auth_modes,
            schema=tools_schema(tool_types),
            cache_behavior=cache_behavior,
            projection_revision=projection_revision,
        )
    ]
    if tool_choice:
        rules.append(
            direct_rule(
                "tool_choice",
                auth_modes=auth_modes,
                schema=tool_choice_schema(tool_types),
                cache_behavior=cache_behavior,
                projection_revision=projection_revision,
            )
        )
    return tuple(rules)


def tool_parameter_observations(
    tool_capabilities: Iterable[ToolCapability],
    *,
    source: str,
    tool_choice: bool = True,
) -> tuple[ProviderParameterObservation, ...]:
    """Provider evidence mirroring the tool rules.

    INVARIANT (§4.4): every enabled parameter carries a provider observation, so an
    enabled tool path is never left unevidenced. Mirrors ``function_calling_rules``
    exactly — same enablement guard, same ``tool_choice`` flag — so the rules and
    their evidence can never disagree about which tool paths exist.
    """
    if not supported_tool_types(tool_capabilities):
        return ()
    paths = ("tools", "tool_choice") if tool_choice else ("tools",)
    return tuple(
        ProviderParameterObservation(request_path=path, support="supported", source=source)
        for path in paths
    )


def direct_parameter_observations(
    request_paths: Iterable[str],
    *,
    source: str,
) -> tuple[ProviderParameterObservation, ...]:
    """Provider evidence for non-sampling ``direct`` request paths (OME-584).

    INVARIANT (§4.4): every enabled parameter carries a provider observation, so an
    enabled non-sampling field (e.g. ``response_format``) is never left unevidenced.
    Kept OUT of the sampling discovery constants — these are not sampling fields — so
    the strict discovery-parser tests keep their meaning (mirrors
    ``tool_parameter_observations``). Empty in, empty out: no phantom evidence.
    """
    return tuple(
        ProviderParameterObservation(request_path=path, support="supported", source=source)
        for path in request_paths
    )
