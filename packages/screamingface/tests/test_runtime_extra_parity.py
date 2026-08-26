"""The [runtime] extra must declare what the bundled apps need.

Mental model: the wheel smuggles three whole applications (gateway, scoreboard,
engine) into `screamingface/_runtime`, but pip never reads THEIR pyprojects —
it only resolves the client's `[runtime]` extra. So the extra is a hand-written
mirror of the apps' direct dependencies, and any drift ships a broken install.

Worked example (GitHub #735): the gateway declares `python-multipart>=0.0.20`
for its FastAPI form endpoints. The extra didn't mirror it, so a fresh
`pip install "screamingface[runtime]"` + `screamingface up` died at startup
with `Form data requires "python-multipart" to be installed`. This test turns
that bug class into a red gate at PR time.

Stage 1 — read the client's pyproject: base deps + the [runtime] extra.
Stage 2 — read each bundled app's pyproject: its direct `dependencies`.
Stage 3 — every app dependency name must be covered by the client's names,
unless it is on an explicit, commented allowlist (satisfied transitively, or
vendored inside the wheel itself).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

# WHY: mirrors scripts/runtime_build_hook.py — the same three apps it bundles
# into the wheel are the ones whose dependencies the extra must cover.
BUNDLED_APPS = ("aigateway", "scoreboard", "screamingface-engine")

# INVARIANT: every name here must state HOW it is satisfied without being in
# the extra — an entry without a reason is drift waiting to happen.
SATISFIED_TRANSITIVELY = {
    "pydantic",  # pulled by fastapi and pydantic-settings, both in the extra
    "asyncpg",  # pulled by the extra's tortoise-orm[asyncpg]
}
VENDORED_IN_WHEEL = {
    "url4",  # runtime_build_hook copies the url4 sources into the wheel itself
}


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(requirement: str) -> str:
    # Dep strings here are simple ("name[extra]>=1.2"); cut at the first
    # character that can't be part of a distribution name.
    match = re.match(r"[A-Za-z0-9._-]+", requirement.strip())
    assert match is not None, f"unparseable requirement: {requirement!r}"
    return _canonical(match.group(0))


def _project_dependencies(pyproject: Path) -> list[str]:
    with pyproject.open("rb") as handle:
        return tomllib.load(handle)["project"]["dependencies"]


def test_runtime_extra_covers_every_bundled_app_dependency() -> None:
    apps_dir = PACKAGE_ROOT.parents[1] / "apps"
    if not apps_dir.is_dir():
        # AIDEV-NOTE: sdists vendor only the apps' sources, not their
        # pyprojects — this parity check is meaningful only in the checkout.
        pytest.skip("bundled apps' pyprojects are only present in the monorepo checkout")

    client = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())
    provided = {
        _requirement_name(requirement)
        for requirement in (
            *client["project"]["dependencies"],
            *client["project"]["optional-dependencies"]["runtime"],
        )
    }
    allowed = provided | SATISFIED_TRANSITIVELY | VENDORED_IN_WHEEL

    missing: dict[str, list[str]] = {}
    for app in BUNDLED_APPS:
        for requirement in _project_dependencies(apps_dir / app / "pyproject.toml"):
            if _requirement_name(requirement) not in allowed:
                missing.setdefault(app, []).append(requirement)

    assert not missing, (
        "bundled apps declare dependencies the [runtime] extra does not provide "
        f"(a fresh `pip install screamingface[runtime]` will break): {missing}"
    )
