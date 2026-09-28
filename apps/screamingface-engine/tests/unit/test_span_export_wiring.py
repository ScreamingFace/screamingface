"""The composition root's half of span export (OME-1130): what a Job pays, and when.

Two properties, both of which fail SILENTLY if broken — which is why they are tests and not
comments:

* export is OFF unless configured, so no existing run changes behaviour;
* the OTel SDK is not imported when it is off, so no Job pays ~62 ms of cold start for a
  feature it does not use.

The second is the same discipline `check_layering.py` applies to the engine's own modules.
That gate protects a Job's import graph from `screamingface_engine` submodules and cannot see
a third-party dependency, so this covers the direction it structurally cannot.
"""

from __future__ import annotations

import subprocess
import sys

from screamingface_engine.runner.main import span_sink

ENDPOINT = "http://collector.invalid:4318"


# --- off unless configured --------------------------------------------------------------------


def test_a_clean_environment_gets_no_sink() -> None:
    assert span_sink({}) is None


def test_a_configured_endpoint_gets_a_sink() -> None:
    sink = span_sink({"OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT})

    assert sink is not None
    sink.close()


def test_a_blank_endpoint_is_off_not_broken() -> None:
    """A chart renders `""` for an environment nobody has configured yet. That must read as
    "off" — not as an endpoint, and not as a crash on boot."""
    assert span_sink({"OTEL_EXPORTER_OTLP_ENDPOINT": ""}) is None


def test_a_broken_exporter_config_does_not_stop_the_run(monkeypatch) -> None:
    """INVARIANT: telemetry degrades ALONE. A misconfigured collector must not become the
    reason a benchmark run never happens — the run is worth more than its trace."""
    import screamingface_engine.tracing.otlp as otlp

    def explode(_env: object) -> None:
        raise RuntimeError("bad OTLP config")

    monkeypatch.setattr(otlp, "sink_from_env", explode)

    assert span_sink({"OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT}) is None


# --- what the import costs ----------------------------------------------------------------


def test_importing_the_run_entrypoint_does_not_load_opentelemetry() -> None:
    """A CLEAN SUBPROCESS, so the claim has teeth: in-process, another test having imported
    `tracing.otlp` would leave `opentelemetry` in `sys.modules` and this would pass vacuously.

    `packages/url4/tests/unit/test_import_isolation.py` makes the same claim the same way, for
    the same reason.
    """
    probe = (
        "import sys; import screamingface_engine.runner.main; "
        "print(len([m for m in sys.modules if m.startswith('opentelemetry')]))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert loaded.stdout.strip() == "0", (
        "importing the run entrypoint pulled in the OTel SDK — every Job now pays ~62ms of "
        "cold start for a feature most of them do not use. Keep the import inside `span_sink`."
    )


def test_the_probe_can_actually_detect_a_loaded_sdk() -> None:
    """The guard above asserts a ZERO count, so it would also pass if the probe were simply
    broken and always printed 0. This proves the probe sees the SDK when it IS there."""
    probe = (
        "import sys; import screamingface_engine.tracing.otlp; "
        "print(len([m for m in sys.modules if m.startswith('opentelemetry')]))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert int(loaded.stdout.strip()) > 0
