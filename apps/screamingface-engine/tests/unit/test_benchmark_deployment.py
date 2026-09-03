"""One deployment declaration drives runtime discovery and image asset preparation."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType
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
from url4.peer.server import Url4Node

# WHY resolved + checked: the workflow guard reads a file OUTSIDE this app. In a standalone
# engine checkout the monorepo siblings are simply absent, and a guard that cannot see its
# subject must say so rather than fail as if the subject were wrong.
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
# (`for b in draco ifeval healthbench`) is the natural way back into a Dockerfile or script.
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


def test_the_runtime_registry_is_the_deployments_own_registrations() -> None:
    assert BUILTIN_DEPLOYMENT.benchmarks is BUILTIN_BENCHMARKS


def _installer_bundle_id(registration: BenchmarkRegistration) -> str | None:
    """The bundle directory the board's OWN installer reads, or None when it declares none.

    A board's installer is defined in its family module beside that family's
    ``ASSET_BUNDLE_ID`` constant, and reads ``assets_root / ASSET_BUNDLE_ID`` — see
    ``benchmarks/gdpval/exam.py``. So the constant exported next to the installer is the
    directory the board actually opens at runtime, read here from the board itself rather
    than from a second list.
    """

    module = sys.modules.get(registration.benchmark.install.__module__)
    return getattr(module, "ASSET_BUNDLE_ID", None)


def _family_package(registration: BenchmarkRegistration) -> str:
    """The family package a board's installer lives in — ``...benchmarks.<family>.<module>``."""

    return registration.benchmark.install.__module__.split(".")[-2]


@pytest.mark.parametrize(
    "registration",
    BUILTIN_DEPLOYMENT.registrations,
    ids=lambda registration: registration.benchmark.id,
)
def test_every_board_is_registered_against_the_bundle_its_installer_reads(
    registration: BenchmarkRegistration,
) -> None:
    """INVARIANT: the deployment bakes the directory the board goes on to open.

    WHY derived rather than a hand-written board->bundle map (OME-1095): the map had to be
    edited for every new board, and it could only ever restate what the registration already
    says. Registering a board against another family's bundle bakes one directory and reads
    another — the board's assets are simply absent at runtime — and that is what this catches
    for a board nobody has written yet.
    """

    declared = _installer_bundle_id(registration)

    assert declared is not None, (
        f"{registration.benchmark.id} installs from "
        f"{registration.benchmark.install.__module__}, which exports no ASSET_BUNDLE_ID; "
        "a board must name the asset directory it reads next to the installer that reads it"
    )
    assert declared == registration.asset_bundle.id, (
        f"{registration.benchmark.id} is registered against bundle "
        f"{registration.asset_bundle.id!r} but its installer reads {declared!r}"
    )


def test_the_bundle_provenance_check_covers_a_board_the_registry_has_never_seen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deletion test, made measurable: the check is a pure function of a registration.

    A throwaway board declared here — never added to ``BUILTIN_DEPLOYMENT`` — is checked by
    the same function the built-ins go through, which is what "a seventh board extends the
    suite by existing" means in practice.
    """

    family = ModuleType("screamingface_engine.benchmarks.throwaway.exam")
    family.ASSET_BUNDLE_ID = "throwaway"  # type: ignore[attr-defined]

    def install(_node: Url4Node, _assets: Path) -> None:
        """The board's installer, defined in its family module beside the constant above."""

    install.__module__ = family.__name__
    monkeypatch.setitem(sys.modules, family.__name__, family)
    bundle = BenchmarkAssetBundle(id="throwaway", prepare=lambda _out: {})
    board = replace(_benchmark("throwaway-text"), install=install)

    matched = BenchmarkRegistration(board, asset_bundle=bundle)
    assert _installer_bundle_id(matched) == matched.asset_bundle.id
    assert _family_package(matched) == "throwaway"

    borrowed = BenchmarkRegistration(
        board,
        asset_bundle=BenchmarkAssetBundle(id="someone-elses", prepare=lambda _out: {}),
    )
    assert _installer_bundle_id(borrowed) != borrowed.asset_bundle.id


def test_benchmark_image_invokes_only_the_registered_asset_orchestrator() -> None:
    dockerfile = Path(__file__).parents[2] / "Dockerfile.benchmark"
    body = dockerfile.read_text(encoding="utf-8")

    expected = f"-m screamingface_engine.benchmarks.prepare --root {DEFAULT_BENCHMARK_ASSETS_ROOT}"
    assert expected in body
    # INVARIANT: no family-specific invocation may recreate a second deployment manifest.
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
    """WHY: a guard derived from a mistyped path would match nothing and pass in silence.

    Both sides are derived (OME-1095): the families found on disk must be exactly the
    families the registered boards install from, so a preparer package nobody deploys — or a
    deployed family whose preparer vanished — fails here instead of going unguarded.
    """

    assert FAMILY_PACKAGES
    assert set(FAMILY_PACKAGES) == {
        _family_package(registration) for registration in BUILTIN_DEPLOYMENT.registrations
    }
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
