"""OME-791 — the ambient certification behind Hugging Face's global-cache participation.

FEATURE: one globally shared exact-request cache (OME-305). A stored row is replayed to any
caller whose request keys identically, so a row is only safe to share if the process that filled
it will send what the projection SAYS it sends. This module is that certification.

STORY: as an operator I enable an unrelated LiteLLM process global — a proxy flag, a fallback
list, a callback — and Hugging Face silently stops sharing rows instead of quietly storing
answers that do not match their key.

INVARIANT: TOTAL and FAIL-CLOSED. Every unknown, every unreadable secret and every raise is a
DECLINE, never an exception into the request path. ``global_plan.py:72-77`` already swallows a
raise here into non-participation, but relying on that would make the guard's own correctness
unobservable, so totality is owned here.

INVARIANT: a decline is LOSSLESS. It suppresses lookup and write-back for this deployment; it
never invalidates, rewrites or re-keys a stored row, and it never fails a dispatch. Requests
continue normally, uncached.

AIDEV-NOTE (M5, partial remediation — read before "cleaning this up"). Sibling providers carry
near-copies of this predicate (``openai_provider/plugin.py``,
``openrouter_provider/litellm_controls.py``). Extracting ONE cross-provider core helper is the
right end state and is deliberately NOT done here:

  * the three condition sets are NOT identical — each provider's reachable litellm surface
    differs, so a shared helper needs a union plus per-provider deltas;
  * more importantly the RESPONSES differ. Hugging Face declines cache participation; some
    sibling paths hard-fail dispatch. Copying a condition without its response would convert a
    lossless cache decline into a refused request. Do NOT mirror these conditions mechanically
    into another provider.
OME-884 IS present in this base and the participation hook now accepts the raw requested model,
so the port signature is settled and is NOT what blocks extraction. The differing condition sets
and — above all — the differing failure responses are. Repository-wide consolidation stays a
FOLLOW-UP for that reason. Cross-provider duplication is NOT eliminated by this change; only the
Hugging Face copy is now cohesive and single-sourced.
"""

from __future__ import annotations

import logging

import litellm
from litellm.secret_managers.main import get_secret_bool

from .settings import OFFICIAL_ROUTER_API_BASE

logger = logging.getLogger(__name__)

# The environment/secret-backed switch that selects LiteLLM Proxy independently of the module
# attribute. Named here because it is KEY-RELEVANT, not merely configuration.
PROXY_SECRET_NAME = "USE_LITELLM_PROXY"

# Decline tokens. INVARIANT: a token NEVER carries a configured value — see ``log_decline_once``.
PROXY_SECRET_REASON = f"env.{PROXY_SECRET_NAME}"
ROUTER_API_BASE_REASON = "router_api_base"
UNREADABLE_AMBIENT_STATE_REASON = "litellm.runtime_state"

# Process-global LiteLLM controls that reroute dispatch or change what reaches the wire, so a
# stored row would describe something other than what this process actually sent.
#
# WHY ``model_fallbacks`` is the load-bearing case, verified against installed litellm 1.97.0
# rather than assumed: it is read at ``main.py:602`` INSIDE ``async def acompletion``, which is
# what HF's inherited ``chat_completion`` calls —
#
#     fallbacks = fallbacks or litellm.model_fallbacks
#     if fallbacks is not None:
#         response = await async_completion_with_fallbacks(...)
#
# ``fallback_utils.py:57,62`` then re-enters ``acompletion`` with ``model=fallback``. The gateway
# strips a caller's ``fallbacks`` at ingress (``request_hardening.py:82``), so only the process
# global can set it, and the fill path stores any answer carrying a ``finish_reason`` without
# comparing its model to the key's. One process-global setting therefore writes ANOTHER MODEL'S
# ANSWER under an HF key, in a store whose rows never expire. That is a wrong answer, not a stale
# one — which is why a coarse provider-wide decline is the right trade.
#
# ``headers`` reaches the HF wire SPECIFICALLY: ``main.py:2994`` inside ``_complete_huggingface``
# does ``hf_headers = headers or litellm.headers``. Two processes with different globals would
# key alike and send differently — ruling 34's exact hazard.
#
# ``use_litellm_proxy`` (OME-791 B2) reroutes dispatch away from router.huggingface.co entirely:
# ``LiteLLMProxyChatConfig._should_use_litellm_proxy_by_default`` is consulted at the TOP of
# ``get_llm_provider`` (``get_llm_provider_logic.py:151``) and rewrites the provider to
# ``litellm_proxy``. The projected ``api_base`` would then be a statement about an endpoint the
# request never reached.
#
# ``disable_stop_sequence_limit`` (M1) changes the FINAL WIRE VALUE while the caller body and the
# key stay byte-identical: litellm truncates a long ``stop`` list unless it is set.
#
# ``enable_json_schema_validation`` (M2) governs post-dispatch acceptance of a JSON-schema
# ``response_format`` — which this provider KEYS. A cache hit returns before that validation runs,
# so a row filled under one setting would bypass the refusal the other setting performs.
LITELLM_DISPATCH_GLOBALS: tuple[str, ...] = (
    "model_fallbacks",
    # Coarser than the sibling exemplars, which test ``model in aliases``. The narrow form IS
    # expressible here — ``participates_in_global_cache`` carries the raw requested model since
    # OME-884 (``_provider.py:278``) — and Hugging Face deliberately keeps the provider-wide
    # decline for the MVP anyway: it is the fail-safe direction, declining more often and never
    # less. Exact-model narrowing is a non-blocking cross-provider follow-up, not an
    # impossibility. COST OF THE CONSERVATIVE FORM, so nobody rediscovers it as a bug: ONE
    # unrelated alias entry anywhere in the deployment stops Hugging Face caching entirely for
    # the life of the process. Lossless, logged once, and visible only as a 100% miss rate.
    "model_alias_map",
    "headers",
    "use_litellm_proxy",
    "disable_stop_sequence_limit",
    "enable_json_schema_validation",
)

# ``pre_call_rules``/``post_call_rules`` only ever RAISE (``litellm_core_utils/rules.py:29-58``),
# so they cannot corrupt a response body. They are guarded for a different reason: a cache HIT
# returns at ``routes/chat.py:351`` BEFORE dispatch, so a deployment's configured refusal would
# be silently skipped for a stored row while still applying to a miss. ``drop_params`` changes
# WHICH PARAMETERS reach the wire, so one body produces two different upstream calls.
#
# AIDEV-NOTE (M8): ``additional_drop_params`` was previously listed here and does NOT exist as a
# litellm module global on the installed 1.97.0 — it is a per-request kwarg. Guarding a
# non-existent attribute is a no-op that reads like coverage. Verified absent via
# ``hasattr(litellm, "additional_drop_params")``; ``test_every_guarded_global_exists_on_litellm``
# now fails if any name here stops existing.
LITELLM_RULE_GLOBALS: tuple[str, ...] = (
    "pre_call_rules",
    "post_call_rules",
    "drop_params",
)

# Guarded on PRESENCE rather than truthiness: a configured-but-falsy auth object still means a
# proxy auth path is wired up.
LITELLM_PRESENCE_GLOBALS: tuple[str, ...] = ("proxy_auth",)

LITELLM_CALLBACK_GLOBALS: tuple[str, ...] = (
    "callbacks",
    "input_callback",
    "success_callback",
    "failure_callback",
    "_async_input_callback",
    "_async_success_callback",
    "_async_failure_callback",
)

# ``"cache"`` is litellm's own bookkeeping entry, not a third-party observer; both sibling
# exemplars permit it, and excluding it would decline in ordinary deployments.
EXEMPT_CALLBACK = "cache"

# Every litellm module global this guard reads. The M8 conformance test asserts each one still
# EXISTS, so a litellm rename turns a silently-dead guard into a red test.
GUARDED_LITELLM_GLOBALS: tuple[str, ...] = (
    LITELLM_DISPATCH_GLOBALS
    + LITELLM_RULE_GLOBALS
    + LITELLM_PRESENCE_GLOBALS
    + LITELLM_CALLBACK_GLOBALS
)


def _proxy_selected_by_secret() -> bool:
    """Whether the environment/secret-backed proxy switch is on.

    WHY this exists SEPARATELY from the ``use_litellm_proxy`` module attribute: litellm checks
    the secret FIRST (``llms/litellm_proxy/chat/transformation.py:73``) and returns True on it
    alone, so an environment variable reroutes dispatch while the attribute stays ``False``.
    Guarding only the attribute leaves that path wide open.

    AIDEV-NOTE: litellm's own ``_should_use_litellm_proxy_by_default`` is deliberately NOT called
    (B2.4). It is private, and it additionally consults per-request ``litellm_params`` this hook
    does not have — so calling it here would answer a different question than the one asked.

    INVARIANT: fail CLOSED. ``get_secret`` can reach a configured key-management system, so it may
    raise or block; an unreadable switch means the answer is unknown, and unknown must decline.
    """
    try:
        return get_secret_bool(PROXY_SECRET_NAME) is True
    except Exception:
        return True


def unsafe_litellm_global_state() -> str | None:
    """The ambient LiteLLM control that forbids sharing rows, or ``None`` if the process is clean.

    AIDEV-NOTE: ``litellm.HuggingFaceChatConfig().get_config()`` was considered and REJECTED.
    ``_complete_huggingface`` (``main.py:2971-3011``) reads no ``*Config.get_config()`` at all,
    and ``BaseConfig.get_config`` reads only ``cls.__dict__``, so the condition cannot fire on
    anything reaching the HF wire — while merely EVALUATING it instantiates the class, whose
    ``__init__`` sets ``self.__class__._is_base_class = False`` and thus mutates litellm process
    state on every request. A guard that protects nothing and mutates shared state is strictly
    worse than no guard.
    """
    for field in LITELLM_DISPATCH_GLOBALS + LITELLM_RULE_GLOBALS:
        if getattr(litellm, field, None):
            return f"litellm.{field}"
    for field in LITELLM_PRESENCE_GLOBALS:
        if getattr(litellm, field, None) is not None:
            return f"litellm.{field}"
    for field in LITELLM_CALLBACK_GLOBALS:
        callbacks = getattr(litellm, field, None)
        if callbacks and any(callback != EXEMPT_CALLBACK for callback in callbacks):
            return f"litellm.{field}"
    if _proxy_selected_by_secret():
        return PROXY_SECRET_REASON
    return None


def global_cache_decline_reason(*, configured_router_api_base: object) -> str | None:
    """The single Hugging Face answer to "may this deployment share rows?" (M5.2).

    ``None`` participates; any string declines and names the condition.

    INVARIANT: this is the ONE source of truth used by ``participates_in_global_cache``. The
    router-base comparison lives here rather than in ``plugin.py`` so that no second predicate
    can drift from it — the failure mode M5 records is precisely a condition added in one copy
    and not the others.

    D3 — the operator-overridable router base. The projection emits the OFFICIAL constant
    unconditionally, so a deployment pointed anywhere else would key its requests as though they
    had gone to the official router and share rows with deployments that did. That is
    cross-endpoint contamination of a globally shared cache.

    WHY the comparison is NORMALISED rather than literal: litellm's ``_build_chat_completion_url``
    does ``model_url.rstrip("/")`` before appending ``/chat/completions``
    (``transformation.py:26-28``), so a trailing slash produces a byte-identical upstream call. A
    literal ``!=`` would silently disable caching for a deployment that is provably sending the
    same request. The normalisation stops there ON PURPOSE: this is a safety gate, so every
    accepted spelling must be provably wire-equivalent, not merely plausible.

    AIDEV-NOTE: OBSERVED TO FIRE. This gate was neutralised on 2026-08-20 and
    ``test_a_row_filled_at_the_official_base_is_not_replayed_after_an_override`` was run. Observed
    symptom: the deployment configured for ``https://proxy.internal/v1`` was served
    ``X-AIGW-Cache: hit`` from the row a DIFFERENT deployment filled against the official router —
    a 200 carrying an answer its own upstream never produced, with no dispatch. Gate restored.
    """
    try:
        if not isinstance(configured_router_api_base, str):
            return ROUTER_API_BASE_REASON
        if configured_router_api_base.rstrip("/") != OFFICIAL_ROUTER_API_BASE.rstrip("/"):
            return ROUTER_API_BASE_REASON
        return unsafe_litellm_global_state()
    except Exception:
        # INVARIANT: third-party ambient objects may raise from attribute access, truthiness or
        # iteration. A runtime the guard cannot inspect is uncertified, so caching gives way while
        # dispatch remains available. The token carries no configured value or caller data.
        return UNREADABLE_AMBIENT_STATE_REASON


# WHY module state for logging: every decline path publishes the SAME wire reason
# (``provider_projection``), so without a log an operator whose HF caching silently stopped has no
# way to learn which check declined. But this runs per request, so an unconditional warning would
# be its own operational problem. One line per CONDITION per process is the compromise.
_LOGGED_DECLINES: set[str] = set()


def log_decline_once(reason: str) -> None:
    """Name the declining condition once per process, never the configured value.

    INVARIANT: the TOKEN only. ``router_api_base`` can carry an internal hostname and
    ``litellm.headers`` can carry tenant or auth material, so no value is ever logged — and no
    caller identity, prompt content or cache key is available here to leak in the first place.
    """
    if reason in _LOGGED_DECLINES:
        return
    _LOGGED_DECLINES.add(reason)
    logger.warning(
        "huggingface is not participating in the global cache: %s (this deployment's rows "
        "are neither read nor written; requests dispatch normally)",
        reason,
    )


def reset_decline_log() -> None:
    """Clear the once-per-process log memo. For tests only."""
    _LOGGED_DECLINES.clear()
