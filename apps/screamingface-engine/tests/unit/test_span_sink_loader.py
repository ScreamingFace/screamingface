"""ONE span-sink loader, in the `tracing` shared leaf (OME-1462).

`app.control_plane_span_sink` and `runner.main.span_sink` were the same function written
twice (the control plane may not import the run half, so it could not borrow it). Both are
now the leaf's `load_span_sink`; the two names stay as the composition roots' seams.

INVARIANT: the leaf loads the OTel SDK only when a sink is actually built — importing
`screamingface_engine.tracing` (which `runner/main.py` does on every Job's cold path) loads none
of it. `test_span_export_wiring.py` holds the same line for `runner.main`.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from screamingface_engine.app import control_plane_span_sink
from screamingface_engine.runner import main
from screamingface_engine.tracing import load_span_sink

ENDPOINT = "http://collector.invalid:4318"


def test_both_composition_roots_use_the_one_loader() -> None:
    assert main.span_sink is load_span_sink
    assert control_plane_span_sink is load_span_sink


@pytest.mark.parametrize("env", [{}, {"OTEL_EXPORTER_OTLP_ENDPOINT": "  "}])
def test_an_unconfigured_environment_gets_no_sink(env: dict[str, str]) -> None:
    assert load_span_sink(env) is None


def test_the_signal_specific_endpoint_alone_gets_a_sink() -> None:
    sink = load_span_sink({"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": ENDPOINT})

    assert sink is not None
    sink.close()


def test_a_broken_exporter_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Telemetry degrades ALONE — for the App and the run alike."""
    import screamingface_engine.tracing.otlp as otlp

    def explode(_env: object) -> None:
        raise RuntimeError("bad OTLP config")

    monkeypatch.setattr(otlp, "sink_from_env", explode)

    assert load_span_sink({"OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT}) is None


def test_importing_the_tracing_leaf_does_not_load_opentelemetry() -> None:
    """A clean subprocess, so another test's import cannot make this pass vacuously."""
    probe = (
        "import sys; import screamingface_engine.tracing; "
        "print(len([m for m in sys.modules if m.startswith('opentelemetry')]))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert loaded.stdout.strip() == "0"
