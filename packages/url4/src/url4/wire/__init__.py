"""url4.wire — the shared sub-request wire codec (one owner).

A relative expression ``/path(context)!intent`` is dispatched as a localhost
fetch of ``/path?[params&]q=(context)!intent``. ``subrequest`` is the single
definition of that encoding: the engine builds sub-requests with it, and every
node adapter decodes them with it.

This is a SHARED layer. Both the engine (``url4.dag``) and the node layer
(``url4.io``, ``url4.peer``) import it, so it must stay below both.

May import: the standard library and ``url4.core``.
Must not import: ``url4.dag``, ``url4.io``, ``url4.observe``, ``url4.peer``,
``url4.cli``, ``url4.streaming``.

See ``ARCHITECTURE.md`` for the layer map and the direction rule.
"""
