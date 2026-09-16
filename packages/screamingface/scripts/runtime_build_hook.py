"""Include the local runtime applications in both the sdist and wheel."""

from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        root = Path(self.root)
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
                apps / "screamingface-engine" / "url4.json",
                "screamingface/_runtime/resources/url4.json",
                "screamingface-engine/url4.json",
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
