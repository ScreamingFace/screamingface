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

# WHY a separate list rather than more entries in _OPEN_PROVIDER_MARKERS: these are the
# vendors that ship BOTH. Every marker here names a model family whose OWNER is on the closed
# list, so it must be consulted before the owner rule or the owner wins and an open-weights
# model is published as closed. That is the OME-1145 defect, and on the live draco-3pass board
# `moonshotai`/`kimi` alone is the difference between 0% and 29%.
#
# INVARIANT (OME-1179 Q1): membership here means "weights are downloadable and locally
# runnable", NOT "permissively licensed". Gemma carries use restrictions and gpt-oss a usage
# policy; both are still open under the chosen definition, because the board's claim is
# reproducibility — can someone else run this and get your number.
_OPEN_MODEL_MARKERS: tuple[str, ...] = (
    "gpt-oss",
    "gemma",
    "moonshotai",
    "kimi",
)

# WHY: a routing prefix says who carried the request, not what ran. Every live draco-3pass
# route is `openrouter/`-prefixed and `openrouter` is a closed PROVIDER marker, so without
# stripping this every model on the board classifies closed however open its weights are.
_ROUTING_PREFIXES: tuple[str, ...] = ("openrouter",)

# INVARIANT: ORDER IS THE RULE. `classify_model` returns on the first match, so the specific
# model markers must sit above the owner markers — `gpt-oss` before `openai`, `gemma` before
# `google`. Reordering these three entries silently reintroduces OME-1145. Expressed as data
# rather than an if-chain so the precedence is visible in one place and testable.
_MODEL_RULES: tuple[tuple[tuple[str, ...], ModelOpenness], ...] = (
    (_OPEN_MODEL_MARKERS, "open"),
    (_OPEN_PROVIDER_MARKERS, "open"),
    (_CLOSED_PROVIDER_MARKERS, "closed"),
)


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


def _strip_routing_prefix(route: str) -> str:
    head, separator, tail = route.partition("/")
    if separator and head.lower() in _ROUTING_PREFIXES:
        return tail
    return route


def classify_model(route: str) -> ModelOpenness:
    """Openness of ONE declared model route (OME-1181).

    Distinct from `classify_providers`, which returns one verdict for a whole submission from
    its provider prefixes. OME-1179 D1 keeps that any-closed-wins aggregation; this only
    changes what gets fed to it.

    INVARIANT: `unknown` is a THIRD value, not a synonym for `closed`. Both close an entry
    under D1, but D4 requires the count of unrecognised models to be reportable, which is
    impossible once the two collapse into one verdict.

    WHY this resolution order: a specific model rule must beat its owner rule. `gpt-oss` is
    OpenAI's and `gemma` is Google's, so checking `_CLOSED_PROVIDER_MARKERS` first would file
    both as closed on the owner's name while their weights are downloadable.
    """
    identity = _strip_routing_prefix(route)
    for markers, verdict in _MODEL_RULES:
        if _matches_any(identity, markers):
            return verdict
    _log_unrecognized("model route", route)
    return "unknown"


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
