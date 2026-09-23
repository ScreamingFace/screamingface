"""url4.io — the I/O PORT and its adapters: the seam between engine and network.

Executable nodes never perform I/O themselves. They depend on the
:class:`~url4.io.layer.IOLayer` port; adapters implement it.

Owns
----
- ``layer`` — the port (``IOLayer``, ``FetchRequest``/``FetchResult``) and the
  optional capability protocols (``SupportsFetchEx``, ``SupportsHoldings``, …).
  Standard library only, so the engine can name the port without a transport.
- ``static`` — ``StaticIOLayer``: in-memory, deterministic; the test default.
- ``http`` — ``HttpIOLayer``: the httpx adapter.

May import: the standard library, ``url4.core``, and ``url4.wire``.
Must not import: ``url4.dag`` (the engine depends on this port, not the
reverse), ``url4.peer``, ``url4.cli``, ``url4.streaming``.

See ``ARCHITECTURE.md`` for the layer map and the direction rule.
"""
