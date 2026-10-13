"""Spec builders for the signal reducer tests (OME-1289 E4a gap-closure, unit 10E).

Test-only. Each builder returns a spec over the built-in operators, shaped like what the SDK writes
for argmax (``pick``), rank by a signal and filter. ``sources`` and ``costs`` give an accounting
signal its context ``sources`` and an injected ``AccountingReader``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from combine_support import vote_spec

from screamingface_engine.combine.ports import AccountingReader, MemberSources, SignalOrder


def argmax_spec(member_count: int, key: str, order: SignalOrder) -> dict[str, Any]:
    """A pick over one signal: the member with the highest (max) or lowest (min) number wins."""
    return vote_spec(
        member_count,
        reducer="pick",
        extract=None,
        normalize=None,
        reduce={"op": "by_signal@1", "args": {"key": key, "order": order}},
        select={"op": "best_holder@1", "args": {"order": order}},
    )


def rank_signal_spec(member_count: int, k: int, key: str, order: SignalOrder) -> dict[str, Any]:
    """A rank over one signal: the top ``k`` members by that number."""
    return vote_spec(
        member_count,
        reducer="rank",
        extract=None,
        normalize=None,
        reduce={"op": "by_signal@1", "args": {"key": key, "order": order}},
        select={"op": "top_k@1", "args": {"k": k, "order": order}},
    )


def filter_spec(
    member_count: int, args: Mapping[str, Any], extract: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """A filter: ``filter@1`` marks each voter, ``kept@1`` hands on the members that passed."""
    return vote_spec(
        member_count,
        reducer="filter",
        extract=None if extract is None else dict(extract),
        normalize=None,
        reduce={"op": "filter@1", "args": dict(args)},
        select={"op": "kept@1", "args": {}},
    )


def sources(member_count: int) -> dict[str, Any]:
    """The context ``sources`` of ``member_count`` members: one call each, no params."""
    return {
        f"member_{k}": {f"model_{k}": {"path": f"/p/{k}", "params": ""}}
        for k in range(1, member_count + 1)
    }


def costs(*values: float | None) -> AccountingReader:
    """An ``AccountingReader`` that answers ``cost_usd`` for member_1.. in order."""

    def reader(known: MemberSources, /) -> Mapping[str, Mapping[str, float | None]]:
        return {f"member_{k}": {"cost_usd": value} for k, value in enumerate(values, start=1)}

    return reader


__all__ = ["argmax_spec", "costs", "filter_spec", "rank_signal_spec", "sources"]
