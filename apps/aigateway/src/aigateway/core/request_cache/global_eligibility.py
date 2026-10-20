"""OME-305 — what an effective request consists of for global cache purposes.

FEATURE: one global exact-request cache. Before anything can be hashed, the
gateway has to decide which parts of a request are output-affecting facts, which
are transport noise, and which make the request uncacheable altogether. This
module owns that decision; ``.global_keys`` owns turning the answer into a hash.

INVARIANT: the field enumeration here is CLOSED. Every key in the request body is
either prompt material, a reviewed structural field named below, the one
``provider_params`` wrapper, or a request path a provider RULE dispositions.
Anything else bypasses. A key this module fails to account for is a key that
silently does not participate in the hash — which is the one failure mode a shared
cache may never have.

INVARIANT: no identity. Nothing here takes an account, profile, user, auth mode or
credential, and the provider projection is called with the request body alone.

AIDEV-NOTE (OME-653 pattern): split out of ``.global_keys`` purely to keep each
file within the repository's 450-line limit. ``.global_keys`` is the public
surface and re-exports every name below; import from there.

AIDEV-NOTE: this enumeration is independent of the auth-specific dispatch classifier,
which may legitimately reject a key elsewhere. This module must ACCOUNT FOR every key.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from ..cache_ports import PROJECTION_BYPASS_REASON, CacheBypass, GlobalCacheProjection
from ..chat_parameters import (
    ParameterProjectionRule,
    ParameterRuleError,
    ParameterValidationError,
    normalize_rules,
)
from ..parameter_projection import WRAPPER_KEY

# Closed bypass vocabulary. Published in ``X-AIGW-Cache-Reason``, so no member may
# ever carry a caller value, a prompt fragment, a provider message or identity.
BYPASS_UNSUPPORTED_SHAPE: Final = "unsupported_shape"
BYPASS_UNKNOWN_PARAMETER: Final = "unknown_parameter"
# INVARIANT: the published spelling is kept deliberately (owner decision 53). The rename to
# ``bypassing_parameter`` was landed and then reverted — URL4 reads these bytes, so the
# owner ruled "rename only what must change". Do not restore it.
BYPASS_DECLARED: Final = "unsupported_fields"
BYPASS_MALFORMED_PARAMETER: Final = "malformed_parameter"
BYPASS_RULE_SET: Final = "provider_rule_set"
BYPASS_STREAM: Final = "stream"
BYPASS_METADATA: Final = "metadata"
BYPASS_UNPROJECTED_NATIVE: Final = "unprojected_parameter"
BYPASS_MODE_RESTRICTED: Final = "mode_restricted_parameter"

# --- the reviewed disposition of every non-parameter request field ------------

# Prompt material: hashed verbatim, never normalized. ``system`` is here rather
# than in the rule space because prompt material is hashed verbatim.
PROMPT_FIELDS: Final[frozenset[str]] = frozenset({"model", "messages", "system"})

# Excluded from the key because they provably do not affect provider output.
# ``api_key`` cannot reach this point (``strip_dispatch_controls`` removes it) and
# is listed so that if it ever did, credential material would be EXCLUDED rather
# than hashed.
EXCLUDED_TRANSPORT_FIELDS: Final[frozenset[str]] = frozenset(
    {"timeout", "extra_headers", "api_key"}
)

# Presence alone makes the request ineligible (plan §1.3). ``metadata`` bypasses
# even when empty, because presence is the fact under review: no closed
# transport-only subset of caller metadata has been proven yet.
#
# WHY: tools/tool_choice used to live here too (OME-305) and no longer do —
# OME-782, owner decision D1. A cached entry represents ONE model call, and a
# tool RESULT the caller sends back on the next turn arrives in ``messages``,
# which is already hashed verbatim, so a differing tool result already yields
# a differing key. There is nothing left for a blanket presence bypass to
# protect: whether ``tools``/``tool_choice`` key or bypass is now decided the
# ordinary way, per request path, by whatever rule a provider declares for
# them (see ``standard_parameters.function_calling_rules``).
PRESENCE_BYPASS_REASONS: Final[Mapping[str, str]] = {
    "metadata": BYPASS_METADATA,
}

# Ineligible only when truthy: ``stream: false`` means exactly what omission means.
# INVARIANT: streaming stays structurally ineligible here even if a provider rule
# ever declared otherwise — a streamed response is assembled from chunks the
# gateway does not store.
TRUTHY_BYPASS_REASONS: Final[Mapping[str, str]] = {"stream": BYPASS_STREAM}

# Every top-level field the parameter adjudicator must NOT look up as a rule,
# because one of the reviewed dispositions above already accounts for it.
#
# WHY this union is published rather than re-spelled at each use site: the
# conformance guard has to ask the same question ``_classify`` asks, and a guard
# that re-derives the union would keep honouring four sets while ``_classify``
# honoured five the moment a fifth exclusion was added — the guard would narrow
# silently and still look correct. One name, one source of truth.
#
# INVARIANT: a DENYLIST, deliberately. An allowlist of keyable paths would need
# editing on every promotion of a rule from ``bypass`` to ``keyed``, which is
# precisely how the old prompt-only allowlist became a guard that forbade the
# promotions this ticket exists to make.
STRUCTURALLY_EXCLUDED_FIELDS: Final[frozenset[str]] = (
    PROMPT_FIELDS
    | EXCLUDED_TRANSPORT_FIELDS
    | frozenset(TRUTHY_BYPASS_REASONS)
    | frozenset(PRESENCE_BYPASS_REASONS)
)

_WRAPPER_PREFIX: Final = f"{WRAPPER_KEY}."
_PROJECTION_MEMBERS: Final[frozenset[str]] = frozenset(
    {"resolved_model", "provider_adapter_revision", "prepared"}
)


class _Absent:
    """Sentinel: the caller sent no top-level ``system`` context at all.

    WHY a sentinel rather than ``None``: plan §2.5 requires missing, null, false
    and zero to remain DISTINCT. ``system: null`` is a thing the caller said.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "ABSENT"


ABSENT: Final = _Absent()


@dataclass(frozen=True)
class RequestFacts:
    """Everything about one request that a global key is allowed to depend on."""

    requested_model: str
    messages: list[Any]
    system: Any
    keyed_parameters: dict[str, Any]
    resolved_model: str
    provider_adapter_revision: str
    prepared_request: Mapping[str, Any]


@dataclass(frozen=True)
class _Accepted:
    """What one adjudicated request path contributes to the key.

    ``entry`` is the direct keyed contribution — empty for a ``transport_only``
    field (accepted and deliberately excluded) and empty for a provider-native
    one, whose effective value travels in the projection instead. ``projected_root``
    names the ``prepared`` location a native path depends on, or ``""`` for none.
    """

    entry: dict[str, Any]
    projected_root: str


_EXCLUDED: Final = _Accepted(entry={}, projected_root="")


def is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _prompt_parts(body: Mapping[str, Any]) -> tuple[str, list[Any], Any] | CacheBypass:
    model = body.get("model")
    messages = body.get("messages")
    if not is_text(model):
        return CacheBypass(BYPASS_UNSUPPORTED_SHAPE)
    if not isinstance(messages, list):
        return CacheBypass(BYPASS_UNSUPPORTED_SHAPE)
    return str(model), messages, body.get("system", ABSENT)


def _structural_bypass(body: Mapping[str, Any]) -> CacheBypass | None:
    for field, reason in TRUTHY_BYPASS_REASONS.items():
        if body.get(field):
            return CacheBypass(reason)
    for field, reason in PRESENCE_BYPASS_REASONS.items():
        if field in body:
            return CacheBypass(reason)
    return None


def _accept(
    path: str,
    value: Any,
    enabled: Mapping[str, ParameterProjectionRule],
    provider_modes: frozenset[str],
) -> _Accepted | CacheBypass:
    """What this addressed path contributes to the key, or the bypass it forces.

    WHY the schema is validated HERE, on a path that has no auth context: schema
    validity is auth-INDEPENDENT, so a value that fails it will be refused with an
    HTTP 400 on the miss path for every caller. Keying it anyway would let a later
    identical request be answered 200 from cache for a request the gateway must
    refuse. Compare the ACCEPTED consequence for auth-mode-specific validation,
    which a hit does skip.
    """
    rule = enabled.get(path)
    if rule is None:
        return CacheBypass(BYPASS_UNKNOWN_PARAMETER)
    if rule.cache_behavior == "bypass":
        return CacheBypass(BYPASS_DECLARED)
    if not provider_modes <= frozenset(rule.applicable_auth_modes):
        # INVARIANT: a path this provider offers in only SOME of its auth modes can
        # never be keyed, because the key cannot see which mode the caller will
        # resolve to. Keyed, an api-key caller could fill an entry with a parameter
        # an OAuth caller is not offered, and that OAuth caller would then be served
        # a 200 hit for a request the miss path would have refused outright.
        #
        # WHY this is NOT covered by the accepted validation skip: that trade-off is
        # about auth-specific VALIDATION ("your value is invalid"). This is
        # AVAILABILITY ("this parameter is not offered in your mode") — a different
        # kind of refusal, and accepting it silently would widen an approved
        # trade-off without saying so.
        #
        # The test is auth-mode-INDEPENDENT (provider metadata vs the rule's own
        # declaration), so it needs no caller state and the port stays identity-free.
        # Granularity is per-path: one mode-restricted parameter in the body costs
        # this request its entry, not every request to the provider.
        return CacheBypass(BYPASS_MODE_RESTRICTED)
    if rule.cache_behavior == "transport_only":
        # Accepted and deliberately excluded — ONLY because a rule proved the field
        # does not affect output.
        return _EXCLUDED
    if rule.parameter_schema is not None:
        try:
            rule.parameter_schema.validate_value(value)
        except ParameterValidationError:
            return CacheBypass(BYPASS_MALFORMED_PARAMETER)
    if rule.projection_kind == "provider_native":
        # WHY a native VALUE is not hashed here: the caller's spelling of a native
        # control is not what reaches the provider. The provider boundary
        # RECONSTRUCTS its own object from an allowlist and normalizes on the way,
        # so one upstream request has several accepted spellings — a price ceiling
        # of "1", "1.0" and "1.000" is one ceiling, and a flag whose ``false`` means
        # exactly what omission means is sent as nothing at all. Hashing the
        # spelling would split ONE upstream request across three cache entries.
        # The EFFECTIVE value travels in ``prepared_request``, which is hashed
        # whole, so what participates in the key is what the provider will send.
        #
        # INVARIANT: a native path is keyed only if the provider's projection
        # DESCRIBES the location it projects into (checked in
        # ``collect_request_facts``). Without that check the value would silently
        # leave the key and two different values would share one entry — the one
        # failure mode a shared cache may never have. A missing DEEPER path is the
        # deliberate-omission case above and is correct; a missing ROOT means the
        # provider never described this surface at all.
        #
        # AIDEV-NOTE: this root is in the PROVIDER-TARGET namespace, not the caller's
        # request-path namespace, and that correctness rests on a validator in
        # another file: ``chat_parameters/_types.py`` requires ``provider_target`` on
        # every ``provider_native`` rule, which is what makes ``rule.target`` return
        # it. Relax that validator and ``target`` falls back to ``request_path``,
        # ``projected_root`` becomes ``"provider_params"``, and EVERY native keyed
        # rule silently bypasses. It fails safe, but the dependency spans two files,
        # so do not remove the validator without moving this derivation with it.
        return _Accepted(entry={}, projected_root=rule.target.split(".", 1)[0])
    # INVARIANT: the rule's own revision travels WITH the value, so bumping a
    # projection's revision abandons entries built under the old behaviour
    # instead of re-serving them under the new one.
    return _Accepted(
        entry={path: {"value": value, "revision": rule.projection_revision}}, projected_root=""
    )


def _accept_wrapper(
    wrapper: Any,
    enabled: Mapping[str, ParameterProjectionRule],
    keyed: dict[str, Any],
    roots: set[str],
    provider_modes: frozenset[str],
) -> CacheBypass | None:
    if not isinstance(wrapper, Mapping):
        return CacheBypass(BYPASS_UNSUPPORTED_SHAPE)
    for leaf, value in wrapper.items():
        if not isinstance(leaf, str):
            return CacheBypass(BYPASS_UNSUPPORTED_SHAPE)
        accepted = _accept(f"{_WRAPPER_PREFIX}{leaf}", value, enabled, provider_modes)
        if isinstance(accepted, CacheBypass):
            return accepted
        keyed.update(accepted.entry)
        if accepted.projected_root:
            roots.add(accepted.projected_root)
    return None


def _classify(
    body: Mapping[str, Any],
    rules: Iterable[ParameterProjectionRule],
    provider_modes: frozenset[str],
) -> tuple[dict[str, Any], frozenset[str]] | CacheBypass:
    """Adjudicate every caller parameter: keyed entries + the projection it needs.

    Returns the directly keyed entries and the set of ``prepared`` roots that
    accepted provider-native paths depend on (see ``_accept``).

    INVARIANT: uses the provider's AUTH-MODE-INDEPENDENT rule set, because this
    runs before any auth mode is resolved. ``cache_behavior`` is one unconditional
    value per request path, so the disposition is well-defined without it.
    """
    try:
        enabled = {rule.request_path: rule for rule in normalize_rules(rules)}
    except ParameterRuleError:
        # A provider rule set that cannot be normalized is a misconfiguration.
        # Degrade to bypass rather than raising into the request path.
        return CacheBypass(BYPASS_RULE_SET)
    keyed: dict[str, Any] = {}
    roots: set[str] = set()
    for key, value in body.items():
        # One membership test against the published union: prompt material and
        # excluded transport are keyed (or excluded) elsewhere, and the structural
        # bypass fields were already adjudicated by ``_structural_bypass`` before
        # this ran. None of them may be looked up as a parameter rule.
        if key in STRUCTURALLY_EXCLUDED_FIELDS:
            continue
        if key == WRAPPER_KEY:
            outcome = _accept_wrapper(value, enabled, keyed, roots, provider_modes)
            if outcome is not None:
                return outcome
            continue
        if key.startswith(_WRAPPER_PREFIX):
            # OME-704: the wrapper OBJECT is the only addressing form for a native field. A
            # top-level ``provider_params.*`` key must be refused before lookup. Other dotted
            # names are valid direct paths (OME-1656) and still require an explicit rule below.
            return CacheBypass(BYPASS_UNKNOWN_PARAMETER)
        accepted = _accept(key, value, enabled, provider_modes)
        if isinstance(accepted, CacheBypass):
            return accepted
        keyed.update(accepted.entry)
        if accepted.projected_root:
            roots.add(accepted.projected_root)
    return keyed, frozenset(roots)


def _projected(
    projection: GlobalCacheProjection, body: Mapping[str, Any]
) -> tuple[str, str, Mapping[str, Any]] | CacheBypass:
    """The provider's own deterministic view of what it would send.

    INVARIANT: the projection receives a DEEP COPY, so a hook that mutates its
    argument cannot alter what the miss path later dispatches.

    INVARIANT: the returned shape is CLOSED. An unrecognized member bypasses
    rather than being dropped, so a provider cannot add an output-affecting
    prepared field that silently fails to participate in the key.
    """
    try:
        produced = projection(copy.deepcopy(dict(body)))
    except Exception:
        # WHY this catch is broad: a provider hook is third-party-shaped code, and
        # the cache may never be an availability dependency (plan §5.4). A bug
        # here costs a bypass, never the caller's request.
        return CacheBypass(PROJECTION_BYPASS_REASON)
    if isinstance(produced, CacheBypass) or not isinstance(produced, Mapping):
        return CacheBypass(PROJECTION_BYPASS_REASON)
    if set(produced) != _PROJECTION_MEMBERS:
        return CacheBypass(PROJECTION_BYPASS_REASON)
    resolved_model = produced["resolved_model"]
    revision = produced["provider_adapter_revision"]
    prepared = produced["prepared"]
    if not is_text(resolved_model) or not is_text(revision):
        return CacheBypass(PROJECTION_BYPASS_REASON)
    if not isinstance(prepared, Mapping):
        return CacheBypass(PROJECTION_BYPASS_REASON)
    return resolved_model, revision, prepared


def collect_request_facts(
    *,
    body: Mapping[str, Any],
    rules: Iterable[ParameterProjectionRule],
    projection: GlobalCacheProjection,
    provider_auth_modes: Iterable[str],
) -> RequestFacts | CacheBypass:
    """Every fact a global key may depend on, or the reason there is no key.

    ``body`` is the request after JSON shape validation, gateway and provider
    dispatch-control stripping, cache-control removal and the body-wins profile-default merge.

    ``provider_auth_modes`` is every mode the PROVIDER offers
    (``plugin.available_auth_modes()``) — provider metadata, never the caller's
    resolved mode. It is what lets a mode-restricted parameter be refused without
    the pure stage learning anything about who is asking.

    AIDEV-NOTE: do NOT substitute the union of ``applicable_auth_modes`` across the
    rule set. When every rule for a model is api-key-only that union is
    ``{"api_key"}``, so "applicable in all modes" is vacuously true for all of them
    and the guard silently does nothing while appearing to work.
    """
    parts = _prompt_parts(body)
    if isinstance(parts, CacheBypass):
        return parts
    structural = _structural_bypass(body)
    if structural is not None:
        return structural
    classified = _classify(body, rules, frozenset(provider_auth_modes))
    if isinstance(classified, CacheBypass):
        return classified
    produced = _projected(projection, body)
    if isinstance(produced, CacheBypass):
        return produced
    requested_model, messages, system = parts
    keyed, projected_roots = classified
    resolved_model, adapter_revision, prepared = produced
    # INVARIANT: an accepted provider-native value participates in the key ONLY
    # through the projection, so a provider that does not describe the surface it
    # projects into makes the request UNKEYABLE rather than silently keyless. Fail
    # safe: this costs a bypass, never a shared entry for two different values.
    if any(root not in prepared for root in projected_roots):
        return CacheBypass(BYPASS_UNPROJECTED_NATIVE)
    return RequestFacts(
        requested_model=requested_model,
        messages=messages,
        system=system,
        keyed_parameters=keyed,
        resolved_model=resolved_model,
        provider_adapter_revision=adapter_revision,
        prepared_request=prepared,
    )
