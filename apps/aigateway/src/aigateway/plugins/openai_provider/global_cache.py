"""OME-884 — direct OpenAI's PURE projection of what it will send, for the global cache.

FEATURE: one globally shared exact-request cache (OME-305). OME-864 shipped direct
`openai/*` dispatch under the base class's safe ``CacheBypass``, so an identical
benchmark re-run paid full price every time. Here the gateway's own output-affecting
preparation is PROJECTED, which is what makes a stored response safe to replay.

STORY: as a benchmark operator I re-run a suite from a second account and the identical
`openai/*` calls come back from the first run's rows — no second dispatch, and the
second account's key is never read.

AIDEV-NOTE: this lives OUTSIDE ``plugin.py`` for the same reason OpenRouter's does. The
projection must be PURE — no I/O, no clock, no environment, no credential, no identity,
no ``self.settings`` — while ``plugin.py`` is where every impure thing this provider
does is wired (the runtime-safety guard reads ``os.environ`` and LiteLLM globals; it
belongs there, not here). Separate modules make that boundary visible to a reader and
mean the registry-wide purity sweep in ``tests/unit/test_global_cache_projection_purity``
is checking a file that contains nothing else.
"""

from __future__ import annotations

from typing import Any

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON, CacheBypass

from .settings import OFFICIAL_API_BASE, is_route_valid_model_id, upstream_model_id

# OME-884: the revision of THIS plugin's output-affecting preparation, as reported by
# ``global_cache_projection``.
#
# INVARIANT: bump it whenever what reaches OpenAI for an UNCHANGED request changes —
# a different base, a new gateway-owned control, a change to the transport guarantees
# listed below, or an upgrade of LiteLLM/openai that alters the wire. Rows have no
# expiry and survive deployments, so a bump is the only thing that abandons a
# generation instead of re-serving it under semantics this module no longer implements.
#
# WHY it is separate from the RULES revision in ``parameters.py``: that one versions
# what a caller may say and where each value lands; this one versions what the boundary
# adds on its own. Collapsing them would make every rule edit look like a wire change.
#
# WHAT THIS REVISION COVERS THAT ``prepared`` CANNOT (ruling 34's "fold it in and say
# so"). The key material is hashed as JSON, so no sentinel and no live object may
# appear in it. These guarantees are therefore carried by the revision string alone:
#
#   * ``OpenAI-Organization`` and ``OpenAI-Project`` suppressed with ``Omit()``
#     sentinels. This is the explicit condition that LICENSES cross-account replay:
#     with both headers suppressed, two accounts sending the identical effective
#     request produce byte-identical upstream calls, so one row is correct for both.
#     Restore either header and this revision MUST be bumped in the same commit —
#     stored rows would otherwise be replayed across organizations that no longer send
#     the same request.
#   * a request-local ``AsyncOpenAI`` client with ``max_retries=0``, over an httpx
#     client pinned to ``verify=True``, ``trust_env=False``, ``follow_redirects=False``
#     — TLS verification on, ambient proxy/CA environment ignored, no redirect
#     following.
#   * the exact installed LiteLLM behaviour (pinned at 1.97.0), which owns the
#     ``max_tokens`` -> ``max_completion_tokens`` mapping for GPT-5/o-series models and
#     the Chat-Completions handler selection. ``tests/unit/openai/test_openai_dispatch``
#     pins both at the final HTTP wire; a change there is a mandatory bump here.
GLOBAL_CACHE_ADAPTER_REVISION = "openai-global-cache-2026-08"


def gateway_dispatch_controls() -> dict[str, Any]:
    """The gateway-owned LiteLLM controls this boundary adds to every direct call.

    # INVARIANT: ONE table with TWO readers — this projection and
    # ``OpenAIProviderPlugin.chat_completion``. That is what makes "the key describes
    # what dispatch sends" true by construction instead of by two lists a maintainer
    # must remember to edit together. Adding an entry here changes the wire AND the
    # key, which is exactly the coupling ruling 34 asks for; it is still a mandatory
    # ``GLOBAL_CACHE_ADAPTER_REVISION`` bump, because old rows were keyed without it.
    # INVARIANT: a FRESH dict (including the nested one) per call. The core hashes
    # ``prepared`` whole and does not copy it, so a shared mutable table would let one
    # reader alter every later request's key material.
    # WHY each entry is output-affecting rather than transport noise:
    #   api_base                    — which endpoint answers.
    #   caching / cache             — LiteLLM's OWN response cache is disabled, so the
    #                                 answer is a fresh generation, not litellm's replay.
    #   num_retries / max_retries   — zero gateway-level retries: one request, one
    #                                 upstream call, no silent second sampling.
    #   _skip_responses_api_bridge  — Chat Completions only. With the bridge active a
    #                                 GPT-5 call is re-shaped into a Responses API call,
    #                                 which is a different upstream operation entirely.
    """
    return {
        "api_base": OFFICIAL_API_BASE,
        "caching": False,
        "cache": {"no-cache": True, "no-store": True},
        "num_retries": 0,
        "max_retries": 0,
        "_skip_responses_api_bridge": True,
    }


def project_global_cache_request(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
    """What direct OpenAI will send, as a deterministic function of the body alone.

    INVARIANT: PURE. No I/O, no clock, no randomness, no credential, no identity, no
    settings read. The same request keys identically in every deployment — which is
    what lets one row be shared globally instead of partitioned per host.

    INVARIANT: TOTAL. Every input is either a projection or a ``CacheBypass``; nothing
    raises. A projection may never fail a request, only decline to key it.

    INVARIANT (owner-approved MVP semantics): EVERY route-valid `openai/*` id projects,
    whether or not it appears in ``default_models``. The catalog publishes; it does not
    admit. Reading ``self.settings`` here would also break purity outright — one host's
    seed list would make its keys differ from another's while each host's own
    determinism test still passed.

    ACCEPTED CONSEQUENCE — a HIT re-checks nothing. OpenAI validates model existence and
    caller access on the MISS that filled the row; a later hit performs no availability
    and no access check. So an exact replay may still answer after the model has
    disappeared upstream or become unavailable to the current caller. This is the
    approved exact-replay/cross-account behaviour, not an oversight: the cache changes
    who may READ a stored answer, never what goes on the wire.

    WHY a malformed id BYPASSES rather than keying: ``prepare_chat_body`` refuses it
    with a 400, and the cache is read BEFORE preparation. Without the bypass a stored
    entry could answer 200 for a request the gateway must refuse — and the two use the
    SAME predicate, so they cannot drift apart.
    """
    model = body.get("model")
    if not is_route_valid_model_id(model):
        return CacheBypass(reason=PROJECTION_BYPASS_REASON)
    return {
        # The UPSTREAM id: LiteLLM strips its provider prefix exactly once at the wire
        # (pinned by the MockTransport payload assertions in ``test_openai_dispatch``),
        # so this is the id OpenAI actually resolves. The caller's prefixed string is
        # keyed separately by the core as ``requested_model``.
        "resolved_model": upstream_model_id(str(model)),
        "provider_adapter_revision": GLOBAL_CACHE_ADAPTER_REVISION,
        "prepared": gateway_dispatch_controls(),
    }
