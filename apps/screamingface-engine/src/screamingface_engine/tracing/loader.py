"""The span sink a deployment configured, built on demand (OME-1130, OME-1218, OME-1462).

One loader for both composition roots: the App (`app.control_plane_span_sink`, the accept
span) and the run (`runner.main.span_sink`, the run's waterfall). It lives in this shared leaf
because the control plane may not import the run half (`check_layering.py`), which is why it
had been written twice.

WHY the import is LAZY. `tracing.otlp` pulls the OTel SDK, protobuf and `requests` — measured
at ~62 ms of a Job's ~227 ms import time, which every Job would otherwise pay whether or not it
exports anything. `check_layering.py` protects a Job's cold start from the engine's OWN
modules; nothing protects it from a third-party dependency, so this is the same discipline
applied by hand. `tests/unit/test_span_sink_loader.py` and `test_span_export_wiring.py` check
it in a clean subprocess.

INVARIANT: never raises. A broken exporter config must not stop a run from happening or the
App from serving — telemetry degrades alone. An unreachable collector is already handled
downstream (the exporter drops); this covers the boot-time half.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from screamingface_engine.tracing.relay import SpanSink, otlp_configured

logger = logging.getLogger(__name__)


def load_span_sink(env: Mapping[str, str]) -> SpanSink | None:
    """The configured span sink, or ``None`` when this deployment set no OTLP endpoint."""
    if not otlp_configured(env):
        return None
    try:
        from screamingface_engine.tracing.otlp import sink_from_env

        return sink_from_env(env)
    except Exception:
        logger.warning("span export is configured but could not be started", exc_info=True)
        return None


__all__ = ["load_span_sink"]
