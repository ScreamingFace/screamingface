"""url4.dag.semantics — execution-time value semantics used by DAG nodes.

Pure helpers a node calls at resolve time. They are not the AST
(``url4.core``) and not a port (``url4.io``); they are the engine's runtime
vocabulary.

Owns
----
- ``collection`` — ``parse_collection``: fetched body → iterable string items
  (spec §5.3.7), consumed by the ``*`` iteration and ``;expand``.
- ``ensemble`` — ``$name`` / ``$item`` substitution and reducer-input assembly
  (spec §8.2), consumed by the fetch and group nodes.

May import: the standard library, ``url4.core``, and other ``url4.dag`` modules.
Must not import: ``url4.io`` adapters, ``url4.peer``, ``url4.cli``,
``url4.streaming``.

See ``ARCHITECTURE.md`` for the layer map and the direction rule.
"""
