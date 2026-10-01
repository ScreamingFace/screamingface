"""The control plane's half of span export (OME-1218): off unless configured, never fatal.

Same two properties `test_span_export_wiring.py` pins for the run half, for the same reasons:
an App with no OTLP endpoint must behave exactly as before, and a broken exporter config must
not stop the App from serving runs.
"""

from __future__ import annotations

import subprocess
import sys

from screamingface_engine.app import control_plane_span_sink

ENDPOINT = "http://collector.invalid:4318"


def test_a_clean_environment_gets_no_control_plane_sink() -> None:
    assert control_plane_span_sink({}) is None


def test_a_blank_endpoint_is_off() -> None:
    assert control_plane_span_sink({"OTEL_EXPORTER_OTLP_ENDPOINT": " "}) is None


def test_a_configured_endpoint_gets_a_sink() -> None:
    sink = control_plane_span_sink({"OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT})

    assert sink is not None
    sink.close()


def test_a_broken_exporter_config_does_not_stop_the_app(monkeypatch) -> None:
    import screamingface_engine.tracing.otlp as otlp

    def explode(_env: object) -> None:
        raise RuntimeError("bad OTLP config")

    monkeypatch.setattr(otlp, "sink_from_env", explode)

    assert control_plane_span_sink({"OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT}) is None


def test_the_accept_span_module_does_not_load_opentelemetry() -> None:
    """INVARIANT: `tracing.accept` is pure, like `relay` and `span_tree` — the OTel import
    stays confined to `tracing.otlp`. Clean subprocess so the claim cannot pass vacuously."""
    probe = (
        "import sys; import screamingface_engine.tracing.accept; "
        "print(len([m for m in sys.modules if m.startswith('opentelemetry')]))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert loaded.stdout.strip() == "0"
