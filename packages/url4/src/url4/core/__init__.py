"""url4.core — the LANGUAGE layer: url4 text ↔ AST.

Turns url4 surface text into a frozen parse tree and back. Pure and
synchronous: no I/O, no async, no network.

Owns
----
- ``grammar`` / ``parser`` — ``parse(text)`` and ``build(text)``: text → AST.
- ``nodes`` — the AST node union (frozen dataclasses, no behavior).
- ``render`` — AST → canonical text; the certified inverse of ``build``.
- ``builders`` — the Python AST builders (``expr``, ``src``, ``iterate``, …).
- ``context`` — the lexical scope chain (``$name`` resolution).
- ``_scan`` / ``_annotations`` — shared scanning and annotation validation.
- ``errors`` — the shared error hierarchy; a leaf every layer imports.

May import: the standard library and other ``url4.core`` modules only.
Must not import: ``url4.wire``, ``url4.dag``, ``url4.io``, ``url4.observe``,
``url4.peer``, ``url4.cli``, ``url4.streaming``.

See ``ARCHITECTURE.md`` for the layer map and the direction rule.
"""
