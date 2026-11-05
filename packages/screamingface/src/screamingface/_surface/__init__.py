"""The map → select → reduce recipe surface (E4b, OME-1653), exported as ``sf.*``.

FEATURE: one grammar, composed left to right with ``>>``::

    Fanout(members, signals=...)  >>  [Judge]  >>  [Rank | Filter]*  >>  terminal

A ``Fanout`` opens a block, a ``Judge`` scores it, the narrow steps (``Rank``, ``Filter``,
``Concat``) make the panel smaller, and a reducer (``Vote``, ``Median``, ``Mean``, ``ArgMax``,
``ArgMin``, ``First``, ``Merge``, ``JudgePick``, ``Gate``) or a writer (``Synthesize``) closes it.
``lowering.lower`` turns a chain into the internal nodes that the compiler reads.
INVARIANT: ``screamingface/__init__.py`` exports the public names; this package exports none, so
each name has one public path (``sf.<Name>``).
"""
