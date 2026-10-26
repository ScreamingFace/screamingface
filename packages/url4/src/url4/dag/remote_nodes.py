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

from collections.abc import Awaitable
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
    raise ResolutionError(
        f"remote-node calls are not supported in v1 (url4://{authority}{path})",
        code=ErrorCode.REMOTE_NODE_UNSUPPORTED,
        permanent=True,
    )


__all__ = ["allow_one_remote_hop", "check_remote_node", "refuse_remote_nodes"]
