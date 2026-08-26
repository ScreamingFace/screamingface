"""Runtime-source resolution: live checkout vs installed package (OME-1001).

FEATURE: `screamingface up` is the one stack command for devs and users. Inside the
real ScreamingFace monorepo it must serve the live `apps/` + `packages/url4` code;
anywhere else it must serve the installed (bundled) package. These tests pin the
detection rules, the forcing environment variable, and the sys.path/PYTHONPATH
activation that makes the live code win over the build-time copies.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from screamingface._runtime import source

# INVARIANT: detection matches the real ScreamingFace repo only — every marker below
# must exist. A pip user with an unrelated `apps/` folder next to site-packages must
# never be routed to "checkout".
_MARKERS = (
    "packages/screamingface/pyproject.toml",
    "apps/aigateway/src/aigateway/__init__.py",
    "apps/scoreboard/src/scoreboard/__init__.py",
    "apps/screamingface-engine/src/screamingface_engine/__init__.py",
    "apps/screamingface-engine/url4.toml",
    "packages/url4/src/url4/__init__.py",
)


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / "monorepo"
    for marker in _MARKERS:
        file = root / marker
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    return root


def _anchor(root: Path) -> Path:
    """Where `source.py` itself lives when the SDK runs from the checkout."""

    return root / "packages/screamingface/src/screamingface/_runtime/source.py"


def test_a_full_marker_set_resolves_to_the_live_checkout(tmp_path: Path) -> None:
    root = _checkout(tmp_path)

    resolved = source.resolve_source({}, anchor=_anchor(root))

    assert resolved.mode == source.MODE_CHECKOUT
    assert resolved.root == root
    assert str(root) in resolved.describe()


@pytest.mark.parametrize("missing", _MARKERS)
def test_any_missing_repo_marker_means_the_installed_package(tmp_path: Path, missing: str) -> None:
    root = _checkout(tmp_path)
    (root / missing).unlink()

    resolved = source.resolve_source({}, anchor=_anchor(root))

    assert resolved.mode == source.MODE_BUNDLED
    assert resolved.root is None
    assert resolved.describe() == "bundled"


def test_a_shallow_install_location_is_not_a_checkout() -> None:
    # A wheel installed near the filesystem root has too few parent directories to
    # even name a candidate checkout; that must resolve to bundled, not crash.
    resolved = source.resolve_source({}, anchor=Path("/source.py"))

    assert resolved.mode == source.MODE_BUNDLED


def test_the_environment_variable_forces_each_mode(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    anchor = _anchor(root)

    forced_bundled = source.resolve_source(
        {source.SOURCE_ENVIRONMENT_VARIABLE: "bundled"}, anchor=anchor
    )
    forced_checkout = source.resolve_source(
        {source.SOURCE_ENVIRONMENT_VARIABLE: "checkout"}, anchor=anchor
    )

    assert forced_bundled.mode == source.MODE_BUNDLED
    assert forced_checkout.mode == source.MODE_CHECKOUT
    assert forced_checkout.root == root


def test_forcing_checkout_outside_a_checkout_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="checkout"):
        source.resolve_source(
            {source.SOURCE_ENVIRONMENT_VARIABLE: "checkout"},
            anchor=tmp_path / "site-packages/screamingface/_runtime/source.py",
        )


def test_an_unknown_source_value_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="SCREAMINGFACE_RUNTIME_SOURCE"):
        source.resolve_source(
            {source.SOURCE_ENVIRONMENT_VARIABLE: "editable"}, anchor=_anchor(_checkout(tmp_path))
        )


def test_activation_prepends_the_live_source_directories_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _checkout(tmp_path)
    resolved = source.resolve_source({}, anchor=_anchor(root))
    monkeypatch.setattr(sys, "path", ["kept-first"])

    source.activate(resolved)
    source.activate(resolved)

    expected = [
        str(root / "apps/aigateway/src"),
        str(root / "apps/scoreboard/src"),
        str(root / "apps/screamingface-engine/src"),
        str(root / "packages/url4/src"),
    ]
    # INVARIANT: live checkout code must shadow any stale build-time copy already
    # installed in site-packages, and repeat activation must not stack duplicates.
    assert sys.path[: len(expected)] == expected
    assert sys.path[len(expected) :] == ["kept-first"]


def test_activation_promotes_a_source_directory_stuck_behind_site_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: an editable install (e.g. url4's .pth) can put a source dir on sys.path
    # ALREADY — but after site-packages, where the stale vendored copy still wins.
    # Presence is not precedence; activation must move it to the front.
    root = _checkout(tmp_path)
    resolved = source.resolve_source({}, anchor=_anchor(root))
    stuck = str(root / "packages/url4/src")
    monkeypatch.setattr(sys, "path", ["site-packages", stuck])

    source.activate(resolved)

    assert sys.path.index(stuck) < sys.path.index("site-packages")
    assert sys.path.count(stuck) == 1


def test_live_module_verification_names_the_stale_import(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    resolved = source.resolve_source({}, anchor=_anchor(root))
    live = types.ModuleType("aigateway")
    live.__file__ = str(root / "apps/aigateway/src/aigateway/__init__.py")
    stale = types.ModuleType("url4")
    stale.__file__ = "/venv/site-packages/url4/__init__.py"

    source.verify_live_modules(resolved, {"aigateway": live})

    # INVARIANT: "runtime source: checkout" in the boot log must be TRUE — a stale
    # site-packages copy slipping through activation fails loudly, by module name.
    with pytest.raises(RuntimeError, match="url4"):
        source.verify_live_modules(resolved, {"aigateway": live, "url4": stale})


def test_live_module_verification_is_a_no_op_for_the_installed_package() -> None:
    stale = types.ModuleType("url4")
    stale.__file__ = "/venv/site-packages/url4/__init__.py"

    source.verify_live_modules(
        source.RuntimeSource(mode=source.MODE_BUNDLED, root=None), {"url4": stale}
    )


def test_bundled_activation_leaves_the_import_path_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "path", ["kept-first"])

    source.activate(source.RuntimeSource(mode=source.MODE_BUNDLED, root=None))

    assert sys.path == ["kept-first"]


def test_child_environment_carries_the_live_sources_on_pythonpath(tmp_path: Path) -> None:
    root = _checkout(tmp_path)
    resolved = source.resolve_source({}, anchor=_anchor(root))

    fresh = source.child_environment(resolved, {"HOME": "/home/dev"})
    extended = source.child_environment(resolved, {"PYTHONPATH": "/existing"})

    prefix = os.pathsep.join(
        (
            str(root / "apps/aigateway/src"),
            str(root / "apps/scoreboard/src"),
            str(root / "apps/screamingface-engine/src"),
            str(root / "packages/url4/src"),
        )
    )
    assert fresh["PYTHONPATH"] == prefix
    assert fresh["HOME"] == "/home/dev"
    # WHY: a caller's own PYTHONPATH stays reachable — appended, never replaced.
    assert extended["PYTHONPATH"] == f"{prefix}{os.pathsep}/existing"


def test_child_environment_is_untouched_for_the_installed_package() -> None:
    environment = {"PYTHONPATH": "/existing"}

    passed = source.child_environment(
        source.RuntimeSource(mode=source.MODE_BUNDLED, root=None), environment
    )

    assert passed == environment


def test_the_state_record_names_the_owning_source(tmp_path: Path) -> None:
    root = _checkout(tmp_path)

    checkout_record = source.state_record(source.resolve_source({}, anchor=_anchor(root)))
    bundled_record = source.state_record(source.RuntimeSource(mode=source.MODE_BUNDLED, root=None))

    # INVARIANT: the record is what `screamingface up` compares before adopting a
    # running stack — it must distinguish two checkouts by their real paths.
    assert checkout_record == {"mode": "checkout", "root": str(root)}
    assert bundled_record == {"mode": "bundled", "root": None}
