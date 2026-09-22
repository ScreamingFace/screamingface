"""url4.peer — the NODE layer: network participation (server + client).

Owns
----
- ``server`` — ``Url4Node``: registers endpoints/data/holdings/identities and
  serves the engine over HTTP.
- ``client`` — ``Client``, ``Url4Result``, ``evaluate_sync``: the requestor
  facade.
- ``_dispatch`` / ``_http`` / ``_asgi`` / ``_owned`` — the dispatch order and
  the framework-free ASGI adapter.

May import: everything below it — ``url4.core``, ``url4.wire``, ``url4.dag``,
``url4.io``, ``url4.observe``.
Must not import: ``url4.cli`` (the CLI composes the node, not the reverse) or
``url4.streaming``.

See ``ARCHITECTURE.md`` for the layer map and the direction rule.
"""
