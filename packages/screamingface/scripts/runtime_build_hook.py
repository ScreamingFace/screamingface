"""Include the local runtime applications in both the sdist and wheel.

An editable install inside the monorepo is the exception: it points at the live sources
instead of copying them, because a copy is frozen at build time and shadows the checkout.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# INVARIANT: the same directories, in the same order, as `_SOURCE_DIRECTORIES` in
# src/screamingface/_runtime/source.py (tests/test_runtime_build_hook.py pins it). This
# script runs in an isolated build env where the SDK itself is not importable.
_LIVE_SOURCE_DIRECTORIES = (
    Path("apps") / "aigateway" / "src",
    Path("apps") / "scoreboard" / "src",
    Path("apps") / "screamingface-engine" / "src",
    Path("packages") / "url4" / "src",
)
_LIVE_SOURCES_PTH = "_screamingface_runtime_sources.pth"


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        root = Path(self.root)
        if version == "editable" and (root.parents[1] / "apps").is_dir():
            self._point_at_live_sources(root.parents[1], build_data)
        else:
            self._vendor_runtime(root, build_data)

    def _vendor_runtime(self, root: Path, build_data: dict[str, object]) -> None:
        """Copy url4 and the three apps into the wheel (or the sdist's runtime-vendor/)."""

        checkout_apps = root.parents[1] / "apps"
        if checkout_apps.is_dir():
            apps = checkout_apps
            url4 = root.parent / "url4" / "src" / "url4"
        else:
            apps = root / "runtime-vendor"
            url4 = root / "runtime-vendor" / "url4" / "src" / "url4"
        sources = (
            (apps / "aigateway" / "src" / "aigateway", "aigateway", "aigateway/src/aigateway"),
            (apps / "scoreboard" / "src" / "scoreboard", "scoreboard", "scoreboard/src/scoreboard"),
            (
                apps / "scoreboard" / "portal",
                "screamingface/_runtime/scoreboard_portal",
                "scoreboard/portal",
            ),
            (
                apps / "scoreboard" / "artifacts",
                "screamingface/_runtime/scoreboard_artifacts",
                "scoreboard/artifacts",
            ),
            (
                apps / "screamingface-engine" / "src" / "screamingface_engine",
                "screamingface_engine",
                "screamingface-engine/src/screamingface_engine",
            ),
            (
                apps / "screamingface-engine" / "url4.toml",
                "screamingface/_runtime/resources/url4.toml",
                "screamingface-engine/url4.toml",
            ),
            (url4, "url4", "url4/src/url4"),
        )
        missing = [str(path) for path, _, _ in sources if not path.exists()]
        if missing:
            raise RuntimeError(f"runtime distribution sources are missing: {missing}")

        force_include = build_data.setdefault("force_include", {})
        if not isinstance(force_include, dict):
            raise RuntimeError("Hatch force_include build data has an unexpected type")
        if self.target_name == "sdist":
            for source, _, vendor_destination in sources:
                force_include[str(source)] = str(Path("runtime-vendor") / vendor_destination)
        else:
            force_include.update({str(source): destination for source, destination, _ in sources})

    def finalize(self, version: str, build_data: dict[str, object], artifact_path: str) -> None:
        staging = getattr(self, "_pth_staging", None)
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)

    def _point_at_live_sources(self, checkout: Path, build_data: dict[str, object]) -> None:
        """Ship a .pth naming the live source dirs, so a dev venv never holds a stale copy.

        WHY (2026-09-25): `import screamingface` imports url4 before checkout activation
        runs, so a copy vendored into a dev venv on Sep 18 kept serving after url4 gained
        `url4.cli._config` on Sep 22, and `screamingface up` crashed at boot.

        WHY `force_include_editable`: when it is non-empty hatchling ships ONLY it in the
        editable wheel, instead of the regular force-include map. The runtime resources
        (url4.toml, the scoreboard portal) need no copy: `_runtime/config.py` already
        falls back to the checkout.
        """

        staging = Path(tempfile.mkdtemp(prefix="screamingface-editable-"))
        self._pth_staging = staging
        pth = staging / _LIVE_SOURCES_PTH
        pth.write_text(
            "".join(f"{checkout / directory}\n" for directory in _LIVE_SOURCE_DIRECTORIES),
            encoding="utf-8",
        )
        build_data["force_include_editable"] = {str(pth): _LIVE_SOURCES_PTH}
