"""The idempotency key a retrying guard offers to the I/O adapters (part of the io port).

A guarded source with ``;retry=N`` may send its request more than once, and a request
can apply its effect even when its response is lost. The protocol does not deduplicate
(spec §15.1; ``rid`` is fresh per child request, §11.6.3), so the engine offers the
remote a key: adapters that can carry it send it — the HTTP adapter as the
``Idempotency-Key`` header (IETF httpapi draft). Deduplicating on it is the remote's
choice; without it, guarded effects must still be idempotent. (url4's own server does
not deduplicate on it yet, so a url4→url4 hop is not protected.)

The rule is "reuse until answered". Each target has its own key inside one guarded
resolve. A retry re-sends a target with the SAME key while no reply came back for it
(timeout, network error, a lost response): the remote may have applied it, so it may
deduplicate. Once the adapter received ANY response for the target (success or error
status), it calls :func:`mark_answered`, and the next request to that target gets a
FRESH key: the earlier exchange is complete, so a new request is a new request — this
keeps resampling a malformed reply possible.

The scope travels as a context variable, not as a port argument, so every fetch inside
the guarded subtree (``fetch``, ``fetch_ex``, nested calls) sees it and adapters that
predate it keep working unchanged. Standard library only.
"""

from __future__ import annotations

import secrets
from contextvars import ContextVar
from hashlib import sha256


class IdempotencyScope:
    """The key state of one guarded resolve: a secret, and a generation per target.

    A key is ``sha256(secret, generation, target)``: stable while the target's
    generation is unchanged, and unlinkable across targets and hosts (nothing in it
    repeats from one key to another).
    """

    __slots__ = ("_generations", "_secret")

    def __init__(self) -> None:
        self._secret = secrets.token_hex(16)
        self._generations: dict[str, int] = {}

    def key_for(self, target: str) -> str:
        generation = self._generations.get(target, 0)
        return sha256(f"{self._secret}\0{generation}\0{target}".encode()).hexdigest()

    def answered(self, target: str) -> None:
        self._generations[target] = self._generations.get(target, 0) + 1


IDEMPOTENCY_SCOPE: ContextVar[IdempotencyScope | None] = ContextVar(
    "url4_idempotency_scope", default=None
)
"""The current guarded resolve's key state, or ``None`` outside a retrying guard.

Set by :class:`~url4.dag.nodes.GuardNode` (only when ``retries > 0``). A nested guard
keeps the outer scope, so an outer retry re-sends the inner requests with the same keys.
"""


def idempotency_key(target: str) -> str | None:
    """The ``Idempotency-Key`` for ``target`` now, or ``None`` outside a retrying guard."""
    scope = IDEMPOTENCY_SCOPE.get()
    return None if scope is None else scope.key_for(target)


def mark_answered(target: str) -> None:
    """An adapter received a response for ``target``: its next request gets a new key."""
    scope = IDEMPOTENCY_SCOPE.get()
    if scope is not None:
        scope.answered(target)


__all__ = ["IDEMPOTENCY_SCOPE", "IdempotencyScope", "idempotency_key", "mark_answered"]
