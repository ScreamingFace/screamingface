"""The token log-probability numbers of one chat-completions reply (E4b part 3, logprob-capture).

FEATURE: a member call that asks for `logprobs` (and maybe `top_logprobs`) carries, on its terminal
reply, the numbers a combine step reads: the token count, the exact sum of the token
log-probabilities, and the mean token entropy.
STORY: as a researcher, I weight or pick members by how sure each model was of its own answer.
INVARIANT: no token string and no `bytes` array leaves this module; only four numbers do (LC-D1,
OME-990). Nothing here logs.
INVARIANT: pure, and never raises on any decoded JSON value: the reply is untrusted gateway input
(C3). A bad shape gives None for the numbers it touches.
INVARIANT: the token values and the top lists are checked apart (LC-D2): a bad or positive token
value makes `logprob_sum` None; a bad top entry makes only `entropy_mean` None.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from screamingface_engine.combine.ports import finite_float
from screamingface_engine.operation_accounting import ReplyLogprobs


def reply_logprobs(data: Mapping[str, Any], top_k: int | None) -> ReplyLogprobs | None:
    """The numbers of ``choices[0].logprobs.content``, or None when the reply has no such list.

    ``top_k`` is the ``top_logprobs`` the call asked for; None means it asked for none, and then the
    entropy is None. A missing, null, non-list or empty ``content`` gives None (LC-E3).
    """
    content = _content_entries(data)
    if content is None:
        return None
    return ReplyLogprobs(
        tokens=len(content),
        logprob_sum=_logprob_sum(content),
        top_k=top_k,
        entropy_mean=None if top_k is None else _entropy_mean(content, top_k),
    )


def _content_entries(data: Mapping[str, Any]) -> list[Any] | None:
    choices = data.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    block = first.get("logprobs") if isinstance(first, Mapping) else None
    content = block.get("content") if isinstance(block, Mapping) else None
    return content if isinstance(content, list) and content else None


def _log_probability(value: object) -> float | None:
    """A finite number <= 0, as a float, else None. A log-probability is never positive.

    A bool is not a number here, and an integer too large for a float is None (``finite_float``).
    """
    number = finite_float(value)
    return number if number is not None and number <= 0.0 else None


def _logprob_sum(content: Sequence[Any]) -> float | None:
    """``math.fsum`` of every token value (exact, so the order never changes it), or None."""
    values: list[float] = []
    for entry in content:
        value = _log_probability(entry.get("logprob")) if isinstance(entry, Mapping) else None
        if value is None:
            return None
        values.append(value)
    try:
        total = math.fsum(values)
    except OverflowError:
        return None
    return total if math.isfinite(total) else None


def _entropy_mean(content: Sequence[Any], top_k: int) -> float | None:
    """The mean position entropy over the positions with at least one top entry (entropy PRD §3).

    Only the first ``top_k`` entries of a position count (LC-D8). A missing or null
    ``top_logprobs``, or an empty list, skips the position (EN-D2). A non-list, or one entry that is
    not an object with a finite ``logprob`` <= 0, makes the whole value None (LC-D2, EN-D7).
    """
    entropies: list[float] = []
    for entry in content:
        if not isinstance(entry, Mapping):
            return None
        tops = entry.get("top_logprobs")
        if tops is None:
            continue
        listed = _top_values(tops, top_k)
        if listed is None:
            return None
        if listed:
            entropies.append(_position_entropy(listed))
    return math.fsum(entropies) / len(entropies) if entropies else None


def _top_values(tops: object, top_k: int) -> list[float] | None:
    """The first ``top_k`` log-probabilities of one position, or None when the list is bad."""
    if not isinstance(tops, list):
        return None
    values: list[float] = []
    for top in tops[:top_k]:
        value = _log_probability(top.get("logprob")) if isinstance(top, Mapping) else None
        if value is None:
            return None
        values.append(value)
    return values


def _position_entropy(logprobs: Sequence[float]) -> float:
    """``H = -sum p ln p - r ln r`` in nats, ``p = exp(l)``, ``r = max(0, 1 - sum p)``,
    ``0 ln 0 = 0``.

    WHY ``-sum p * l``: ``ln p`` is the log-probability itself, so no ``log`` of a rounded ``p``.
    WHY the residual ``r``: the mass the provider did not list counts as one more outcome (P8).
    WHY ``max(0.0, ...)``: rounding can never give a negative entropy or a ``-0.0``.
    """
    probabilities = [math.exp(value) for value in logprobs]
    listed = -math.fsum(p * value for p, value in zip(probabilities, logprobs, strict=True))
    residual = max(0.0, 1.0 - math.fsum(probabilities))
    residual_term = residual * math.log(residual) if residual > 0.0 else 0.0
    return max(0.0, listed - residual_term)


__all__ = ["reply_logprobs"]
