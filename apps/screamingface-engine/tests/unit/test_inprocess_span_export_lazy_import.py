"""The in-process adapter's span-export wiring keeps the OTel SDK import lazy (e2e unit 6a).

A module of its own because the test is SYNC: `test_inprocess_span_export` marks every test
`asyncio` module-wide, and pytest-asyncio warns on a sync test carrying that mark.
"""

import subprocess
import sys


def test_importing_the_inprocess_adapter_does_not_load_opentelemetry() -> None:
    """A clean subprocess, as in `test_span_export_wiring`: wiring the relay here must not pull
    the OTel SDK into every local App's import graph — only a configured endpoint may load it."""
    probe = (
        "import sys; import screamingface_engine.adapters.inprocess; "
        "print(len([m for m in sys.modules if m.startswith('opentelemetry')]))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert loaded.stdout.strip() == "0"
