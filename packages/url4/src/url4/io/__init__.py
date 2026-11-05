"""url4.io — the I/O PORT and its adapters: the seam between engine and network.

Executable nodes never perform I/O themselves. They depend on the
:class:`~url4.io.layer.IOLayer` port; adapters implement it.

Owns
----
- ``layer`` — the port (``IOLayer``, ``FetchRequest``/``FetchResult``) and the
  optional capability protocols (``SupportsFetchEx``, ``SupportsHoldings``, …).
  Standard library only, so the engine can name the port without a transport.
- ``media`` — the binary-safe bytes port (``FetchedBytes``, ``SupportsFetchBytes``,
  ``fetch_bytes``) and the text/binary media-type rule the adapters' text paths share.
- ``idempotency`` — the ``Idempotency-Key`` a retrying guard offers to adapters
  ("reuse until answered"), carried in a context variable. Standard library only.
- ``static`` — ``StaticIOLayer``: in-memory, deterministic; the test default.
- ``http`` — ``HttpIOLayer``: the httpx adapter, with its private destination guard
  (spec F1b): ``_source_policy`` (stdlib: scheme, address, peer rules; ``SourceGuard``)
  and ``_guarded_transport`` (the httpx transport that enforces them on every hop).

May import: the standard library, ``url4.core``, and ``url4.wire``.
Must not import: ``url4.dag`` (the engine depends on this port, not the
reverse), ``url4.observe``, ``url4.peer``, ``url4.cli``, ``url4.streaming``.

See ``ARCHITECTURE.md`` for the layer map and the direction rule.
"""
