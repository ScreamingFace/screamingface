"""Host-specific notebook services, imported only in an active notebook."""

from __future__ import annotations

import json
import weakref
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import uuid4


def in_colab() -> bool:
    try:
        from IPython.core.getipython import get_ipython
    except ImportError:
        return False
    shell = get_ipython()
    # INVARIANT: installing google.colab in another host does not change its behavior.
    return shell is not None and type(shell).__module__.startswith("google.colab.")


def prepare_widgets() -> None:
    if in_colab():
        output = import_module("google.colab.output")

        # WHY: Colab requires its custom manager for third-party widgets such as ipyevents.
        output.enable_custom_widget_manager()


def download_in_colab(path: Path) -> bool:
    if not in_colab():
        return False
    files = import_module("google.colab.files")

    # WHY: kernel-local Jupyter URLs resolve to browser localhost in Colab output frames.
    files.download(str(path))
    return True


def case_click_handler(callback: Any) -> str:
    if not in_colab():
        return ""
    output = import_module("google.colab.output")
    name = f"screamingface.case.{uuid4().hex}"
    reference = weakref.WeakMethod(callback)

    def select(event: dict) -> None:
        method = reference()
        if method is not None:
            method(event)

    # WHY: Colab lazily loads displayed widget models; standalone ipyevents models
    # are not reached by its manager. Its native output callback carries Case identity.
    output.register_callback(name, select)
    weakref.finalize(callback.__self__, output.unregister_callback, name)
    return (
        f"google.colab.kernel.invokeFunction({json.dumps(name)}, "
        "[{target: {id: this.id}}], {})"
    )
