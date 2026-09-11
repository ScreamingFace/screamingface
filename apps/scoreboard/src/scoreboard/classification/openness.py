"""Open vs. closed classification for scores and baselines (OME-323, spec §4/§9).

A public "how much of the frontier is open" claim must not default-credit the open
side for anything it can't actually verify — every classification here fails closed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from scoreboard.scores.schemas import BaselineSchema, ScoreSchema

Openness = Literal["open", "closed"]

logger = logging.getLogger(__name__)

# WHY substring match, not exact match: real provider/model identifiers carry
# version and org-path noise (e.g. "meta-llama/Llama-3.1-70B-Instruct",
# "gpt-5.2-thinking") that an exact-match registry would need to enumerate
# combinatorially. A curated marker list is the same tradeoff Option A's original
# framing accepted (spec §4) — it drifts as new models ship, which is exactly why
# every miss below is logged rather than silently absorbed.
_CLOSED_PROVIDER_MARKERS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "google",
    "gemini",
    "openrouter",
)
_OPEN_PROVIDER_MARKERS: tuple[str, ...] = (
    "huggingface",
    "meta-llama",
    "llama",
    "mistral",
    "qwen",
    "deepseek",
)

_CLOSED_BASELINE_MARKERS: tuple[str, ...] = ("gpt-", "claude-", "gemini-")
_OPEN_BASELINE_MARKERS: tuple[str, ...] = ("llama", "mistral", "qwen", "deepseek")

# FEATURE: OME-1181 — per-model classification, for `classify_model` only. The lists above
# describe PROVIDERS and keep serving `classify_providers` unchanged.
ModelOpenness = Literal["open", "closed", "unknown"]

# INVARIANT: model routes are CLIENT-SUBMITTED, so this is an adversarial surface and the rules
# below are STRUCTURAL, never substring. An earlier version matched any open marker anywhere in
# the route, which let a submitter name a proprietary model `not-gemma-proprietary` and be
# published as open — the fail-closed contract inverted by choosing a string (review of PR #922).
#
# A route is `owner/model`. The OWNER segment decides, matched exactly.
_OPEN_OWNERS: frozenset[str] = frozenset(
    {
        "meta-llama",
        "mistralai",
        "qwen",
        "deepseek",
        "moonshotai",
        "huggingface",
        # A locally-run model is the definition of downloadable-and-runnable under Q1.
        "ollama",
    }
)
# INVARIANT: every `custom_llm_provider` the Gateway registers belongs in one of these two sets,
# or an ordinary supported provider reports as a registry gap. `unknown` and `closed` both close
# an entry under OME-1179 D1, so a miss here changes no percentage — it corrupts D4's staleness
# count, which is only meaningful if it means "models the registry has not been taught about".
#
# Verified against `apps/aigateway/src/aigateway/plugins/*_provider/plugin.py`: the registered
# ids are openai, anthropic, gemini-cli, codex, antigravity, huggingface, ollama, openrouter.
# `gemini-cli`, `codex` and `antigravity` were missing (review of PR #922).
#
# AIDEV-NOTE: an owner segment is a Gateway provider id on a direct route, and a model owner on
# an OpenRouter-carried one (`openrouter/google/...`), so both kinds live here. Entries are only
# added once observed in one of those two places — an earlier version carried `cohere` and `xai`,
# neither registered by the Gateway nor OpenRouter's actual namespace, which is `x-ai`.
_CLOSED_OWNERS: frozenset[str] = frozenset(
    {
        # Gateway provider ids
        "openai",
        "anthropic",
        "gemini-cli",
        "codex",
        "antigravity",
        # Model owners as they appear on OpenRouter routes
        "google",
        "gemini",
    }
)

# The vendors that ship BOTH. A family exception is SCOPED TO ITS OWNER and matched as a prefix
# of the model segment, so `google/gemma-*` is open while `openai/gemma-anything` is not —
# Google ships Gemma's weights, OpenAI does not.
#
# INVARIANT (OME-1179 Q1): membership means "weights are downloadable and locally runnable", NOT
# "permissively licensed". Gemma carries use restrictions and gpt-oss a usage policy; both are
# still open under the chosen definition, because the board's claim is reproducibility.
_OPEN_FAMILIES_BY_OWNER: dict[str, tuple[str, ...]] = {
    "openai": ("gpt-oss",),
    "google": ("gemma",),
}

# WHY: a routing prefix says who carried the request, not what ran. Every live draco-3pass
# route is `openrouter/`-prefixed, so without stripping this the owner segment would always
# read `openrouter` and no model could ever be classified at all.
_ROUTING_PREFIXES: frozenset[str] = frozenset({"openrouter"})


def _matches_any(name: str, markers: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in markers)


def _log_unrecognized(kind: str, name: str) -> None:
    # WHY a log, not silence: the fail-closed default (below) is permanent and
    # correct, but staying silent about it isn't — every miss is a model the
    # registry doesn't know about yet, quietly understating "open" until someone
    # updates the list (spec §4's staleness resolution, 2026-08-06).
    logger.warning("unrecognized %s for openness classification: %r", kind, name)


def classify_providers(providers: Sequence[str]) -> Openness:
    """Closed if ANY provider is closed; open only if every provider is open
    (spec §4's mixed-provider fusion rule). An empty list is closed — there is
    nothing here to credit as open.
    """
    if not providers:
        _log_unrecognized("provider", "<empty ran_with_providers>")
        return "closed"

    saw_closed = False
    for provider in providers:
        if _matches_any(provider, _CLOSED_PROVIDER_MARKERS):
            saw_closed = True
        elif _matches_any(provider, _OPEN_PROVIDER_MARKERS):
            continue
        else:
            _log_unrecognized("provider", provider)
            saw_closed = True
    return "closed" if saw_closed else "open"


def _split_route(route: str) -> tuple[str, str] | None:
    """`owner/model` for a route, after dropping any routing prefix. None if it has no owner.

    A bare `claude-opus-4.8` carries no owner to reason about, and guessing from the string is
    exactly the hole this parsing closes, so the caller fails closed on None.
    """
    segments = [segment for segment in route.lower().split("/") if segment]
    if segments and segments[0] in _ROUTING_PREFIXES:
        segments = segments[1:]
    if len(segments) < 2:
        return None
    return segments[0], "/".join(segments[1:])


def classify_model(route: str) -> ModelOpenness:
    """Openness of ONE declared model route (OME-1181).

    Distinct from `classify_providers`, which returns one verdict for a whole submission from
    its provider prefixes. OME-1179 D1 keeps that any-closed-wins aggregation; this only
    changes what gets fed to it.

    INVARIANT: STRUCTURAL, never substring. Routes are client-submitted, so any rule that reads
    the whole string lets a submitter buy a verdict by naming their model after an open family
    — `openai/not-gemma-proprietary` classified open under the first version of this function
    (review of PR #922). The owner segment decides, matched exactly; a family exception must
    belong to that owner.

    INVARIANT: `unknown` is a THIRD value, not a synonym for `closed`. Both close an entry
    under D1, but D4 requires the count of unrecognised models to be reportable, which is
    impossible once the two collapse into one verdict.
    """
    verdict = _owner_verdict(_split_route(route))
    if verdict == "unknown":
        _log_unrecognized("model route", route)
    return verdict


def _owner_verdict(parsed: tuple[str, str] | None) -> ModelOpenness:
    """The rules themselves, so `classify_model` stays one decision and one log.

    INVARIANT: the family exception is consulted FIRST and is scoped to its owner. Reversing
    these two lines files `openai/gpt-oss-120b` as closed on its owner's name; widening the
    family check beyond `_OPEN_FAMILIES_BY_OWNER[owner]` re-opens the crafted-name hole.
    """
    if parsed is None:
        return "unknown"
    owner, model = parsed
    families = _OPEN_FAMILIES_BY_OWNER.get(owner, ())
    if any(model.startswith(family) for family in families) or owner in _OPEN_OWNERS:
        return "open"
    return "closed" if owner in _CLOSED_OWNERS else "unknown"


def classify_baseline_name(model_name: str) -> Openness:
    """Same fail-closed pattern as `classify_providers`, via substring match
    against a baseline's free-text `model_name`.
    """
    if _matches_any(model_name, _CLOSED_BASELINE_MARKERS):
        return "closed"
    if _matches_any(model_name, _OPEN_BASELINE_MARKERS):
        return "open"
    _log_unrecognized("baseline model", model_name)
    return "closed"


def classify_score(score: ScoreSchema) -> Openness:
    """The registry-and-override-aware classifier `frontier.py` actually calls.
    `openness_override` (spec §9), when set, wins outright — the registry is never
    even consulted.
    """
    if score.openness_override is not None:
        return score.openness_override
    return classify_providers(score.ran_with_providers)


def classify_baseline(baseline: BaselineSchema) -> Openness:
    """Baseline counterpart of `classify_score`."""
    if baseline.openness_override is not None:
        return baseline.openness_override
    return classify_baseline_name(baseline.model_name)
