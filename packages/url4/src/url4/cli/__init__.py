"""url4.cli — the ``url4`` console script: ``url4 serve`` and ``url4 eval``.

Owns
----
- ``app`` — argument parsing and dispatch; imports no web framework.
- ``_serve`` — the ASGI assembly and subprocess handlers for ``url4 serve``.
- ``_config`` — the ``url4.toml`` contract, resolution, and validation.

This is the composition root for the node layer: it wires ``Url4Node`` and
``ServeConfig`` together. Uvicorn is imported lazily, so ``url4 --version`` and
``url4 eval`` work on the base install.

May import: everything it composes, except ``url4.streaming``.

See ``ARCHITECTURE.md`` for the layer map and the direction rule.
"""
