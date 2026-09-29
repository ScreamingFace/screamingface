"""Process-local composition root for analytics adapters."""

import os
import sys
import threading

from screamingface._analytics.core import Coordinator
from screamingface._analytics.delivery import BackgroundSink
from screamingface._analytics.ports import Consent
from screamingface._environment import running_in_notebook
from screamingface._version import resolve_version

_pid = os.getpid()
_lock = threading.Lock()
_coordinator: Coordinator | None = None


class Preferences:
    def read(self) -> Consent:
        from screamingface.analytics import _consent

        return _consent()


def origin() -> str:
    if "google.colab" in sys.modules:
        return "colab"
    return "local_jupyter" if running_in_notebook() else "python"


def coordinator() -> Coordinator:
    global _pid, _lock, _coordinator
    if _pid != os.getpid():
        # INVARIANT: a fork never reuses inherited locks, worker queues or session IDs.
        _pid, _lock, _coordinator = os.getpid(), threading.Lock(), None
    with _lock:
        if _coordinator is None:
            endpoint = "https://analytics.dev.screamingface.ai/v1/events"
            sink = BackgroundSink(endpoint, lambda event: selected.accepts(event))
            selected = Coordinator(Preferences(), sink, version=resolve_version())
            _coordinator = selected
        return _coordinator


def clear() -> None:
    if _coordinator is not None and _pid == os.getpid():
        _coordinator.clear()
