# pyright: reportMissingImports=false
# WHY file-level: this suite imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""The fidelity check reads the same catalogue, and the same fingerprint, as the goldens (OME-1471).

INVARIANT: `fidelity_check.declared_today()` and `test_benchmark_fingerprints._fingerprint`
must agree on what a Benchmark's fingerprint is, or a record could read `fresh` against a value
no golden pins. Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from test_benchmark_fingerprints import _FINGERPRINTS  # noqa: E402

from screamingface_engine.benchmarks.medxpert import definition as medxpert  # noqa: E402
from screamingface_engine_inspect.benchmarks import BENCHMARKS, imported_benchmark  # noqa: E402

_SCRIPT: Path = Path(__file__).resolve().parents[3] / "scripts" / "fidelity_check.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fidelity_check", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_registered_benchmark_is_declared_exactly_once() -> None:
    declared = _module().declared_today()

    expected: set[str] = {imported_benchmark(spec.key).benchmark.id for spec in BENCHMARKS}
    expected.add(medxpert.MEDXPERT.id)
    assert set(declared) == expected
    assert all(declared[name].benchmark == name for name in declared)


def test_the_declared_fingerprint_is_the_golden_one() -> None:
    """The script's "today" value for IFEval is the literal the fingerprint golden pins."""

    declared = _module().declared_today()

    assert declared["ifeval"].fingerprint == _FINGERPRINTS["ifeval"]
    assert declared["ifeval"].origin == "screamingface"
    assert declared["ifeval"].harness_url is not None
    assert declared["medxpert"].fingerprint == _FINGERPRINTS["medxpert"]


def test_the_real_catalogue_path_opens_no_network_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """INVARIANT: the whole check is offline, including the half that loads the plugin.

    The extra-less socket test injects the catalogue, so it never runs `declared_today()`, the
    only code that touches the plugin and its pins. This runs `main()` end to end with name
    resolution and outbound connects refused, so a `declared_today` that fetched the Hub fails.
    """

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the fidelity check must not touch the network")

    module = _module()
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)

    code: int = module.main(["--records", str(tmp_path)])

    out: str = capsys.readouterr().out
    assert code == 0
    assert f"{len(module.declared_today())} no record" in out
