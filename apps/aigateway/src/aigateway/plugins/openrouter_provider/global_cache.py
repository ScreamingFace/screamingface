"""OME-305 — OpenRouter's pure projection of what it will send, for the global cache.

FEATURE: one globally shared exact-request cache. Under v1 an OpenRouter request
could never be cached, because ``prepare_chat_body`` rewrites the body and an
inspected rewrite is indistinguishable from an unreviewed one. Here the preparation
is PROJECTED instead, so a bare request becomes cacheable and a routing-controlled
one is keyed by the policy that will actually be sent.

AIDEV-NOTE: this lives OUTSIDE ``plugin.py`` for a reason worth keeping. The
projection must be pure — no I/O, no clock, no credential, no identity — while
``plugin.py`` is where every impure thing this provider does is wired. Separate
modules make that boundary visible to a reader and mean the purity sweep in
``tests/unit/test_global_cache_projection_purity.py`` is checking a file that
contains nothing else. (It also keeps ``plugin.py`` under the 450-line limit, which
is what forced the split, but the homing is the reason to keep it.)
"""

from __future__ import annotations

from typing import Any

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON, CacheBypass
from aigateway.core.parameter_projection import WRAPPER_KEY

from .dispatch_errors import _UnexpectedRoutingPolicyError
from .parameters import EXTRA_BODY_OBJECT, TOP_K_LEAF
from .routing_policy import PROVIDER_OBJECT, build_provider_policy, project_routing_controls
from .settings import (
    GATEWAY_MODEL_PREFIX,
    OFFICIAL_API_BASE,
    is_online_variant,
    is_valid_upstream_model_id,
)

# OME-305: the revision of THIS plugin's output-affecting preparation, as reported
# by ``global_cache_projection``.
#
# INVARIANT: bump it whenever ``prepare_chat_body`` or the projection changes what
# reaches OpenRouter for an unchanged request — a new pinned base, a different
# model-identity rule, a change to how the routing policy is reconstructed. Every
# stored global entry for this provider is then abandoned instead of being re-served
# under semantics it was not produced with.
#
# WHY it is separate from the RULES revision in ``parameters.py``: that one versions
# what a caller may say and where each value lands; this one versions what the
# boundary adds on its own. A change to either must invalidate, and collapsing them
# into one constant would make every rule edit look like a dispatch change.
#
# OME-712 (`...-08` -> `...-08b`): `:online` ids USED to dispatch and fill entries, and are
# now refused. The projection below bypasses them, but a bypass only stops NEW rows — rows
# written before this landed stay readable under their old key. Bumping abandons them.
#
# OME-781 (`...-08b` -> `...-08c`): `web_search` / `web_search_excluded_domains` moved from
# `cache_behavior="bypass"` to `"keyed"` (the deployment blocklist that made bypass necessary
# is deleted). Rows written under the old bypass semantics were never stored for a search
# request at all, so there is nothing to serve stale — but this bump also folds in the
# `apply_web_search` envelope-shaping constants (the `id`/`engine` policy dict), which were
# never part of any prior revision's contract for this key path. Abandoning the whole
# generation here is the same discipline as every other adapter-revision bump: readers must
# never be served an entry keyed under a semantics this module no longer implements.
#
# 08d (OME-800): `apply_web_search` stopped naming the search engine, so the envelope this
# key path projects changed shape. Entries written while `engine: "native"` was forced
# describe a request this module no longer sends — a different upstream retrieval path, and
# for models without built-in search, one that erred rather than answering.
GLOBAL_CACHE_ADAPTER_REVISION = "openrouter-global-cache-2026-08d"

# OME-952: register the revision with the core-owned registry the admin cache-snapshot
# upload compares manifests against. Plugins import core (never the reverse), and this
# module is imported by ``plugin.py`` at load time, so the registration is in place before
# any route can run. Registering HERE keeps the constant single-sourced: the registry and
# the projection report the same name.
from aigateway.core.request_cache.revisions import register_adapter_revision  # noqa: E402

register_adapter_revision("openrouter_adapter", GLOBAL_CACHE_ADAPTER_REVISION)


def project_global_cache_request(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
    """What this provider will send, as a deterministic function of the body.

    The two output-affecting things this boundary adds are the pinned API base and
    the reconstructed routing policy; both are projected here.

    INVARIANT: pure. No I/O, no clock, no randomness, no credential, no identity —
    it receives the request body alone and returns the same answer every time.
    Attribution headers and the injected key are TRANSPORT and stay out.

    INVARIANT: ``resolved_model`` is the UPSTREAM id. The gateway prefix is LiteLLM's
    provider prefix and is stripped exactly once at the wire (D8), so the upstream
    remainder is what OpenRouter actually resolves — and an id this plugin would
    refuse to dispatch yields a bypass here rather than a raise, because a projection
    may never fail a request.

    INVARIANT (ledger decision 12): reconstruction failure is a projection-time
    BYPASS. ``build_provider_policy`` refuses a policy it cannot rebuild, and that
    refusal is a 503 on dispatch; moving the cache read ahead of
    ``prepare_chat_body`` must not turn such a request into a 200 hit. Calling the
    real reconstruction here is also what pins the price and ``zdr`` equivalences:
    two spellings of one ceiling, and a ``false`` flag that is sent as nothing at
    all, canonicalize to one policy and therefore to one key.

    AIDEV-NOTE: the bypass above is proven by a tripwire that was OBSERVED TO FIRE —
    with the ``except`` clause replaced by ``policy = {}``,
    ``test_a_body_whose_routing_policy_cannot_be_rebuilt_is_never_served_from_cache``
    fails with a real key hash in the store's read log. That is the wrong-hit class
    this guard closes: an unrebuildable policy would key as if no policy were asked
    for, so a request demanding a price ceiling would collide with one demanding
    none. Do not replace this bypass with a fallback policy value.
    """
    model = body.get("model")
    if not isinstance(model, str) or not model.startswith(GATEWAY_MODEL_PREFIX):
        return CacheBypass(reason=PROJECTION_BYPASS_REASON)
    upstream = model[len(GATEWAY_MODEL_PREFIX) :]
    if not is_valid_upstream_model_id(upstream):
        return CacheBypass(reason=PROJECTION_BYPASS_REASON)
    if is_online_variant(upstream):
        # OME-712: ``prepare_chat_body`` REFUSES this id with a 400 — the `:online` suffix is
        # OpenRouter's implicit search, a second route around the provider-neutral `web_search`
        # parameter and the deployment exclusions it carries. The refusal alone is not enough,
        # because the cache is read BEFORE preparation: without this, a stored entry would
        # answer 200 for a request the gateway must refuse. Same class as the routing-policy
        # bypass below, and the same predicate as the dispatch guard so the two cannot drift.
        return CacheBypass(reason=PROJECTION_BYPASS_REASON)
    wrapper = body.get(WRAPPER_KEY)
    try:
        policy = build_provider_policy(project_routing_controls(wrapper))
    except _UnexpectedRoutingPolicyError:
        return CacheBypass(reason=PROJECTION_BYPASS_REASON)
    prepared: dict[str, Any] = {"api_base": OFFICIAL_API_BASE, PROVIDER_OBJECT: policy}
    if isinstance(wrapper, dict) and TOP_K_LEAF in wrapper:
        # OME-305: `provider_params.top_k` is declared ``cache_behavior="keyed"``, and
        # a provider-native value participates in the key ONLY by appearing here — the
        # rule contributes an empty entry precisely because `prepared` is hashed whole.
        # So the declaration is only honoured if the leaf is really projected; without
        # it every top_k request bypassed with `unprojected_parameter`.
        #
        # INVARIANT: emitted ONLY when the caller sent the leaf, never as an empty or
        # defaulted root. The key builder's gate is root-only, so `extra_body` present
        # means "every rule targeting this root is keyed, trust the provider" — an
        # unconditional root would silently un-key a leaf instead of bypassing it.
        #
        # WHY the value is copied raw rather than coerced: eligibility validates it
        # against ``OPENROUTER_TOP_K_SCHEMA`` and bypasses on failure BEFORE this
        # projection is consulted, and dispatch forwards the same raw value, so
        # normalizing here would key a request the provider never receives.
        prepared[EXTRA_BODY_OBJECT] = {TOP_K_LEAF: wrapper[TOP_K_LEAF]}
    return {
        "resolved_model": upstream,
        "provider_adapter_revision": GLOBAL_CACHE_ADAPTER_REVISION,
        "prepared": prepared,
    }
