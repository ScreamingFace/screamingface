"""Host-environment capabilities shared across client features."""

from __future__ import annotations

import builtins
import sys


def running_in_notebook() -> bool:
    """Whether the active IPython host is an ipykernel-backed notebook."""
    get_ipython = getattr(builtins, "get_ipython", None)
    if not callable(get_ipython):
        return False
    try:
        shell = get_ipython()
    except Exception:  # pragma: no cover - defensive around a host-provided hook
        shell = None
    if shell is None:
        return False
    # WHY inspect the MRO: hosted notebooks such as Colab and Databricks subclass the
    # ipykernel shell from their own modules, so the concrete class name alone lies.
    return any(cls.__module__.startswith("ipykernel") for cls in type(shell).__mro__)


def ipykernel_loaded() -> bool:
    """Whether ipykernel is loaded, the established progress-panel capability signal."""
    return "ipykernel" in sys.modules


__all__: list[str] = []
