"""Which worker runs a driver-started run's topic (E5 P2 spec D7, R3).

FEATURE: a detached Run (OME-1837). The driver sends a start again whenever it cannot tell
whether the first one landed (D6), so two workers can take two copies of one start, minutes
apart. Before it runs an `exclusive` start, a worker claims the topic here; exactly one claim
succeeds, and every other copy is acked away.

LAYERING: a shared leaf, standard library only. The worker imports it; the adapter is
`adapters/topic_claims_jetstream.py`, and the in-memory one is in `adapters/memory.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Claim:
    """A topic's claim as the bucket holds it.

    ``revision`` is the entry's own, which a takeover names so that only one of two contenders
    wins. ``finished`` means the holder's run has published its terminal frame.
    """

    holder: str
    revision: int
    finished: bool = False


class TopicClaimsUnavailable(RuntimeError):
    """The bucket could not be read or written. INVARIANT (R3): the worker then runs its copy,
    as it does today when it cannot tell, so this never ends a run."""


class TopicClaims(Protocol):
    """INVARIANT: a broker error is raised as `TopicClaimsUnavailable`. A broker that cannot be
    reached at all may instead never answer, so the worker bounds every call by
    `topic_claim_budget_s` (R3)."""

    async def ensure_bucket(self, *, update: bool = False) -> None:
        """Create the bucket if it is missing, and check an existing one. ``update=True`` is for
        the runner pool at startup, which owns the bucket's settings and applies a changed one."""
        ...

    async def claim(self, topic: str, worker_id: str) -> Claim:
        """Claim ``topic`` for ``worker_id`` if nobody has, and return the claim as it now
        stands: this worker's new one, or the one already there, which may also be its own."""
        ...

    async def take_over(self, topic: str, worker_id: str, revision: int) -> Claim | None:
        """Make ``worker_id`` the holder if the claim is still at ``revision``. None when another
        write came first; the caller reads the claim again."""
        ...

    async def finish(self, topic: str, worker_id: str) -> None:
        """Mark ``worker_id``'s claim finished. A claim another worker has taken over, or one
        that has expired, is left as it is."""
        ...

    async def close(self) -> None: ...


def encode_claim(holder: str, *, finished: bool) -> bytes:
    return json.dumps({"holder": holder, "finished": finished}, separators=(",", ":")).encode()


def decode_claim(value: bytes, revision: int) -> Claim:
    """A claim from its stored value. `TopicClaimsUnavailable` for one this code did not write:
    the worker runs its copy rather than trust it."""
    try:
        data = json.loads(value)
        holder, finished = data["holder"], data["finished"]
    except (ValueError, TypeError, KeyError) as exc:
        raise TopicClaimsUnavailable(f"unreadable claim at revision {revision}") from exc
    if not isinstance(holder, str) or not isinstance(finished, bool):
        raise TopicClaimsUnavailable(f"unreadable claim at revision {revision}")
    return Claim(holder, revision, finished)


__all__ = [
    "Claim",
    "TopicClaims",
    "TopicClaimsUnavailable",
    "decode_claim",
    "encode_claim",
]
