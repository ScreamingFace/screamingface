"""url4.peer — the NODE layer: network participation (server + client).

Owns
----
- ``server`` — ``Url4Node``: registers endpoints/data/holdings/identities and
  serves the engine over HTTP.
- ``client`` — ``Client``, ``Url4Result``, ``evaluate_sync``: the requestor
  facade.
- ``direct`` — ``dispatch_direct``, ``describe_routes``: the PUBLIC one-handler call a host
  uses for mount calls; it refuses the eval path (spec D1).
- ``_dispatch`` / ``_http`` / ``_asgi`` / ``_owned`` — the dispatch order and
  the framework-free ASGI adapter.
- ``_request`` — ``Request``, the handler contract for every endpoint call.
- ``_code_pointer`` — the receiver of a code-pointer (RDS) call: decode, opt-in, errors.
- ``_holdings`` — the ``@`` holdings and ``@identity`` registration (§5.6), a mixin of
  ``Url4Node``.

May import: everything below it — ``url4.core``, ``url4.wire``, ``url4.dag``,
``url4.io``, ``url4.observe``.
Must not import: ``url4.cli`` (the CLI composes the node, not the reverse) or
``url4.streaming``.

See ``ARCHITECTURE.md`` for the layer map and the direction rule.
"""

from url4.peer.direct import (
    DirectResult,
    RouteInfo,
    describe_routes,
    dispatch_direct,
    http_status,
    is_eval_path,
)

__all__ = [
    "DirectResult",
    "RouteInfo",
    "describe_routes",
    "dispatch_direct",
    "http_status",
    "is_eval_path",
]
