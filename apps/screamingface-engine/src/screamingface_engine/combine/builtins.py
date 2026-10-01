"""The one place that lists the built-in combine operator plugins (wiring).

Mirrors benchmarks/builtins.py BUILTIN_REGISTRATIONS: the registry is built at import, so a
duplicate operator id stops the process at start (FW-D5). Unit 2 adds the plugin modules here.
"""

from __future__ import annotations

from screamingface_engine.combine.ports import OperatorDescriptor
from screamingface_engine.combine.registry import OperatorRegistry

BUILTIN_REGISTRATIONS: tuple[OperatorDescriptor, ...] = ()
BUILTIN_OPERATORS = OperatorRegistry(BUILTIN_REGISTRATIONS)

__all__ = ["BUILTIN_OPERATORS", "BUILTIN_REGISTRATIONS"]
