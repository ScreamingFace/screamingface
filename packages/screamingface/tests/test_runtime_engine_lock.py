"""The Engine's pinned world comes from its lock, at the moment it is needed (OME-1620).

There is no committed copy to go stale: a release wheel gets the pins from the Engine's
`uv.lock` when it is BUILT, and a checkout reads them from the same lock when `up` builds its
Engine environment. These tests pin the one export both paths call, what the wheel ends up
carrying, and which copy the runtime prefers.
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest
from hatchling.build import build_wheel

from screamingface._runtime import engine_env, engine_lock

PACKAGE_ROOT: Path = Path(__file__).resolve().parents[1]
CHECKOUT_ROOT: Path = PACKAGE_ROOT.parents[1]
ENGINE_APP: Path = CHECKOUT_ROOT / engine_lock.ENGINE_APP


def _pins(text: str) -> set[str]:
    """One requirement per line, whitespace removed, comments and blanks dropped."""
    return {
        "".join(line.split())
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_the_export_asks_uv_for_the_engines_benchmarks_world(tmp_path: Path) -> None:
    ran: list[tuple[list[str], object]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        ran.append((command, kwargs.get("cwd")))
        return subprocess.CompletedProcess(command, 0, stdout="inspect-ai==0.3.263\n", stderr="")

    text = engine_lock.export_engine_requirements(
        tmp_path, which=lambda name: "/bin/uv" if name == "uv" else None, run=run
    )

    assert text == "inspect-ai==0.3.263\n"
    command, cwd = ran[0]
    assert command[0] == "/bin/uv" and command[1] == "export"
    # The benchmarks extra (a superset of inspect), from the lock as it is, without the two
    # projects the environment installs from its own copies.
    for flag in ("--frozen", "--no-dev", "--no-emit-project", "--no-hashes"):
        assert flag in command
    assert command[command.index("--extra") + 1] == "benchmarks"
    assert command[command.index("--no-emit-package") + 1] == "url4"
    assert cwd == tmp_path


def test_the_export_says_uv_is_needed_when_it_is_missing(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="needs uv"):
        engine_lock.export_engine_requirements(tmp_path, which=lambda _: None)


def test_a_failed_export_carries_uvs_reason(tmp_path: Path) -> None:
    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="error: lock is stale")

    with pytest.raises(RuntimeError, match="lock is stale"):
        engine_lock.export_engine_requirements(tmp_path, which=lambda _: "/bin/uv", run=run)


def test_a_release_wheel_carries_exactly_the_locks_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: the pins a pip user installs ARE the Engine lock's, as of the wheel build.

    The deployed Engine image is built from the same `uv.lock`, so this is what makes the local
    Engine run the deployed Engine's versions, with nothing committed that could drift.
    """
    monkeypatch.chdir(PACKAGE_ROOT)
    wheel: str = build_wheel(str(tmp_path))
    with zipfile.ZipFile(tmp_path / wheel) as archive:
        shipped: str = archive.read(
            f"screamingface/_runtime/resources/{engine_lock.REQUIREMENTS_NAME}"
        ).decode("utf-8")

    assert _pins(shipped) == _pins(engine_lock.export_engine_requirements(ENGINE_APP))
    assert any(pin.startswith("inspect-ai==") for pin in _pins(shipped))


def test_the_runtime_prefers_the_wheels_copy_over_a_live_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shipped = tmp_path / engine_lock.REQUIREMENTS_NAME
    shipped.write_text("inspect-ai==0.0.1\n")
    monkeypatch.setattr(engine_env, "_vendored_requirements", lambda: shipped)
    monkeypatch.setattr(
        engine_env, "_exported_requirements", lambda _app: pytest.fail("exported anyway")
    )

    assert engine_env._requirements_text() == "inspect-ai==0.0.1\n"


def test_a_checkout_reads_the_pins_from_its_own_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    # STORY: a dev bumps the Engine's lock and runs `up`; nothing to regenerate by hand.
    monkeypatch.setattr(engine_env, "_vendored_requirements", lambda: None)
    exported: list[Path] = []

    def export(app: Path) -> str:
        exported.append(app)
        return "inspect-ai==0.3.263\n"

    monkeypatch.setattr(engine_env, "_exported_requirements", export)

    assert engine_env._requirements_text() == "inspect-ai==0.3.263\n"
    assert exported == [ENGINE_APP]
