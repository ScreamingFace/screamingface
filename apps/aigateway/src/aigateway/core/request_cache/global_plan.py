"""OME-305 — the pre-credential global cache decision for one chat request.

FEATURE: one global exact-request cache. The route answers "is there a shared answer
for exactly this effective call?" after merging profile defaults and before resolving
an auth mode or provider credential. This module is that decision as a pure function.

STORY: as a benchmark operator I re-run a suite from a second account and the
identical calls are served from the first run's responses — the second account's
key is never read, and it need not even be connected.

INVARIANT: PURE and TOTAL. No ``Request``, no ``app.state``, no store, no await,
no clock. Every failure — an operator gate that is off, a caller opt-out, a
malformed control, an unkeyable request, a provider hook that raises — is a plan
that does not participate, with a reason from the closed vocabulary. Nothing here
raises into the request path, because the cache may never become an availability
dependency.

INVARIANT: identity is structurally absent. There is no account, profile, user,
auth-mode or credential parameter on this signature, so the only rule set it can
possibly consult is the auth-mode-INDEPENDENT one — which is what makes the plan
the same for every caller sending the same call.

AIDEV-NOTE: the async half — the store read, the write-back and the response
headers — deliberately lives in the route layer. Keeping THIS half free of I/O is
what lets the identity-invariance and projection-purity properties be tested
without a profile, a connection, a credential blob or a database.
"""

from __future__ import annotations

from typing import Any, Final

from ..cache_ports import PROJECTION_BYPASS_REASON, CacheBypass
from ..plugin_base import ProviderPluginBase
from .global_controls import GlobalCacheControls
from .global_eligibility import BYPASS_RULE_SET, BYPASS_UNSUPPORTED_SHAPE, is_text
from .global_keys import GlobalCacheKeyResult, build_global_cache_key

# The operator's kill switch. Published in ``X-AIGW-Cache-Reason`` like every other
# reason, so an operator reading a response can tell "off" from "not cacheable".
#
# INVARIANT: this keeps the published wire spelling (owner decision 53, "rename only what must
# change"). URL4 reads these bytes, so a rename is a caller-visible break and the owner
# declined to spend one on readability. Do NOT re-propose ``cache_disabled``: the
# argument for it — that a bare ``disabled`` reads as "something was disabled" beside
# siblings like ``opted_out`` — was made and REJECTED.
BYPASS_DISABLED: Final = "disabled"


type GlobalCacheDecision = GlobalCacheKeyResult | CacheBypass


def build_global_cache_plan(
    *,
    body: dict[str, Any],
    plugin: ProviderPluginBase,
    controls: GlobalCacheControls,
    cache_enabled: bool,
) -> GlobalCacheDecision:
    """The global cache plan for a hardened caller request.

    ``body`` is the request after JSON shape validation, dispatch-control stripping,
    cache-control removal and the body-wins profile-default merge, and before auth-mode
    resolution, the auth-specific classifier, ``prepare_chat_body`` and credential injection.

    WHY the operator gate is checked FIRST: when the cache is off, nothing about
    the request can change the answer, and reporting the caller's opt-out or an
    eligibility detail instead would describe a decision that was never reached.
    """
    if not cache_enabled:
        return CacheBypass(BYPASS_DISABLED)
    try:
        # OME-884: the RAW requested model, and nothing else about the request. The gate
        # order is deliberately UNCHANGED — this still runs ahead of the caller opt-out
        # and ahead of the ``is_text`` shape check below, so the hook may be handed a
        # non-string and must be total over it.
        provider_participates = plugin.participates_in_global_cache(body.get("model"))
    except Exception:
        # Same argument as the rule-table and projection calls below: a provider hook
        # on this path costs a bypass, never the caller's request.
        provider_participates = False
    if not provider_participates:
        # A provider that is switched off must not have its stored rows replayed, and
        # the dispatch-side guards cannot deliver that: this stage runs before model
        # resolution and before any credential is read, so neither the 404 nor the 400
        # ever gets a chance to refuse the request.
        #
        # WHY it is checked BEFORE the caller's opt-out: an opt-out describes a
        # decision about a cache this request was eligible for. When the provider is
        # off there is nothing to opt out of, so reporting ``opted_out`` would
        # attribute the outcome to the caller.
        #
        # WHY ``provider_projection`` and NOT ``disabled`` — this is load-bearing and
        # was measured, not assumed. ``disabled`` is re-interpreted downstream:
        # ``chat_cache_stage._closed_gate_reason`` maps a plan-level ``disabled`` to
        # ``cache_unavailable`` whenever the cache's OWN switch is on, because at that
        # layer ``disabled`` can only have meant "the store did not answer". Returning
        # it here therefore published ``cache_unavailable`` for a switched-off
        # provider — telling an operator their cache store is broken when it is
        # healthy. ``provider_projection`` is the value the port already returns by
        # default for a provider that offers no cacheable projection, it is not
        # re-mapped, and it points at the provider rather than at the cache.
        #
        # AIDEV-NOTE: a dedicated ``provider_disabled`` would be more precise than
        # either, and is the right answer if an operator ever needs to tell "provider
        # off" from "provider cannot project". It is deliberately NOT taken here: the
        # vocabulary is a caller-visible contract (URL4 reads these bytes, and
        # ``test_global_cache_reason_vocabulary._WIRE_CONTRACT`` owns the spelling), so
        # adding a value is an owner decision rather than an implementation detail.
        return CacheBypass(PROJECTION_BYPASS_REASON)
    if not controls.participate:
        return CacheBypass(controls.bypass_reason)
    model = body.get("model")
    if not is_text(model):
        return CacheBypass(BYPASS_UNSUPPORTED_SHAPE)
    try:
        # INVARIANT (decision 1): the AUTH-MODE-INDEPENDENT rule set. No auth mode
        # is resolved yet, and ``cache_behavior`` is one unconditional value per
        # request path, so the disposition is well-defined without one.
        rules = tuple(plugin.chat_parameter_rules(model=str(model), auth_type=None))
    except Exception:
        # WHY this catch is broad: a provider rule table is third-party-shaped code
        # on a path that must not fail. A bug there costs a bypass, never the
        # caller's request. Same argument as the projection call below.
        return CacheBypass(BYPASS_RULE_SET)
    try:
        # Provider METADATA (which modes this provider offers), not caller identity.
        # A rule the provider offers in only some of its modes cannot be keyed —
        # ``_accept`` refuses it, because the key cannot see which mode the caller
        # will resolve to.
        provider_modes = tuple(plugin.available_auth_modes())
    except Exception:
        return CacheBypass(BYPASS_RULE_SET)
    built = build_global_cache_key(
        provider=plugin.custom_llm_provider,
        body=body,
        rules=rules,
        projection=plugin.global_cache_projection,
        provider_auth_modes=provider_modes,
    )
    return built
