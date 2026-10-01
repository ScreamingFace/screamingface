"""The built-in combine operator plugins (OME-1289, E4a).

Each module here exports ``OPERATORS``, a tuple of ``OperatorDescriptor``. A plugin imports only
``screamingface_engine.combine.ports`` and the standard library; ``combine/builtins.py`` is the
one module that lists the plugin modules. This package re-exports nothing.
"""
