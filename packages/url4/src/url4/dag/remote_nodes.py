"""Whether an evaluation may call another url4 node (#1450 spec F1b, conformance case C6).

FEATURE: file inputs for url4 (epic ``OME-1529``, unit ``OME-1539``); the remote-node half of F1b.
STORY: as a node operator, an expression my node evaluates can never make my node call another
node, because nothing yet authenticates my node to it.

INVARIANT (owner decisions, Sergey 2026-10-26): in a node context every remote expression
(``RemoteFetchNode``) fails ``x.remote_node_unsupported``, permanent, BEFORE any I/O. A node
context is every evaluation a ``Url4Node`` runs (:func:`refuse_remote_nodes`) and a
``Client(node=...)`` evaluation, where only the one outer hop the client built itself may pass,
once (:func:`allow_one_remote_hop`). Without a policy (bare ``url4.run()``) nothing changes.

WHY a ContextVar: the policy belongs to one evaluation, not to the shared node or to the grammar;
every task the run spawns copies the context, and the one :class:`_Policy` object is shared by
reference, so a used hop stays used across the whole run.
AIDEV-NOTE: deliberately not exported from ``url4`` / ``url4.dag``: it is no user option. It is
lifted when a node-to-node authentication spec exists.
"""

from __future__ import annotations

from collections.abc import Awaitable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass

from url4.core.errors import ErrorCode, ResolutionError


@dataclass
class _Policy:
    hop: tuple[str, str] | None  # the (authority, path) a client may call, once; None = none
    used: bool = False


_POLICY: ContextVar[_Policy | None] = ContextVar("url4_remote_nodes", default=None)


async def refuse_remote_nodes[T](evaluation: Awaitable[T]) -> T:
    """Await ``evaluation`` with every remote-node call refused (a node evaluating a request)."""
    return await _under(_Policy(None), evaluation)


async def allow_one_remote_hop[T](evaluation: Awaitable[T], hop: tuple[str, str]) -> T:
    """Await ``evaluation`` allowing exactly one call to ``hop`` = ``(authority, path)``."""
    return await _under(_Policy(hop), evaluation)


async def _under[T](policy: _Policy, evaluation: Awaitable[T]) -> T:
    token = _POLICY.set(policy)
    try:
        return await evaluation
    finally:
        _POLICY.reset(token)


def check_remote_node(authority: str, path: str) -> None:
    """Raise ``x.remote_node_unsupported`` unless this evaluation may call ``authority`` now."""
    policy = _POLICY.get()
    if policy is None:
        return
    if not policy.used and policy.hop == (authority, path):
        # WHY single-use: a second call to the same node (say, from an intent the client
        # lowered itself) is a call the client did not build; it fails closed.
        policy.used = True
        return
    raise _refused(authority, path)


def precheck_remote_nodes(
    calls: Iterable[tuple[str, str]], *, maybe: Iterable[tuple[str, str]] = ()
) -> None:
    """Refuse, before any I/O, every ``(authority, path)`` call this evaluation could not make.

    FEATURE: PR #1587 review finding 4 (owner 2026-11-04) — the run-start attachment phase must
    not fetch anything for a run C6 refuses. INVARIANT: read-only — the client's one hop is
    checked, never spent (the real call spends it, :func:`check_remote_node`); a SECOND call to
    that hop is refused here, as the real second call would be.
    ``maybe`` holds calls the run makes only on some paths (its reduce processor: only on a
    reduce). Each is refused unless it IS the still-unspent hop, but never charged against it.
    WHY (CI on a74e15832, ``examples/url4_client.ipynb``): a ``Client(node=...)`` io whose first
    declared route is the hop makes that hop the run's implicit processor; charging it as a
    second call refused a passthrough run that never reduces. A reduce that does reach it after
    the hop is spent is still refused by :func:`check_remote_node`, before its I/O.
    """
    policy = _POLICY.get()
    if policy is None:
        return
    hop_free = not policy.used
    for authority, path in calls:
        if hop_free and policy.hop == (authority, path):
            hop_free = False
            continue
        raise _refused(authority, path)
    for authority, path in maybe:
        if policy.used or policy.hop != (authority, path):
            raise _refused(authority, path)


def _refused(authority: str, path: str) -> ResolutionError:
    return ResolutionError(
        f"remote-node calls are not supported in v1 (url4://{authority}{path})",
        code=ErrorCode.REMOTE_NODE_UNSUPPORTED,
        permanent=True,
    )


__all__ = [
    "allow_one_remote_hop",
    "check_remote_node",
    "precheck_remote_nodes",
    "refuse_remote_nodes",
]
