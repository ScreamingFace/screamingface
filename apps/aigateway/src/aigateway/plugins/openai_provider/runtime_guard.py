"""OME-884 — certification of the ambient LiteLLM/OpenAI runtime for direct OpenAI.

FEATURE: one global exact-request cache (OME-305). A stored row is replayable by anyone
with no model entry and no credential, so before this provider may fill or serve one the
gateway has to certify that nothing in process-global state can change what OpenAI would
answer for an identical request.

STORY: as an operator I can set a LiteLLM global and know the gateway will stop caching
direct OpenAI rather than quietly serve me answers produced under different settings.

AIDEV-NOTE: this lives OUTSIDE ``plugin.py`` because it is a cohesive responsibility with
its own contract — read ambient state, return a verdict, never raise, never touch a
request body. ``plugin.py`` keeps provider WIRING (models, credentials, parameter rules,
the HTTP error shapes) and calls in here for verdicts. It is also the mirror image of
``global_cache.py``: that module must contain nothing impure, and this one is where every
impure read lives, so neither file needs a caveat about the other's contents.

INVARIANT: this module raises nothing a caller must handle. Every public verdict is total
and fails CLOSED — an ambient read that explodes counts as unsafe, because a runtime the
gate could not inspect has not been certified.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

# The environment variable LiteLLM reads to swap the OpenAI dispatch handler. Both the
# handler it selects and the one it replaces are pinned by this plugin's adapter
# revision, so an enabled flag is a runtime the revision does not describe.
_EXPERIMENTAL_HANDLER_ENV = "EXPERIMENTAL_OPENAI_BASE_LLM_HTTP_HANDLER"
_LITELLM_GLOBAL_CALLBACK_FIELDS = (
    "callbacks",
    "input_callback",
    "success_callback",
    "failure_callback",
    "_async_input_callback",
    "_async_success_callback",
    "_async_failure_callback",
)
# Process-global LiteLLM state that disqualifies the runtime when merely TRUTHY. ONE
# tuple rather than one branch each: the verdict and the reason are identical for every
# member — ambient routing or parameter-dropping that this plugin's adapter revision does
# not describe — so spelling them as separate early returns was a list pretending to be
# control flow.
#
# INVARIANT: membership means "unsafe for BOTH readers" — the tuple feeds the shared
# guard, so a name here refuses DISPATCH too. A hazard whose blast radius is narrower does
# not belong in it; see ``_MODIFY_PARAMS_FIELD``.
# INVARIANT: every member must EXIST on the installed LiteLLM, asserted by
# ``test_every_guarded_global_still_exists_on_installed_litellm`` — a RENAMED global reads
# ``None``, falsy, so the check would pass unguarded. (``additional_drop_params`` was
# removed for that reason: 1.97.0 has no such module global, so it could never fire;
# caller-supplied values are stripped at ingress.) ``callbacks`` stay out: they need the
# ``"cache"`` exemption below, a different question.
_LITELLM_GLOBAL_TRUTHY_FIELDS = (
    "model_fallbacks",
    "headers",
    "pre_call_rules",
    "post_call_rules",
    "drop_params",
)
# LiteLLM's ambient request MUTATOR — read on its own, not through the tuple above; see
# ``_ambient_modifier_is_enabled`` for why its blast radius is narrower.
_MODIFY_PARAMS_FIELD = "modify_params"


def litellm_env_flag_is_true(value: object) -> bool:
    """Whether LiteLLM would read ``value`` from the environment as boolean true.

    # INVARIANT: parity with the INSTALLED implementation, not with intuition.
    # ``get_secret_bool`` delegates to ``str_to_bool``, which recognizes only
    # ``"true"`` and ``"false"`` after ``.strip().lower()`` and answers ``None`` for
    # everything else — so ``"yes"``, ``"1"``, ``"on"`` and ``""`` are NOT true, and an
    # unset variable is not either. Guessing more generously here would fail OPEN: the
    # gateway would refuse a runtime LiteLLM never entered.
    # WHY total over ``object``: the caller passes ``os.environ.get(...)``, which is
    # ``None`` when unset. ``None`` must be an answer, never a crash on the cache path.
    # AIDEV-NOTE: this models the ENVIRONMENT branch only. When a secret-manager client
    # is configured LiteLLM resolves the value somewhere this process cannot see, which
    # is why that state is its own refusal in ``_has_unsafe_openai_runtime_state``
    # rather than something this helper pretends to model.
    """
    return isinstance(value, str) and value.strip().lower() == "true"


def _has_unsafe_openai_runtime_state(litellm: Any) -> bool:
    """The fail-closed verdict on ambient state — MODEL-FREE.

    # INVARIANT (OME-884): ONE core, TWO readers — ``participates_in_global_cache`` and
    # ``chat_completion``. The cache is a SECOND route to this provider's answers: a
    # stored row needs neither a registered model nor a credential to be replayed, and
    # the cache stage runs ahead of both checks, so a dispatch-only guard would keep
    # serving rows from a runtime it refuses to dispatch into. Sharing the predicate is
    # what makes these two verdicts incapable of drifting apart.
    # SCOPE (OME-884 cycle 2): the two readers share THIS core plus the alias check and
    # nothing more — it is no longer the whole of either decision.
    # ``litellm.modify_params`` is an owner-approved asymmetric exception handled outside
    # this function, its blast radius being narrower than "refuse both"; see
    # ``_ambient_modifier_is_enabled``. Do not fold it back in.
    # INVARIANT: fail CLOSED on a poisoned VALUE — every read is a defensive ``getattr``,
    # so a hostile ambient global costs a bypass, not a request.
    # AIDEV-NOTE: a MISSING global is different and this does NOT fail closed on it — a
    # renamed global reads ``None``, which is falsy, so the check passes and the hazard
    # goes unguarded silently. The defence is external:
    # ``test_every_guarded_global_still_exists_on_installed_litellm``. Add a read here, add
    # it there too.
    # AIDEV-NOTE: this function is NOT total on its own, and deliberately so. A global
    # that answers by RAISING — ``get_config()``, a hostile ``__bool__`` — still escapes
    # here; totality is enforced once, by its only caller
    # ``_has_unsafe_litellm_global_state``, which converts any such escape into the same
    # "unsafe" verdict. Do not add a second try/except here: two of them would let a
    # future reader believe either one alone is sufficient.
    # WHY each state disqualifies the runtime:
    #   OpenAIConfig            — its entries are merged into ``optional_params`` for
    #                             every OpenAI call, so an operator-set temperature
    #                             changes the answer while the key cannot see it.
    #   OPENAI_CUSTOM_HEADERS   — ambient headers ride along on the request.
    #   secret_manager_client   — an ambient resolver can supply the flag below and
    #                             other values from outside this process, so no
    #                             environment read is authoritative any more.
    #   experimental handler    — swaps the dispatch handler, and therefore the wire
    #                             behaviour this plugin's adapter revision pins.
    #   fallbacks/headers/proxy_auth/rules/callbacks (OME-864) — process-global routing
    #                             and observation that could redirect an account-scoped
    #                             credential or mutate the call.
    """
    if os.environ.get("OPENAI_CUSTOM_HEADERS"):
        return True
    if getattr(litellm, "secret_manager_client", None) is not None:
        return True
    if litellm_env_flag_is_true(os.environ.get(_EXPERIMENTAL_HANDLER_ENV)):
        return True
    if getattr(litellm, "proxy_auth", None) is not None:
        return True
    get_config = getattr(getattr(litellm, "OpenAIConfig", None), "get_config", None)
    if callable(get_config) and get_config():
        return True
    if any(bool(getattr(litellm, field, None)) for field in _LITELLM_GLOBAL_TRUTHY_FIELDS):
        return True
    return any(
        callbacks and any(callback != "cache" for callback in callbacks)
        for callbacks in (
            getattr(litellm, field, None) for field in _LITELLM_GLOBAL_CALLBACK_FIELDS
        )
    )


def _model_is_ambiently_aliased(litellm: Any, model: object) -> bool:
    """Whether a process-global LiteLLM alias REDIRECTS this exact requested model.

    # WHY this is per-model and not folded into the core above: an alias silently sends
    # one id somewhere else, so a row stored under the requested id would be replayed
    # while a miss dispatched something different — a wrong-hit class for THAT model and
    # no reason at all to abandon every other model's cache.
    # INVARIANT: EXACT key match only. An alias for a different model, or for another
    # provider entirely, must leave direct OpenAI fully working.
    """
    aliases = getattr(litellm, "model_alias_map", None)
    return isinstance(model, str) and isinstance(aliases, Mapping) and model in aliases


def _has_unsafe_litellm_global_state(litellm: Any, model: object) -> bool:
    """The verdict both readers share: the ambient core plus this request's own alias.

    # INVARIANT: TOTAL. An ambient read that RAISES counts as unsafe, exactly like one
    # that answers with a poisoned value. The reads below are all defensive about a
    # MISSING attribute, but a LiteLLM global can also answer BY raising —
    # ``OpenAIConfig.get_config()`` is a call, ``model in aliases`` runs a hostile
    # ``__contains__``, and ``bool(...)`` runs a hostile ``__bool__``. Before this guard
    # such a runtime escaped as an ordinary exception, and the two paths degraded
    # differently: the cache stage absorbed it into its own catch-all (reporting this
    # provider's projection bypass for something that was not a projection decision),
    # while dispatch surfaced a generic 502 ``provider_error`` — blaming OpenAI for a
    # runtime the GATEWAY could not certify.
    # WHY one try/except here rather than one per read: this function is the single
    # junction both ``participates_in_global_cache`` and ``chat_completion`` pass
    # through for the SHARED hazards, so guarding it makes both of those paths total at
    # once. Guarding each read would be eight places to forget.
    # AIDEV-NOTE: "single junction" covers the SHARED hazards only. Since cycle 2 each
    # reader also consults ``_ambient_modifier_is_enabled`` separately — the cache gate
    # always, dispatch only when ``max_tokens`` is present — and that helper carries its
    # own totality guard. Two callers, two questions.
    # WHY the verdict is UNSAFE and not merely "unknown": the gate certifies that the
    # process-global state cannot change the answer. A runtime it could not inspect has
    # not been certified, and a cache row may not be filled or replayed on the strength
    # of an inspection that did not complete.
    """
    try:
        return _model_is_ambiently_aliased(litellm, model) or _has_unsafe_openai_runtime_state(
            litellm
        )
    except Exception:
        # Deliberately broad, and deliberately not narrowed: the hazard is arbitrary
        # third-party code reached through ``getattr``, so the set of exception types is
        # open by construction. ``BaseException`` is NOT caught — a ``KeyboardInterrupt``
        # or ``SystemExit`` must still propagate.
        logger.warning("direct OpenAI ambient-state inspection failed; treating runtime as unsafe")
        return True


# The caller-facing 503 is deliberately sanitized, so these are the operator's only
# evidence — hence naming the variable and its truthiness trap explicitly.
# INVARIANT: DIAGNOSTIC, never a transcript — no model, message, profile, account or
# credential may appear in them.
_MODIFIER_FOOTGUN = (
    " LiteLLM reads LITELLM_MODIFY_PARAMS as bool(os.getenv(...)), so ANY non-empty value "
    "enables it, including the literal string false; unset the variable to restore."
)
_MODIFIER_CACHE_DECLINE = (
    "direct OpenAI declined global-cache participation: litellm.modify_params is enabled, "
    "so LiteLLM may replace max_tokens after the cache key is built." + _MODIFIER_FOOTGUN
)
_MODIFIER_DISPATCH_REFUSAL = (
    "direct OpenAI refused a request carrying max_tokens: litellm.modify_params is enabled "
    "and would send a ceiling the caller did not ask for." + _MODIFIER_FOOTGUN
)
_MODIFIER_UNREADABLE = (
    "litellm.modify_params could not be read; treating the ambient request mutator as "
    "ENABLED. Check that the installed LiteLLM still defines the module global."
)


def _ambient_modifier_is_enabled(litellm: Any) -> bool:
    """Whether LiteLLM will rewrite this request's ``max_tokens`` before dispatch.

    # WHY not in ``_LITELLM_GLOBAL_TRUTHY_FIELDS``: that tuple refuses dispatch too, and
    # LiteLLM 1.97.0 rewrites only a request that carries a ceiling (``litellm/utils.py``
    # requires ``kwargs.get("max_tokens") is not None``), so refusing one without would be
    # an outage this gateway invented. Blast radius must match the hazard.
    # INVARIANT: TOTAL and fail CLOSED. ``getattr`` takes NO default on purpose — a missing
    # attribute raises and counts as ENABLED, the opposite of the sibling reads, because
    # this flag's ABSENCE from the guard is the very defect being fixed.
    # AIDEV-NOTE: the MODULE GLOBAL is the authority, never ``os.environ`` — LiteLLM
    # snapshots the variable at import.
    """
    try:
        return bool(getattr(litellm, _MODIFY_PARAMS_FIELD))
    except Exception:
        # Deliberately broad and deliberately not ``BaseException`` — same reasoning as
        # the shared junction above: the hazard is third-party code behind ``getattr``,
        # while ``KeyboardInterrupt``/``SystemExit`` must still propagate.
        logger.warning(_MODIFIER_UNREADABLE)
        return True


def has_unsafe_litellm_global_state(litellm: Any, model: object) -> bool:
    """The SHARED verdict: refuse both the cache and the dispatch."""
    return _has_unsafe_litellm_global_state(litellm, model)


def certifies_global_cache_participation(litellm: Any, model: object) -> bool:
    """Whether a global-cache row may be read or filled for ``model`` right now.

    # INVARIANT: this is the COARSE half of the modifier asymmetry. It is handed only the
    # requested model — never the body — so it cannot see whether this particular request
    # carries the ``max_tokens`` an enabled modifier would rewrite, and therefore declines
    # for the whole provider while the flag is on. That errs SAFE by construction:
    # participation ends up strictly stricter than dispatch, so no state exists in which a
    # stored row answers a request dispatch would have refused.
    """
    if _ambient_modifier_is_enabled(litellm):
        # Per DECISION, not once per process: the operator needs the reason attached to the
        # traffic that lost its cache, and this runtime is misconfigured, not busy.
        logger.warning(_MODIFIER_CACHE_DECLINE)
        return False
    return not _has_unsafe_litellm_global_state(litellm, model)


def modifier_refuses_dispatch(litellm: Any, max_tokens: object) -> bool:
    """Whether an enabled ambient modifier must refuse THIS live dispatch.

    # INVARIANT: the PRECISE half of the asymmetry. Installed LiteLLM rewrites only a
    # request whose ``max_tokens`` is not ``None``, so a request without a ceiling is
    # untouched and refusing it would be an outage this gateway invented. A
    # profile-defaulted ceiling counts as present, because defaults are merged into the
    # body before the cache stage; an explicit ``None`` counts as absent, matching
    # LiteLLM's own test.
    # WHY ``max_tokens`` is tested FIRST: a request LiteLLM cannot touch then never reads
    # the flag at all, so it produces neither a refusal nor log noise.
    """
    if max_tokens is None or not _ambient_modifier_is_enabled(litellm):
        return False
    logger.warning(_MODIFIER_DISPATCH_REFUSAL)
    return True
