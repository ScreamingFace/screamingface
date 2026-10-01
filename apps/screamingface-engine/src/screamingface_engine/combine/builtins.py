"""The one place that lists the built-in combine operator plugins (wiring).

Mirrors benchmarks/builtins.py BUILTIN_REGISTRATIONS: the registry is built at import, so a
duplicate operator id stops the process at start (FW-D5). Each later unit adds its plugin module
here and a golden fixture file for each operator id.
"""

from __future__ import annotations

from screamingface_engine.combine.operators import (
    extract,
    fields,
    judge,
    normalize,
    reduce,
    select,
    selection,
)
from screamingface_engine.combine.ports import OperatorDescriptor
from screamingface_engine.combine.registry import OperatorRegistry

BUILTIN_REGISTRATIONS: tuple[OperatorDescriptor, ...] = (
    *extract.OPERATORS,
    *fields.OPERATORS,
    *judge.OPERATORS,
    *normalize.OPERATORS,
    *reduce.OPERATORS,
    *select.OPERATORS,
    *selection.OPERATORS,
)
BUILTIN_OPERATORS = OperatorRegistry(BUILTIN_REGISTRATIONS)

__all__ = ["BUILTIN_OPERATORS", "BUILTIN_REGISTRATIONS"]
