"""One deployment declaration drives runtime discovery and image asset preparation."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from screamingface_engine.benchmarks import prepare as prepare_module
from screamingface_engine.benchmarks.builtins import (
    BUILTIN_BENCHMARKS,
    BUILTIN_DEPLOYMENT,
)
from screamingface_engine.benchmarks.definition import Benchmark
from screamingface_engine.benchmarks.deployment import (
    BenchmarkAssetBundle,
    BenchmarkAssetPreparationError,
    BenchmarkDeployment,
    BenchmarkRegistration,
)
from screamingface_engine.benchmarks.draco.prepare import PrepareError as DracoPrepareError
from screamingface_engine.benchmarks.healthbench.prepare import (
    PrepareError as HealthBenchPrepareError,
)
from screamingface_engine.benchmarks.ifeval.prepare import PrepareError as IFEvalPrepareError
from screamingface_engine.benchmarks.registry import DEFAULT_BENCHMARK_ASSETS_ROOT
from url4 import Text

REPOSITORY_ROOT = Path(__file__).parents[4]
_FAMILY_PREPARER = re.compile(r"screamingface_engine\.benchmarks\.[a-z0-9_]+\.prepare")


def _benchmark(benchmark_id: str) -> Benchmark:
    return Benchmark(
        id=benchmark_id,
        title=benchmark_id,
        description=f"{benchmark_id} description",
        revision="revision-1",
        case_count=1,
        build=lambda _selected: Text("protocol"),
    )


def test_deployment_prepares_each_shared_bundle_once_in_stable_directories(
    tmp_path: Path,
) -> None:
    calls: list[Path] = []

    def prepare(out: Path) -> dict[str, object]:
        calls.append(out)
        return {"cases": len(calls), "out": str(out)}

    shared = BenchmarkAssetBundle(id="shared", prepare=prepare)
    alpha = BenchmarkAssetBundle(id="alpha", prepare=prepare)
    deployment = BenchmarkDeployment(
        (
            BenchmarkRegistration(_benchmark("one"), asset_bundle=shared),
            BenchmarkRegistration(_benchmark("two"), asset_bundle=shared),
            BenchmarkRegistration(_benchmark("three"), asset_bundle=alpha),
        )
    )

    prepared = deployment.prepare_assets(tmp_path)

    assert tuple(benchmark.id for benchmark in deployment.benchmarks) == (
        "one",
        "three",
        "two",
    )
    assert calls == [tmp_path / "alpha", tmp_path / "shared"]
    assert prepared == {
        "alpha": {"cases": 1, "out": str(tmp_path / "alpha")},
        "shared": {"cases": 2, "out": str(tmp_path / "shared")},
    }
    assert all(path.is_dir() for path in calls)


def test_builtin_prepare_cli_prints_one_auditable_record_per_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summaries = {
        "draco": {"cases": 100},
        "healthbench": {"professional_cases": 525, "worst30_cases": 157},
        "ifeval": {"cases": 541, "patched_keys": [146, 179]},
    }
    monkeypatch.setattr(prepare_module, "prepare_builtin_assets", lambda _root: summaries)

    assert prepare_module.main(["--root", str(tmp_path)]) == 0

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records == [
        {"root": str(tmp_path), "bundle": bundle, "summary": summary}
        for bundle, summary in summaries.items()
    ]


def test_builtin_prepare_cli_reports_declared_refusal_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def refuse(_root: Path) -> dict[str, object]:
        raise BenchmarkAssetPreparationError("frozen answer key drifted")

    monkeypatch.setattr(prepare_module, "prepare_builtin_assets", refuse)

    assert prepare_module.main(["--root", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "benchmark asset preparation failed: frozen answer key drifted\n"
    assert "Traceback" not in captured.err


def test_builtin_prepare_cli_does_not_hide_unexpected_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(_root: Path) -> dict[str, object]:
        raise AssertionError("programming defect")

    monkeypatch.setattr(prepare_module, "prepare_builtin_assets", explode)

    with pytest.raises(AssertionError, match="programming defect"):
        prepare_module.main(["--root", str(tmp_path)])


@pytest.mark.parametrize(
    "error_type",
    (DracoPrepareError, HealthBenchPrepareError, IFEvalPrepareError),
)
def test_family_preparation_refusals_share_the_operator_error_boundary(
    error_type: type[Exception],
) -> None:
    assert issubclass(error_type, BenchmarkAssetPreparationError)


def test_conflicting_physical_bundles_cannot_share_a_directory_id() -> None:
    first = BenchmarkAssetBundle(id="shared", prepare=lambda _out: {})
    second = BenchmarkAssetBundle(id="shared", prepare=lambda _out: {})

    with pytest.raises(ValueError, match="conflicting BenchmarkAssetBundles"):
        BenchmarkDeployment(
            (
                BenchmarkRegistration(_benchmark("one"), asset_bundle=first),
                BenchmarkRegistration(_benchmark("two"), asset_bundle=second),
            )
        )


@pytest.mark.parametrize("bundle_id", ("../escape", "nested/path", "UPPER", "-leading"))
def test_asset_bundle_ids_are_safe_directory_names(bundle_id: str) -> None:
    with pytest.raises(ValueError, match="path-safe"):
        BenchmarkAssetBundle(id=bundle_id, prepare=lambda _out: {})


def test_builtins_are_registered_with_their_physical_asset_bundles() -> None:
    registrations = {
        registration.benchmark.id: registration.asset_bundle.id
        for registration in BUILTIN_DEPLOYMENT.registrations
    }

    assert BUILTIN_DEPLOYMENT.benchmarks is BUILTIN_BENCHMARKS
    assert registrations == {
        "draco": "draco",
        "draco-3pass": "draco",
        "ifeval": "ifeval",
        "healthbench-worst30": "healthbench",
        "healthbench-professional": "healthbench",
    }


def test_benchmark_image_invokes_only_the_registered_asset_orchestrator() -> None:
    dockerfile = Path(__file__).parents[2] / "Dockerfile.benchmark"
    body = dockerfile.read_text(encoding="utf-8")

    expected = f"-m screamingface_engine.benchmarks.prepare --root {DEFAULT_BENCHMARK_ASSETS_ROOT}"
    assert expected in body
    # INVARIANT: no family-specific invocation may recreate a second deployment manifest.
    assert _FAMILY_PREPARER.search(body) is None


def test_local_stack_prepare_uses_the_registered_asset_orchestrator() -> None:
    justfile = REPOSITORY_ROOT / "packages" / "screamingface" / "justfile"
    body = justfile.read_text(encoding="utf-8")

    assert "-m screamingface_engine.benchmarks.prepare --root {{assets}}" in body
    assert _FAMILY_PREPARER.search(body) is None


def test_benchmark_image_ci_names_and_caches_the_complete_build() -> None:
    workflow = REPOSITORY_ROOT / ".github" / "workflows" / "screamingface-engine-tests.yml"
    body = workflow.read_text(encoding="utf-8")

    assert "Build the benchmark image" in body
    assert "Build the DRACO benchmark image" not in body
    assert "image: registry:3" in body
    assert "driver-opts: network=host" in body
    assert "cache-from: type=gha,scope=ci-screamingface-engine-benchmark" in body
    assert "cache-to: type=gha,scope=ci-screamingface-engine-benchmark,mode=max" in body
