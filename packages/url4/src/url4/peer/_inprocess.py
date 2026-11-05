"""The in-process fast path of :meth:`Url4Node.fetch_ex` — a node's own endpoint, no URL.

FEATURE: in-process dispatch (memory fix 1, OME-1834;
spec ``docs/spec/2026-11-05-url4-inprocess-dispatch.md``).
STORY: as an operator running a 12k-Case benchmark, the aggregate call's ~150 MB context
reaches the grading endpoint as the string it already is, so the run stays inside its
memory budget.

A relative expression call arrives as a ``SubrequestFetch`` (``url4.dag``) carrying a
structured :class:`~url4.wire.subrequest.SubrequestCall`. When its path is an endpoint this
node registered, the handler gets its :class:`~url4.peer._dispatch.Request` built straight
from the call; everything else — the eval path, a data route, an unknown path, a path with its
own ``?``, a plain ``FetchRequest`` — goes through :func:`url4.peer._dispatch.fetch_ex`
exactly as before.

AIDEV-NOTE: detection is by the ``call`` attribute, not by importing ``SubrequestFetch``:
the node layer reads the wire type it owns a contract with, never an engine class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from url4.io.layer import FetchRequest, FetchResult
from url4.peer import _dispatch
from url4.wire.subrequest import SubrequestCall

if TYPE_CHECKING:  # the node type only — this module never constructs one
    from url4.peer.server import Url4Node


async def fetch_ex(node: Url4Node, request: FetchRequest) -> FetchResult:
    """Serve ``request``: a call to one of ``node``'s endpoints directly, else the wire path."""
    call = getattr(request, "call", None)
    if isinstance(call, SubrequestCall) and _serves_endpoint(node, call.path):
        context, intent, params = call.endpoint_parts()
        req = _dispatch.Request(path=call.path, context=context, intent=intent, params=params)
        body = await _dispatch._text(node._endpoints[call.path](req))
        return FetchResult(body, None)  # the wire path's endpoint branch declares no media type
    return await _dispatch.fetch_ex(node, request)


def _serves_endpoint(node: Url4Node, path: str) -> bool:
    # INVARIANT: the fast path takes only what the wire path would route to this endpoint.
    # A "?" in the path would move the wire split (`target.partition("?")`), so that call
    # keeps the wire path and its own semantics.
    return "?" not in path and path in node._endpoints
