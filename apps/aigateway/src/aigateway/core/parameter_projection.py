"""OME-479 Phase 4: fail-closed chat-parameter classification + projection.

FEATURE: effective parameter contract — dispatch side. The SAME provider rule
set that drives the ``/v1/models`` summary and the detailed
``/v1/model-parameters`` document decides HERE which caller-supplied optional
parameters may be dispatched, and projects each accepted value to its target in
a fresh normalized provider body.

INVARIANT: fail closed. A caller-supplied optional parameter is dispatched ONLY
when an enabled rule matching the REAL auth mode authorizes it. Every other
optional field — unknown, wrong-auth, malformed, duplicate-channel, or a
``provider_params`` wrapper that is not an object — is rejected with HTTP-safe
request paths, BEFORE credential injection and provider dispatch. Presence,
provider support, or staleness never authorize a parameter; only a rule does.

INVARIANT: required-protocol, gateway-owned, and transport fields are NOT
optional model parameters and never need a rule (``model``, ``messages``,
``stream``, ``extra_headers``, ``metadata``, ``timeout``). Caller LiteLLM
control-plane fields are already removed upstream (``strip_dispatch_controls``)
before this runs, so they are neither seen nor re-classified here.

INVARIANT (SOLID/hexagonal): provider-agnostic. No provider-name switch and no
central parameter inventory — a new parameter is enabled by a provider-local
rule + projection target only, with no edit to this module (plan §12 P0).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .auth_types import AuthMode
from .chat_parameters import (
    GATEWAY_OWNED_FIELDS,
    InvalidParameterRuleError,
    ParameterProjectionRule,
    ParameterValidationError,
    normalize_rules,
)

# The one caller-facing wrapper for provider-native fields (never dispatched
# as-is; each nested key is consumed into its rule target).
WRAPPER_KEY = "provider_params"
_WRAPPER_PREFIX = f"{WRAPPER_KEY}."


def wrapper_path_conflicts(request_paths: Iterable[str]) -> tuple[str, ...]:
    """Native names addressed at BOTH their bare path and their wrapper path.

    INVARIANT: within one provider view a native field is addressed at EXACTLY ONE
    request path — either bare (``top_k``) or wrapped (``provider_params.top_k``),
    never both. A provider states "this field rides the wrapper" twice — once in its
    discovery literal, once via its ``provider_native`` rule — and neither file
    imports the other, so the two can drift; when they do, the same field is
    described at two paths and the contract lists it twice.

    PUBLIC and provider-agnostic: callers pass the UNION of a provider's rule paths
    and observation paths (any iterable, duplicates fine) and get back the offending
    native names, sorted, so the failure can NAME the drifted field rather than
    surfacing later as a confusing "enabled but unevidenced" entry.

    WHY the whole remainder is the native name: ``provider_params.a.b`` addresses the
    field ``a.b``, NOT ``a`` — splitting on the first dot would false-positive against
    an unrelated bare ``a``.
    """
    paths = set(request_paths)
    wrapped = {path[len(_WRAPPER_PREFIX) :] for path in paths if path.startswith(_WRAPPER_PREFIX)}
    return tuple(sorted(wrapped & paths))


# Rejection reason codes: safe to return to the caller (no raw value leaks).
_REASON_UNKNOWN = "unknown"
_REASON_WRONG_AUTH = "wrong_auth_mode"
_REASON_MALFORMED = "malformed"
_REASON_DUPLICATE = "duplicate_channel"
_REASON_NOT_OBJECT = "not_an_object"


class UnsupportedParametersError(ValueError):
    """One or more caller optional parameters are not dispatchable (fail closed).

    Carries only SAFE request paths mapped to reason codes — never the raw
    submitted values — so the route can render an OpenAI-compatible HTTP 400
    without echoing a secret or unvalidated payload.
    """

    def __init__(self, rejected: Mapping[str, str]) -> None:
        self.rejected: dict[str, str] = dict(sorted(rejected.items()))
        super().__init__("unsupported chat parameters: " + ", ".join(self.rejected))


class IncompatibleParametersError(ValueError):
    """Individually-valid parameters the provider cannot serve TOGETHER (OME-640).

    Deliberately NOT a variant of ``UnsupportedParametersError``: every path named
    here IS enabled and DID satisfy its schema. What the provider refuses is the
    COMBINATION — a cross-field, often model- and auth-specific constraint that a
    per-path rule cannot express. Reporting it as an unsupported parameter would
    send the caller looking for a disabled field that does not exist.

    Carries only SAFE request paths plus a reason string the provider composed
    from its own constants — never a raw submitted value.
    """

    def __init__(self, paths: Iterable[str], *, reason: str) -> None:
        self.paths: tuple[str, ...] = tuple(sorted(set(paths)))
        self.reason = reason
        super().__init__(f"incompatible chat parameters ({', '.join(self.paths)}): {reason}")


class _TargetCollision(Exception):
    """Two accepted channels resolve to the same provider-body location."""


def _project(body: dict[str, Any], dotted_target: str, value: Any) -> None:
    """Place ``value`` at a dotted provider target, detecting channel collisions.

    Walks/creates intermediate dicts for a dotted target (e.g.
    ``extra_body.top_k`` -> ``{"extra_body": {"top_k": value}}``). Raises
    ``_TargetCollision`` if the leaf is already set or an intermediate segment
    is occupied by a non-dict — i.e. two rules would fight over one location.
    """
    parts = dotted_target.split(".")
    node = body
    for segment in parts[:-1]:
        existing = node.get(segment)
        if existing is None:
            existing = {}
            node[segment] = existing
        elif not isinstance(existing, dict):
            raise _TargetCollision(dotted_target)
        node = existing
    leaf = parts[-1]
    if leaf in node:
        raise _TargetCollision(dotted_target)
    node[leaf] = value


def _addressed_request_paths(body: Mapping[str, Any]) -> Iterable[str]:
    """Every optional-parameter request path this body addresses.

    The caller-visible addressing forms are a top-level field (including an explicitly ruled
    dotted path) or a key nested under the ``provider_params`` wrapper. Gateway-owned fields are
    authorized structurally and are never request paths.

    AIDEV-NOTE: this mirrors the enumeration in ``classify_and_project_chat_parameters``. The
    caller-cache policy tests lock them together so a new addressing form cannot drift between
    the dispatch contract and this compatibility view.
    """
    for key in body:
        if key == WRAPPER_KEY or key in GATEWAY_OWNED_FIELDS:
            continue
        if key.startswith(_WRAPPER_PREFIX):
            # OME-704: only `provider_params.*` top-level keys are not an addressing form;
            # provider-native fields must arrive inside the wrapper object.
            continue
        yield key
    wrapper = body.get(WRAPPER_KEY)
    if isinstance(wrapper, Mapping):
        for nested_key in wrapper:
            yield f"{_WRAPPER_PREFIX}{nested_key}"


def caller_cache_bypass_paths(
    body: Mapping[str, Any],
    *,
    rules: Iterable[ParameterProjectionRule],
    auth_mode: AuthMode,
) -> tuple[str, ...]:
    """Return addressed paths whose enabled rule declares a cache bypass.

    This pure function is a caller-visible compatibility view, not the runtime global-cache
    authority. Actual eligibility lives in ``request_cache.global_eligibility``. Keeping the view
    prevents the single-lane refactor from deleting a non-v1 API while its tests ensure it continues
    to describe the same provider rule contract.
    """
    enabled = {
        rule.request_path: rule
        for rule in normalize_rules(rules)
        if auth_mode in rule.applicable_auth_modes
    }
    return tuple(
        sorted(
            {
                path
                for path in _addressed_request_paths(body)
                if path in enabled and enabled[path].cache_behavior == "bypass"
            }
        )
    )


def classify_and_project_chat_parameters(
    body: Mapping[str, Any],
    *,
    rules: Iterable[ParameterProjectionRule],
    auth_mode: AuthMode,
) -> dict[str, Any]:
    """Return a fresh normalized dispatch body, or raise on any unsupported field.

    Steps (plan §4.5, dispatch subset):

    1. Load + normalize the provider rule set (deterministic; dup paths are a
       provider-config error surfaced here).
    2. Copy required-protocol/gateway-owned/transport fields through untouched.
    3. For every OTHER top-level field and every ``provider_params`` nested key:
       accept iff an enabled rule (matching ``auth_mode``) authorizes it and the
       value satisfies the rule schema; otherwise record a safe rejection.
    4. Project each accepted value to its rule target in the fresh body; the
       ``provider_params`` wrapper is consumed key-by-key and never splatted.
    5. If anything was rejected, raise ``UnsupportedParametersError`` with the
       sorted safe paths — BEFORE the caller ever returns to credential access.
    """
    normalized = normalize_rules(rules)
    by_path = {rule.request_path: rule for rule in normalized}
    enabled = {
        path: rule for path, rule in by_path.items() if auth_mode in rule.applicable_auth_modes
    }

    fresh: dict[str, Any] = {}
    rejected: dict[str, str] = {}

    def _accept(path: str, value: Any) -> None:
        rule = enabled[path]
        schema = rule.parameter_schema
        if schema is not None:
            try:
                schema.validate_value(value)
            except ParameterValidationError:
                rejected[path] = _REASON_MALFORMED
                return
        try:
            _project(fresh, rule.target, value)
        except _TargetCollision:
            rejected[path] = _REASON_DUPLICATE

    def _resolve(path: str, value: Any) -> None:
        if path in enabled:
            _accept(path, value)
        elif path in by_path:
            # Known to the provider, but not under this auth mode.
            rejected[path] = _REASON_WRONG_AUTH
        else:
            rejected[path] = _REASON_UNKNOWN

    # (2) + (3) top-level fields.
    for key, value in body.items():
        if key == WRAPPER_KEY:
            continue  # consumed in the wrapper pass below; never splatted.
        if key.startswith(_WRAPPER_PREFIX):
            # INVARIANT (OME-704): the provider_params OBJECT is the ONLY caller
            # addressing form for a provider-native field. A provider_native rule's
            # request_path IS the string "provider_params.<leaf>", so without this
            # guard a TOP-LEVEL key spelled that way matches the rule directly and
            # dispatches — an undocumented second addressing form for every wrapped
            # field on every provider, outside the published contract and outside
            # every wrapper-shaped protection built on top of it.
            #
            # Structural, so it fires BEFORE rule resolution: a top-level `provider_params.*`
            # key is malformed whether or not a rule owns that path. Other dotted top-level
            # paths are ordinary direct parameters and remain rule-gated (OME-1656).
            rejected[key] = _REASON_UNKNOWN
            continue
        if key in GATEWAY_OWNED_FIELDS:
            # A provider rule must never also claim a gateway-owned field.
            if key in fresh:
                rejected[key] = _REASON_DUPLICATE
            else:
                fresh[key] = value
            continue
        _resolve(key, value)

    # (3) provider_params wrapper — each nested key needs its own rule.
    wrapper = body.get(WRAPPER_KEY)
    if wrapper is not None:
        if not isinstance(wrapper, Mapping):
            rejected[WRAPPER_KEY] = _REASON_NOT_OBJECT
        else:
            for nested_key, nested_value in wrapper.items():
                _resolve(f"{_WRAPPER_PREFIX}{nested_key}", nested_value)

    if rejected:
        raise UnsupportedParametersError(rejected)
    # INVARIANT: the wrapper is fully consumed; a raw provider_params object can
    # never reach a provider, even under optimized Python where asserts disappear.
    if WRAPPER_KEY in fresh:
        raise InvalidParameterRuleError("parameter rule cannot target the provider_params wrapper")
    return fresh
