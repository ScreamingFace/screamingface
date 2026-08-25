"""OME-791 — HuggingFace's PURE projection of what it will send, for the global cache.

FEATURE: one globally shared exact-request cache (OME-305). Until this module existed every
``huggingface/*`` request bypassed at the projection step, inheriting ``CacheBypass`` from
``ProviderPluginBase``, so an identical benchmark re-run paid full price every time.

STORY: as a benchmark operator I re-run a suite against a backend-pinned HF model from a
second account and the identical calls come back from the first run's rows — no second
dispatch, and the second account's HF token is never read.

AIDEV-NOTE: this lives OUTSIDE ``plugin.py`` for the same reason OpenRouter's and OpenAI's do.
The projection must be PURE — no I/O, no clock, no environment, no credential, no identity, no
``self.settings`` — while ``plugin.py`` is where every impure thing this provider does is wired,
including the participation gate that reads ``settings.router_api_base`` and LiteLLM's process
globals. Separate modules make that boundary visible to a reader and mean the registry-wide
purity sweep in ``tests/unit/test_global_cache_projection_purity`` is checking a file that
contains nothing else.
"""

from __future__ import annotations

from typing import Any

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON, CacheBypass

from .settings import OFFICIAL_ROUTER_API_BASE, pinned_router_target

# OME-791: the revision of THIS plugin's output-affecting preparation, as reported by
# ``global_cache_projection``.
#
# INVARIANT: bump it whenever what reaches the HF router for an UNCHANGED request changes.
# Rows have no expiry and survive deployments, so a bump is the only thing that abandons a
# generation instead of re-serving it under semantics this module no longer implements.
#
# WHY it is separate from ``parameters._REVISION``: that one versions what a caller may say
# and where each value lands; this one versions what the boundary adds on its own. Collapsing
# them would make every rule edit look like a wire change.
#
# WHAT THIS REVISION COVERS THAT ``prepared`` CANNOT (ruling 34's "fold it in and say so").
# The key material is hashed as JSON, so no live object and no ambient condition can appear in
# it. These guarantees are carried by the revision string alone, all verified against the
# installed litellm 1.97.0 in this worktree's venv:
#
#   * the HF transform passes the POST-STRIP model to the wire verbatim, so
#     ``resolved_model`` below really is the id the router resolves
#     (``llms/huggingface/chat/transformation.py:123-156``; pinned at the HTTP wire by
#     ``tests/unit/huggingface/test_huggingface_dispatch.py``).
#   * the ``{api_base}/chat/completions`` URL shape, including the ``rstrip("/")``
#     normalisation applied before the suffix is appended (``transformation.py:26-38``).
#   * a non-None ``api_base`` WINS over litellm's ambient ``HF_API_BASE`` /
#     ``HUGGINGFACE_API_BASE`` environment fallbacks — ``get_complete_url`` tests
#     ``if api_base is not None`` ahead of the ``elif os.getenv(...)`` branch
#     (``transformation.py:81-99``, same read at ``:69-79``). This is what makes the projected
#     base a promise rather than a hope.
#   * pinning the base short-circuits ``_fetch_inference_provider_mapping``, whose lru-cached,
#     env-keyed lookup would otherwise make the upstream model not a function of the request
#     (``transformation.py:131-132`` returns early when ``litellm_params["api_base"]`` is set).
#   * the ambient-LiteLLM conditions enumerated in ``runtime_guard.unsafe_litellm_global_state``.
#     This revision is only meaningful for a process where none of them held; participation is
#     what enforces that, and widening the accepted set is a mandatory bump here.
#
# A litellm upgrade touching any of the above is a mandatory bump.
GLOBAL_CACHE_ADAPTER_REVISION = "huggingface-global-cache-2026-08"


def project_global_cache_request(body: dict[str, Any]) -> dict[str, Any] | CacheBypass:
    """What HuggingFace will send, as a deterministic function of the body alone.

    INVARIANT: PURE. No I/O, no clock, no randomness, no credential, no identity, no settings
    read. The same request keys identically in every deployment — which is what lets one row
    be shared globally instead of partitioned per host. The operator-configurable router base
    is handled by declining PARTICIPATION, never by reading it here (plan D3).

    INVARIANT: TOTAL. Every input is either a projection or a ``CacheBypass``; nothing raises.
    A projection may never fail a request, only decline to key it.

    INVARIANT (owner-approved MVP semantics): EVERY route-valid backend-pinned id projects,
    whether or not it appears in ``default_models``. The catalog publishes; it does not admit.
    Reading ``self.settings.default_models`` here would break purity outright — one host's seed
    list would make its keys differ from another's while each host's own determinism test still
    passed.

    ACCEPTED CONSEQUENCE — a HIT re-checks nothing. The router validates model existence,
    backend availability and caller access on the MISS that filled the row; a later hit performs
    no availability and no access check. So an exact replay may still answer after a model has
    been withdrawn, a backend has stopped serving it, or the caller has lost access. For HF this
    also has a licensing dimension recorded in the spec: most seeds are GATED repositories whose
    access requires per-account license acceptance, so a row filled by an account that accepted a
    license can be served to one that never did. That is the approved exact-replay/cross-account
    behaviour, escalated to the owner rather than decided here: the cache changes who may READ a
    stored answer, never what goes on the wire.
    """
    model = body.get("model")
    # WHY the isinstance guard comes FIRST: ``pinned_router_target`` reaches
    # ``_validate_model_slug``, which calls ``.startswith`` on its argument and therefore
    # raises AttributeError for None, int, dict or list. Core would swallow that into a silent
    # permanent bypass, but this function's contract is TOTAL, so it is guarded here where the
    # totality test can see it.
    if not isinstance(model, str):
        return CacheBypass(reason=PROJECTION_BYPASS_REASON)
    target = pinned_router_target(model)
    if target is None:
        # Two distinct classes land here, deliberately sharing one answer:
        #
        # 1. a MALFORMED id, which ``prepare_chat_body``'s downstream handler would refuse.
        #    Sharing ``_validate_model_slug`` with the dispatch path is what stops a stored row
        #    from answering 200 for a request the gateway must refuse — the cache is read BEFORE
        #    preparation, so the two predicates cannot be allowed to drift apart.
        # 2. an UNSUFFIXED id, which dispatches perfectly well. It is refused because without
        #    ``:<backend>`` the router picks a provider PER REQUEST, so no single upstream call
        #    describes the next one. Replaying one backend's answer for a request that would
        #    have gone elsewhere corrupts model attribution — for a benchmark product that is a
        #    wrong answer, not a stale one.
        #
        # AIDEV-NOTE: OBSERVED TO FIRE. This guard was neutralised on 2026-08-20 and
        # ``huggingface/deepseek-ai/DeepSeek-R1`` (unsuffixed) was pushed through
        # ``build_global_cache_plan``. Observed symptom, not predicted: it projected
        # ``resolved_model="deepseek-ai/DeepSeek-R1:"`` — a bogus EMPTY backend — and produced
        # the real, storable key hash
        # ``017a1b3f728f1ad79882d705856bbf4679bc7cb4d6292760bdc7ad7303ac9e21``. So the failure
        # mode is not a decline; it is a permanent row keyed under a model id that names no
        # backend, replayable to any later request for that repo whichever backend the router
        # would have picked. ``test_an_unsuffixed_id_bypasses_even_though_it_dispatches_fine``
        # failed as required. Guard restored.
        return CacheBypass(reason=PROJECTION_BYPASS_REASON)
    repo, backend = target
    return {
        # The UPSTREAM id: litellm strips the ``huggingface/`` prefix and passes the remainder
        # to the wire verbatim. The caller's prefixed string is keyed separately by the core as
        # ``requested_model``, so nothing is lost by narrowing to the upstream form here.
        #
        # INVARIANT: the ``:<backend>`` suffix is RETAINED. It selects which inference provider
        # answers, so it is output-affecting; keeping it in ``resolved_model`` is what makes two
        # backends for one repo key differently as a structural consequence, with no separate
        # mechanism to keep in sync.
        "resolved_model": f"{repo}:{backend}",
        "provider_adapter_revision": GLOBAL_CACHE_ADAPTER_REVISION,
        # INVARIANT: a FRESH dict per call. The core hashes ``prepared`` whole and does NOT copy
        # it (``global_eligibility._projected`` returns it uncopied), so a shared module-level
        # table would let one reader alter every later request's key material.
        #
        # WHY it participates in the key even though it is a constant: ``prepared`` is rendered
        # WHOLESALE into the canonical mapping — it is not filtered against
        # ``EXCLUDED_TRANSPORT_FIELDS``, which governs the caller's body rather than a
        # projection's output. Given participation gating, every keying deployment sends this
        # same base, so it discriminates nothing TODAY; it stays because it is the truthful
        # statement of what dispatch sends, and because loosening the gate later would then find
        # the key already correct instead of needing a retro-fit.
        #
        # ``api_key`` and ``extra_headers`` are absent on purpose: the former is stripped and
        # core-excluded, the latter is a dispatch-control field a caller cannot set.
        "prepared": {"api_base": OFFICIAL_ROUTER_API_BASE},
    }
