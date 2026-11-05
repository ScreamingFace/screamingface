"""Engine-side twin of the SDK's pinned-world drift test (OME-1620).

FEATURE: `screamingface up` builds a pip user's Engine environment from
`packages/screamingface/src/screamingface/_runtime/resources/engine-requirements.txt`, an
export of THIS app's lock, so the local Engine runs the deployed Engine's versions.
WHY a twin here: CI is path-filtered. An Engine-only Dependabot bump to `uv.lock` never runs
the SDK lane, so its copy of this test cannot fail when the drift happens; it would fail later,
on an unrelated SDK PR, after a release could ship stale pins (the shape of OME-1421). This copy
runs in the Engine lane, so the PR that moves the lock is the PR that goes red. Like the inspect
pin twin, it reads the SDK's files as text and imports nothing from it: the export flags are
read out of the SDK's export script, so there is one flag list.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

# parents[3] = apps/, so its parent is the monorepo root
_REPO_ROOT: Path = Path(__file__).resolve().parents[3].parent
_ENGINE_APP: Path = _REPO_ROOT / "apps" / "screamingface-engine"
_SDK_PACKAGE: Path = _REPO_ROOT / "packages" / "screamingface"
_PINS: Path = _SDK_PACKAGE / "src" / "screamingface" / "_runtime" / "resources"
_PINS = _PINS / "engine-requirements.txt"
_EXPORTER: Path = _SDK_PACKAGE / "scripts" / "export_engine_requirements.py"


def _export_flags() -> tuple[str, ...]:
    """The `uv` arguments the SDK's export script uses, read from its `_EXPORT` assignment."""

    tree: ast.Module = ast.parse(_EXPORTER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id == "_EXPORT":
            return tuple(ast.literal_eval(value))
    raise AssertionError(f"{_EXPORTER} no longer defines _EXPORT: update this twin")


def _pins(text: str) -> set[str]:
    """One requirement per line, whitespace removed, comments and blanks dropped.

    WHY a set and not the bytes: a uv release that reorders or re-spaces its export must not
    fail an unrelated PR; only a changed pin may.
    """

    return {
        "".join(line.split())
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_the_sdks_pinned_world_equals_this_apps_lock() -> None:
    uv: str | None = shutil.which("uv")
    assert uv is not None, "uv is the only reader of this app's lock; install it"
    exported: str = subprocess.run(
        [uv, *_export_flags()], cwd=_ENGINE_APP, capture_output=True, text=True, check=True
    ).stdout

    committed: set[str] = _pins(_PINS.read_text(encoding="utf-8"))
    fresh: set[str] = _pins(exported)

    assert committed == fresh, (
        "the SDK's engine-requirements.txt no longer matches this app's lock; run "
        "`uv run python scripts/export_engine_requirements.py` in packages/screamingface "
        f"(only in the SDK copy: {sorted(committed - fresh)[:5]}; "
        f"only in the lock: {sorted(fresh - committed)[:5]})"
    )
    assert any(pin.startswith("inspect-ai==") for pin in committed)
