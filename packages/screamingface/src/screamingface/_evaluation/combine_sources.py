"""The combine context's sources: the model calls each member made (OME-1289 gap, erd §6, SG-D4).

FEATURE: an accounting signal (cost_usd, latency_ms, tokens_in, tokens_out) sums the member's own
model calls; the Engine finds each recorded call by its (path, params) fingerprint.
INVARIANT: canonical_params is the Engine's combine/spec.py canonical_params, expression for
expression (tests/unit/test_canonical_params_conformance.py binds the copy).
INVARIANT (I-C2, F3): claimants are counted over the WHOLE compiled expression; a member with any
call claimed twice or more gets {} (every accounting signal None), never a partial sum.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import quote

type CallFingerprint = tuple[str, tuple[tuple[str, str], ...]]


@dataclass(frozen=True, slots=True)
class _SourceCall:
    """One model call a member made: the Engine records it as (request.path, sorted params)."""

    binding: str  # model_N | synthesis_N
    path: str  # the RelExpr path: "/" + canonical route
    params: tuple[tuple[str, str], ...]  # resolved_params, author order

    @property
    def fingerprint(self) -> CallFingerprint:
        return (self.path, tuple(sorted(self.params)))


def canonical_params(pairs: Iterable[tuple[str, str]]) -> str:
    return "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(pairs))


def member_sources(
    members: Sequence[Sequence[_SourceCall]], claims: Mapping[CallFingerprint, int]
) -> dict[str, dict[str, dict[str, str]]]:
    """{member_k: {binding: {"path", "params"}}}; {} when any call's claims.get(fp, 1) != 1."""

    return {
        f"member_{index}": _member_calls(calls, claims) for index, calls in enumerate(members, 1)
    }


def _member_calls(
    calls: Sequence[_SourceCall], claims: Mapping[CallFingerprint, int]
) -> dict[str, dict[str, str]]:
    # WHY {} and not the unclaimed calls: a partial sum would pass as the member's total (F3).
    if any(claims.get(call.fingerprint, 1) != 1 for call in calls):
        return {}
    return {
        call.binding: {"path": call.path, "params": canonical_params(call.params)} for call in calls
    }


__all__: list[str] = []
