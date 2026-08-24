"""One deployment declaration drives runtime discovery and image asset preparation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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
    BenchmarkAssetPreparerContractError,
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

# WHY resolved + checked: these three guards read files OUTSIDE this app (the SDK justfile and
# the workflow). `packages/screamingface/justfile` itself supports pointing at a separate engine
# checkout via `SCREAMINGFACE_ENGINE_REPO`, so that split is anticipated, not hypothetical. In it
# the monorepo siblings are simply absent, and a guard that cannot see its subject must say so
# rather than fail as if the subject were wrong.
REPOSITORY_ROOT = Path(__file__).parents[4].resolve()
BENCHMARKS_PACKAGE = Path(__file__).parents[2] / "src" / "screamingface_engine" / "benchmarks"
# INVARIANT: the family segment is derived from the family packages that exist on disk, so the
# guard matches only what its failure message claims — a family-specific invocation. A bare
# `[a-z0-9_]+` also matched `benchmarks.deployment.prepare_assets`, blaming the orchestrator.
# WHY not bundle ids: this guard matches module paths, and the codebase already separates the
# two (`draco-3pass` is a benchmark id over the `draco` bundle). A family that renamed its
# bundle id away from its package name would silently stop being guarded at all.
FAMILY_PACKAGES = tuple(
    sorted(path.parent.name for path in BENCHMARKS_PACKAGE.glob("*/prepare.py"))
)
# WHY the two non-literal branches: reintroduction does not have to spell a family out. The
# SDK already builds this exact path from a variable (`_runtime/cli.py`), and a shell loop
# (`for b in draco ifeval healthbench`) is the natural way back into a Dockerfile or justfile.
# A guard that only matches literals would pass green on precisely the shapes most likely to
# return, so a computed family segment counts as a family-specific invocation too.
_COMPUTED_FAMILY = r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\{[A-Za-z_][A-Za-z0-9_]*\}"
_FAMILY_PREPARER = re.compile(
    r"screamingface_engine\.benchmarks\.(?:"
    + "|".join(re.escape(family) for family in FAMILY_PACKAGES)
    + "|"
    + _COMPUTED_FAMILY
    + r")\.prepare\b"
)


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
        "healthbench": {"professional_cases": 525, "declared_worst30_cases": 157},
        "ifeval": {"cases": 541, "patched_keys": [146, 179]},
    }

    def prepare(_root: Path, on_prepared: object = None) -> dict[str, object]:
        for bundle, summary in summaries.items():
            if on_prepared is not None:
                on_prepared(bundle, summary)  # type: ignore[operator]
        return summaries

    monkeypatch.setattr(prepare_module, "prepare_builtin_assets", prepare)

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
    def refuse(_root: Path, _on_prepared: object = None) -> dict[str, object]:
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
    def explode(_root: Path, _on_prepared: object = None) -> dict[str, object]:
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
        "gdpval-text": "gdpval",
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
    if not justfile.is_file():
        pytest.skip("engine checked out apart from the monorepo; the SDK justfile is absent")
    body = justfile.read_text(encoding="utf-8")

    assert "-m screamingface_engine.benchmarks.prepare --root {{assets}}" in body
    assert _FAMILY_PREPARER.search(body) is None


def test_benchmark_image_ci_names_the_complete_build() -> None:
    workflow = REPOSITORY_ROOT / ".github" / "workflows" / "screamingface-engine-tests.yml"
    if not workflow.is_file():
        pytest.skip("engine checked out apart from the monorepo; the workflow is absent")
    body = workflow.read_text(encoding="utf-8")

    assert "Build the benchmark image" in body
    assert "Build the DRACO benchmark image" not in body


def test_a_refusal_still_reports_the_bundles_that_already_completed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: evidence for a completed bake survives a later bundle's refusal.

    WHY: bundles bake in ID order and write real files as they go. Printing only after the
    whole sequence succeeds means an operator reading the build log cannot tell which
    bundles landed — losing exactly the audit trail this unit exists to provide.
    """

    def good(out: Path) -> dict[str, object]:
        return {"cases": 100, "out": str(out)}

    def refuse(_out: Path) -> dict[str, object]:
        raise BenchmarkAssetPreparationError("frozen answer key drifted")

    deployment = BenchmarkDeployment(
        (
            BenchmarkRegistration(
                _benchmark("one"), asset_bundle=BenchmarkAssetBundle(id="alpha", prepare=good)
            ),
            BenchmarkRegistration(
                _benchmark("two"), asset_bundle=BenchmarkAssetBundle(id="beta", prepare=refuse)
            ),
        )
    )
    monkeypatch.setattr(prepare_module, "prepare_builtin_assets", deployment.prepare_assets)

    assert prepare_module.main(["--root", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines() if line.strip()]
    assert records == [
        {
            "root": str(tmp_path),
            "bundle": "alpha",
            "summary": {"cases": 100, "out": str(tmp_path / "alpha")},
        }
    ]
    assert captured.err == "benchmark asset preparation failed: frozen answer key drifted\n"


def test_the_family_guard_does_not_flag_the_orchestrator_itself() -> None:
    """WHY: the guard's message blames a family-specific invocation, so it must only match one."""

    assert _FAMILY_PREPARER.search("-m screamingface_engine.benchmarks.prepare --root /x") is None
    assert (
        _FAMILY_PREPARER.search("screamingface_engine.benchmarks.deployment.prepare_assets(root)")
        is None
    )
    assert (
        _FAMILY_PREPARER.search("screamingface_engine.benchmarks.registry.prepare_everything()")
        is None
    )
    assert _FAMILY_PREPARER.search("-m screamingface_engine.benchmarks.draco.prepare --out /x")


def test_the_family_guard_covers_every_family_preparer_package() -> None:
    """WHY: a guard derived from a mistyped path would match nothing and pass in silence."""

    assert set(FAMILY_PACKAGES) == {"draco", "healthbench", "ifeval"}
    for family in FAMILY_PACKAGES:
        assert _FAMILY_PREPARER.search(f"-m screamingface_engine.benchmarks.{family}.prepare")


def _stale_preparer_deployment() -> BenchmarkDeployment:
    def stale(_out: Path) -> None:
        return None

    return BenchmarkDeployment(
        (
            BenchmarkRegistration(
                _benchmark("one"),
                asset_bundle=BenchmarkAssetBundle(id="alpha", prepare=stale),  # type: ignore[arg-type]
            ),
        )
    )


def test_a_preparer_ignoring_the_summary_contract_fails_by_name(tmp_path: Path) -> None:
    """WHY: a preparer still written against the old `-> None` port should say so by name.

    INVARIANT: it is a *defect*, not an operator refusal, so it must not be a
    `BenchmarkAssetPreparationError` — that class is the CLI's exit-1 channel for dataset and
    answer-key drift, and a wrongly-typed preparer sends an operator hunting for drift that
    does not exist.
    """

    with pytest.raises(BenchmarkAssetPreparerContractError, match="summary mapping"):
        _stale_preparer_deployment().prepare_assets(tmp_path)

    assert not issubclass(BenchmarkAssetPreparerContractError, BenchmarkAssetPreparationError)


def test_a_preparer_contract_defect_reaches_the_operator_as_a_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: the CLI must not launder a preparer defect into a one-line exit 1."""

    deployment = _stale_preparer_deployment()
    monkeypatch.setattr(prepare_module, "prepare_builtin_assets", deployment.prepare_assets)

    with pytest.raises(BenchmarkAssetPreparerContractError, match="summary mapping"):
        prepare_module.main(["--root", str(tmp_path)])


def test_the_engine_workflow_runs_when_the_guarded_justfile_changes() -> None:
    """INVARIANT: a guard that cannot run on its own subject is worse than no guard."""

    workflow = REPOSITORY_ROOT / ".github" / "workflows" / "screamingface-engine-tests.yml"
    if not workflow.is_file():
        pytest.skip("engine checked out apart from the monorepo; the workflow is absent")
    body = workflow.read_text(encoding="utf-8")

    assert body.count('- "packages/screamingface/justfile"') == 2


def test_an_unserializable_summary_value_does_not_abort_the_remaining_bundles(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: a fault in the audit record must not stop assets from being prepared.

    WHY: the record is printed from inside the preparation loop, so a `json.dumps` refusal on
    the first bundle's summary would leave every later bundle unbaked — the image would ship
    missing assets because of a *reporting* problem.
    """

    def exotic(out: Path) -> dict[str, object]:
        return {"cases": 1, "out": out}

    def plain(out: Path) -> dict[str, object]:
        return {"cases": 2, "out": str(out)}

    deployment = BenchmarkDeployment(
        (
            BenchmarkRegistration(
                _benchmark("one"), asset_bundle=BenchmarkAssetBundle(id="alpha", prepare=exotic)
            ),
            BenchmarkRegistration(
                _benchmark("two"), asset_bundle=BenchmarkAssetBundle(id="beta", prepare=plain)
            ),
        )
    )
    monkeypatch.setattr(prepare_module, "prepare_builtin_assets", deployment.prepare_assets)

    assert prepare_module.main(["--root", str(tmp_path)]) == 0

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert records == [
        {
            "root": str(tmp_path),
            "bundle": "alpha",
            "summary": {"cases": 1, "out": str(tmp_path / "alpha")},
        },
        {
            "root": str(tmp_path),
            "bundle": "beta",
            "summary": {"cases": 2, "out": str(tmp_path / "beta")},
        },
    ]
    assert (tmp_path / "beta").is_dir()


def test_an_unserializable_summary_key_does_not_abort_the_remaining_bundles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """WHY: `default=` is never consulted for KEYS, so a value-only guard is half a guard."""

    summaries: dict[str, dict[Any, Any]] = {
        "draco": {"cases": 100},
        "healthbench": {Path("professional"): 525},
        "ifeval": {"cases": 541},
    }

    def prepare(_root: Path, on_prepared: object = None) -> dict[str, object]:
        for bundle, summary in summaries.items():
            if on_prepared is not None:
                on_prepared(bundle, summary)  # type: ignore[operator]
        return dict(summaries)

    monkeypatch.setattr(prepare_module, "prepare_builtin_assets", prepare)

    assert prepare_module.main(["--root", str(tmp_path)]) == 0

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [record["bundle"] for record in records] == ["draco", "healthbench", "ifeval"]
    assert records[1]["summary_unreportable"] == "TypeError"
    assert records[2]["summary"] == {"cases": 541}


def test_the_family_guard_matches_a_computed_family_segment() -> None:
    """WHY: reintroduction is likelier as a loop variable than as three literal lines."""

    assert _FAMILY_PREPARER.search("-m screamingface_engine.benchmarks.$b.prepare --out /x")
    assert _FAMILY_PREPARER.search("-m screamingface_engine.benchmarks.${family}.prepare")
    assert _FAMILY_PREPARER.search('f"screamingface_engine.benchmarks.{name}.prepare"')
    # The orchestrator itself still must not match.
    assert _FAMILY_PREPARER.search("-m screamingface_engine.benchmarks.prepare --root /x") is None
