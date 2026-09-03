"""url4 — a standalone core library for the url4 expression protocol.

url4 expresses multi-source computation as ``(sources)!intent`` — "given this
data, do this" — recursively, with ``$name`` / ``$N`` references (and their
``.field`` / ``[N]`` paths) resolved through a lexical scope. An expression
compiles into an executable **DAG** of typed nodes (:mod:`url4.dag`): each node
owns its own piece of logic behind the ``DagNode`` protocol, independent
nodes run in parallel, and nested fragments parse lazily inside the node that
owns them. All I/O is inverted behind the :class:`IOLayer` port, so the core is
deterministic and framework-free.

Quickstart::

    from url4 import Client, StaticIOLayer, evaluate_sync

    io = StaticIOLayer(fetch_map={"https://x": "some article text"})
    text = "(a=https://x, tone='formal')!'Summarize $a in a $tone tone'"

    # scripts and REPLs: one call, no event loop to manage
    print(evaluate_sync(text, io).text)

    # async code owns a Client (Client() with no io speaks real HTTP)
    async with Client(io) as client:
        res = await client.evaluate(text)
        print(res.request)               # the canonical url4 text that ran

Iteration (``src*(body)!intent``) resolves to a JSON array of per-row results
(spec §5.3.8); broadcast (``!*``) to a JSON array of per-source result objects
(spec §6.1.4).

SDK facades — build expressions in Python (:mod:`url4.core.builders`), print them
canonically (:func:`render`, the certified inverse of :func:`build`), query as
a requestor (:class:`Client`), or stand up a node (:class:`Url4Node`)::

    from url4 import Client, Url4Node, src

    node = Url4Node("demo")

    @node.endpoint("/claude")
    async def claude(request):          # the intent processor
        return f"[claude] {request.intent}"

    async def main():
        # in-process: the node is its own execution engine (and an IOLayer)
        print(await node.evaluate("(@)!'hello'"))
        # as a requestor, with the expression built in Python
        async with Client(node) as client:
            result = await client.query(src("https://x"), intent="Summarize $1")
            print(result.request)        # the canonical url4 text that ran

    # node.serve(port=4404) exposes the same dispatch over HTTP GET (url4[server])

The execution engine — DAG compilation, the executor, lowering — lives one
level down: ``from url4.dag import compile_expression, run``; the wire codecs
in :mod:`url4.core.subrequest`; scope internals in :mod:`url4.core.context`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from url4.core.builders import (
    ParamsLike,
    SourceLike,
    broadcast,
    expand,
    expr,
    identity,
    iterate,
    reduce,
    ref,
    self_,
    src,
    struct,
    text,
)
from url4.core.errors import (
    CollectionError,
    CycleError,
    ParseError,
    RenderError,
    ResolutionError,
    ScopeError,
    Url4Error,
)
from url4.core.nodes import (
    Binding,
    Expression,
    IdentityRef,
    Iteration,
    Node,
    RelExpr,
    RelUrl,
    RemoteExpr,
    SelfRef,
    Source,
    StructObject,
    Text,
    Url,
    VarRef,
)
from url4.core.parser import build, walk
from url4.core.render import render
from url4.io.layer import (
    FetchRequest,
    FetchResult,
    IOLayer,
    SupportsDefaultRoute,
    SupportsFetchEx,
    SupportsHoldings,
    SupportsProcessorRoutes,
)
from url4.io.static import StaticIOLayer
from url4.peer.client import Client, Url4Result, evaluate_sync
from url4.peer.server import Request, Url4Node

if TYPE_CHECKING:  # `url4.HttpIOLayer` still type-checks; see __getattr__ below.
    from url4.io.http import HttpIOLayer

__version__ = "1.5.1"


# AIDEV-NOTE: HttpIOLayer is resolved lazily (PEP 562) so `import url4` never
# pulls in httpx — ~44ms of a ~95ms import, paid by `url4 --version` and
# `url4 eval`, neither of which speaks HTTP. This mirrors the discipline the
# execution core already keeps: `executor._run_context`, `Client._effective_io`
# and `Url4Node._outbound_io` all import the concrete transport inside the
# function, so the static import graph names no transport.
def __getattr__(name: str) -> object:
    if name == "HttpIOLayer":
        from url4.io.http import HttpIOLayer

        return HttpIOLayer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Binding",
    "Client",
    "CollectionError",
    "CycleError",
    "Expression",
    "FetchRequest",
    "FetchResult",
    "HttpIOLayer",
    "IOLayer",
    "IdentityRef",
    "Iteration",
    "Node",
    "ParamsLike",
    "ParseError",
    "RelExpr",
    "RelUrl",
    "RemoteExpr",
    "RenderError",
    "Request",
    "ResolutionError",
    "ScopeError",
    "SelfRef",
    "Source",
    "SourceLike",
    "StaticIOLayer",
    "StructObject",
    "SupportsDefaultRoute",
    "SupportsFetchEx",
    "SupportsHoldings",
    "SupportsProcessorRoutes",
    "Text",
    "Url",
    "Url4Error",
    "Url4Node",
    "Url4Result",
    "VarRef",
    "__version__",
    "broadcast",
    "build",
    "evaluate_sync",
    "expand",
    "expr",
    "identity",
    "iterate",
    "reduce",
    "ref",
    "render",
    "self_",
    "src",
    "struct",
    "text",
    "walk",
]
