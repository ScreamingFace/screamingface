"""The built-in combine operator plugins (OME-1289, E4a).

Each module here exports ``OPERATORS``, a tuple of ``OperatorDescriptor``. A plugin imports
``screamingface_engine.combine.ports`` and the standard library, and may import a sibling
plugin's pure functions (never its ``OPERATORS``); it imports no ``url4`` module and no other
engine module. ``combine/builtins.py`` is the one module that lists the plugin modules. This
package re-exports nothing.
"""
