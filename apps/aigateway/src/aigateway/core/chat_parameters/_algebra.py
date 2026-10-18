"""OME-479 pure rule algebra.

FEATURE: effective model-capability contract — the verbs half. Every function
here is pure: it takes the value objects from ``._types`` and returns new ones,
touching no provider, no cache, and no request.

INVARIANT: only a gateway RULE authorizes a parameter. These derivations may move
provider support, provenance, staleness and lifecycle, and they may make an
unruled path VISIBLE as a disabled row — but none of them can enable a path the
provider's rules did not already enable.

AIDEV-NOTE: import these from the ``chat_parameters`` PACKAGE, never from this
module directly — the split between halves is an implementation detail and may
move again.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..auth_types import AuthMode
from ._types import (
    _DISABLED_AUTH_MODE_REASON,
    _DISABLED_UNPROJECTED_REASON,
    DuplicateParameterRuleError,
    ParameterContractEntry,
    ParameterProjectionRule,
    ProviderParameterObservation,
    ProviderToolObservation,
    ToolCapability,
)


def normalize_rules(
    rules: Iterable[ParameterProjectionRule],
) -> tuple[ParameterProjectionRule, ...]:
    """Return rules deterministically ordered by request_path, rejecting dups.

    INVARIANT: one request path == at most one rule per provider rule set, so
    the summary and the detailed contract cannot disagree about a path.
    INVARIANT: one provider target == at most one rule per provider rule set, so
    two request paths can never race to write the same wire field. ``rule.target``
    is ``provider_target or request_path``, so direct rules fold into the already
    unique request-path space and only genuine collisions (two native paths → one
    target, or a direct path clashing with a native target) trip this. Without it a
    provider misconfig would surface only as a caller-facing ``duplicate_channel``
    400 in ``_project`` — and only if a caller supplied both channels at once.
    """
    ordered = sorted(rules, key=lambda rule: rule.request_path)
    seen_paths: set[str] = set()
    seen_targets: dict[str, str] = {}
    for rule in ordered:
        if rule.request_path in seen_paths:
            raise DuplicateParameterRuleError(f"duplicate rule for {rule.request_path!r}")
        seen_paths.add(rule.request_path)
        if rule.target in seen_targets:
            raise DuplicateParameterRuleError(
                f"duplicate provider target {rule.target!r} for request paths "
                f"{seen_targets[rule.target]!r} and {rule.request_path!r}"
            )
        target_parts = tuple(rule.target.split("."))
        for seen_target, seen_path in seen_targets.items():
            seen_parts = tuple(seen_target.split("."))
            common = min(len(target_parts), len(seen_parts))
            if target_parts[:common] == seen_parts[:common]:
                raise DuplicateParameterRuleError(
                    f"prefix-related provider targets {seen_target!r} and {rule.target!r} "
                    f"for request paths {seen_path!r} and {rule.request_path!r}"
                )
        seen_targets[rule.target] = rule.request_path
    return tuple(ordered)


def inline_supported_parameters(
    rules: Iterable[ParameterProjectionRule],
    *,
    available_auth_modes: tuple[AuthMode, ...],
) -> tuple[str, ...]:
    """Conservative profile-independent summary.

    A path is included iff its rule is enabled under EVERY auth mode the
    provider offers (intersection). This prevents ``/v1/models`` from
    overclaiming an auth-specific field that only one mode can prove.

    INVARIANT: with NO auth mode available the summary is EMPTY. ``∅ ⊆ anything``
    is vacuously true, so the plain intersection would advertise every ruled path —
    the exact opposite of conservative. Nothing can be proven, so nothing is shown.
    """
    available = set(available_auth_modes)
    if not available:
        return ()
    return tuple(
        sorted(
            {rule.request_path for rule in rules if available <= set(rule.applicable_auth_modes)}
        )
    )


def overlay_observations(
    base: Iterable[ProviderParameterObservation],
    overlay: Iterable[ProviderParameterObservation],
    *,
    stale: bool = False,
) -> tuple[ProviderParameterObservation, ...]:
    """Merge dynamic evidence over labelled-local evidence, one verdict per path.

    FEATURE: model-specific provider evidence. A provider's reviewed
    labelled-local observations describe its ENDPOINT and cannot vary by model; a
    discovered snapshot describes ONE model. Where both speak, the more specific
    claim decides — so the detailed contract stops reporting the same evidence for
    every model of a provider.

    INVARIANT (evidence axis only): this moves ``support`` / ``source`` / ``stale``
    and may ADD a path the base never knew. It returns observations, never rules —
    so nothing here can enable a parameter, change the ``/v1/models`` summary, or
    authorize dispatch. A path the overlay is SILENT about keeps its base verdict:
    a partial source must never read as a denial.

    INVARIANT (silence is per FIELD, not only per PATH): an observation carries more
    than one axis, and different sources speak on different ones. A per-model catalog
    reports SUPPORT and knows nothing about a field's schema or lifecycle, so letting
    it win wholesale would erase endpoint facts it never contradicted — the same
    "partial source read as a denial" bug, one level down. ``schema`` and
    ``deprecated`` are therefore carried forward when the overlay is silent (``None``)
    about them, while the support axis is replaced outright.

    ``stale`` is the CACHE's verdict about this particular read, so it is stamped
    onto the overlay entries here rather than carried by the parser — and it is set
    in both directions, so a fresh read can never inherit a stale label.
    """
    merged = {observation.request_path: observation for observation in base}
    for observation in overlay:
        prior = merged.get(observation.request_path)
        # model_copy takes FIELD names, never the ``schema`` alias.
        updates: dict[str, Any] = {}
        if observation.stale != stale:
            updates["stale"] = stale
        if prior is not None:
            if observation.parameter_schema is None and prior.parameter_schema is not None:
                updates["parameter_schema"] = prior.parameter_schema
            if observation.deprecated is None and prior.deprecated is not None:
                updates["deprecated"] = prior.deprecated
        merged[observation.request_path] = (
            observation.model_copy(update=updates) if updates else observation
        )
    return tuple(merged[path] for path in sorted(merged))


def overlay_tool_capabilities(
    base: Iterable[ToolCapability],
    overlay: Iterable[ProviderToolObservation],
) -> tuple[ToolCapability, ...]:
    """Apply discovered tool evidence to a provider's reviewed tool capabilities.

    FEATURE: backend-specific tool evidence. A tool type is named in TWO published
    places — the ``tools``/``tool_choice`` request paths and the tools section — so
    a discovered verdict that reached only one of them would make the detailed
    contract contradict itself. This is the tools-section half.

    INVARIANT (evidence axis only): this moves ``provider_support`` and NOTHING
    else. ``gateway_status`` is policy, derived from the provider's reviewed rules,
    so a backend that lacks a tool cannot change what the gateway forwards — nor the
    ``/v1/models`` summary, which filters on ``gateway_status``.

    INVARIANT (restrict-only): a tool type with no base capability is IGNORED, not
    added. This is where tools DIVERGE from parameters: an unruled discovered
    request path becomes a visible DISABLED entry because ``compose_contract_entries``
    derives that status from the rules, but a ``ToolCapability`` carries both axes in
    one record — admitting an unknown type would mean INVENTING a gateway decision
    for a tool the gateway has no rule for. Silence about a known type likewise
    preserves its reviewed verdict: a partial source is not a denial.
    """
    verdicts = {observation.tool_type: observation.support for observation in overlay}
    return tuple(
        tool
        if tool.tool_type not in verdicts
        else tool.model_copy(update={"provider_support": verdicts[tool.tool_type]})
        for tool in base
    )


def supported_tool_types(tools: Iterable[ToolCapability]) -> tuple[str, ...]:
    """Sorted accepted tool-type values whose gateway status is enabled."""
    return tuple(sorted({tool.tool_type for tool in tools if tool.gateway_status == "enabled"}))


def compose_contract_entries(
    rules: Iterable[ParameterProjectionRule],
    observations: Iterable[ProviderParameterObservation],
    *,
    auth_mode: AuthMode,
) -> tuple[ParameterContractEntry, ...]:
    """Overlay provider observations with gateway rules for one auth mode.

    - A rule applicable to ``auth_mode`` produces an ENABLED entry.
    - A rule the gateway HAS but which does not cover ``auth_mode`` produces a
      DISABLED entry with ``projection_not_available_for_auth_mode``, carrying the
      modes that DO cover it.
    - An observed-but-unruled path produces a DISABLED entry with
      ``projection_not_implemented`` — visible, but never dispatchable.

    INVARIANT (OME-649): a rule is never DROPPED for not covering the read's auth
    mode; only its ``gateway.status`` reacts. Filtering it out here would make the
    contract claim the gateway has no projection at all for that path, which is
    both false and unactionable — the client cannot see that switching credentials
    would enable it. Dispatch is unaffected: it filters rules by auth mode on its
    OWN path (``parameter_projection``), and every entry produced here for a
    non-covering mode is DISABLED, so nothing new becomes forwardable.

    INVARIANT: the published ``applicable_auth_modes`` is the rule's real tuple, so
    the contract shows the same value ``_rules_revision`` already hashes. The
    identity digest covers EVERY rule regardless of the read's mode; publishing
    only the covering ones meant hashing a field the document never showed.
    """
    by_path = {rule.request_path: rule for rule in rules}
    observed = {obs.request_path: obs for obs in observations}
    entries: list[ParameterContractEntry] = []
    for path in sorted(set(by_path) | set(observed)):
        rule = by_path.get(path)
        obs = observed.get(path)
        # ``covering`` is the rule that AUTHORIZES this read; ``rule`` is merely the
        # rule that EXISTS. Keeping them as separate names is what lets the three
        # cases below stay one expression each.
        covering = rule if rule is not None and auth_mode in rule.applicable_auth_modes else None
        if rule is None:
            reason = _DISABLED_UNPROJECTED_REASON
        elif covering is None:
            reason = _DISABLED_AUTH_MODE_REASON
        else:
            reason = None
        entries.append(
            ParameterContractEntry(
                request_path=path,
                # The rule's reviewed schema wins wherever one exists — including on
                # a disabled-by-auth row, where it is exactly the validation the
                # client would face after connecting a covering credential.
                schema=(rule.parameter_schema if rule is not None else None)
                or (obs.parameter_schema if obs is not None else None),
                provider_support=obs.support if obs else "unknown",
                provider_source=obs.source if obs else "none",
                provider_stale=obs.stale if obs else False,
                provider_deprecated=obs.deprecated if obs else None,
                gateway_status="enabled" if covering else "disabled",
                gateway_projection=covering.projection_kind if covering else None,
                gateway_reason=reason,
                # A disabled row forwards nothing, so it keys nothing — ``bypass``
                # describes what this read actually does, in every disabled case.
                cache_behavior=covering.cache_behavior if covering else "bypass",
                applicable_auth_modes=rule.applicable_auth_modes if rule else (),
            )
        )
    return tuple(entries)
