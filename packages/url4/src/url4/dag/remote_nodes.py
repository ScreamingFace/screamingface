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
INVARIANT (OME-1811 review): a refusal is never data. A row policy (``on_error=collect|skip``) or
a guard may catch the error, but the policy records every refusal and ``url4.dag.run`` re-raises
one its own graph swallowed (:func:`reraise_refusals_since`), so the run fails, not completes.
AIDEV-NOTE: only :func:`refuse_remote_nodes` is exported (``url4.dag``, OME-1811), for a host that
runs ``url4.dag.run`` itself as a node (the engine), so its runs refuse as ``Url4Node.evaluate``
does. It can only tighten. Allowing a remote node is still no user option: ``allow_one_remote_hop``
and ``check_remote_node`` stay private until a node-to-node authentication spec exists.
"""

from __future__ import annotations

from collections.abc import Awaitable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass, field

from url4.core.errors import ErrorCode, ResolutionError


@dataclass
class _Policy:
    hop: tuple[str, str] | None  # the (authority, path) a client may call, once; None = none
    used: bool = False
    refusals: list[ResolutionError] = field(default_factory=list)  # every refusal, even caught


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


def remote_policy_active() -> bool:
    """Whether this evaluation runs under a remote-node policy (a node context)."""
    return _POLICY.get() is not None


def refusal_mark() -> int:
    """How many refusals this evaluation has raised so far (a run's starting mark)."""
    policy = _POLICY.get()
    return 0 if policy is None else len(policy.refusals)


def reraise_refusals_since(mark: int) -> None:
    """Raise the first refusal raised after ``mark`` that something caught instead of failing."""
    policy = _POLICY.get()
    if policy is not None and len(policy.refusals) > mark:
        raise policy.refusals[mark]


def reraise_remote_refusal(outcomes: Iterable[object]) -> None:
    """Raise the first refusal THIS policy raised among gathered row outcomes (never a row).

    WHY identity, not the error code: a row whose peer answered ``x.remote_node_unsupported`` is
    that peer's error, and stays an error row; only this evaluation's own refusal is unswallowable.
    """
    policy = _POLICY.get()
    refused = [] if policy is None else policy.refusals
    for outcome in outcomes:
        for refusal in refused:
            if outcome is refusal:
                raise refusal


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
    raise _refuse(policy, authority, path)


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
        raise _refuse(policy, authority, path)
    for authority, path in maybe:
        if policy.used or policy.hop != (authority, path):
            raise _refuse(policy, authority, path)


def _refuse(policy: _Policy, authority: str, path: str) -> ResolutionError:
    refusal = ResolutionError(
        f"remote-node calls are not supported in v1 (url4://{authority}{path})",
        code=ErrorCode.REMOTE_NODE_UNSUPPORTED,
        permanent=True,
    )
    policy.refusals.append(refusal)
    return refusal


__all__ = [
    "allow_one_remote_hop",
    "check_remote_node",
    "precheck_remote_nodes",
    "refusal_mark",
    "refuse_remote_nodes",
    "remote_policy_active",
    "reraise_refusals_since",
    "reraise_remote_refusal",
]
