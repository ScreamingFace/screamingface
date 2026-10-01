from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# INVARIANT: the one name for the supervisor's state record — `screamingface up` writes
# it, `screamingface status` and default-client discovery (detect.py) read it.
STATE_FILENAME = "runtime.json"

# INVARIANT: the Engine's own name for its spill folder (`screamingface_engine.job_env.
# ARTIFACTS_DIR`), spelled here so this module stays importable without the runtime extra.
# `tests/test_runtime_artifacts_dir.py` pins the two names equal.
ARTIFACTS_DIR_ENV = "URL4_CLOUD_ARTIFACTS_DIR"


def default_data_dir() -> Path:
    configured = os.getenv("SCREAMINGFACE_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".screamingface").resolve()


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    data_dir: Path
    runner_config: Path | None = None
    gateway_port: int = 9105
    scoreboard_port: int = 9106
    engine_port: int = 9108

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", self.data_dir.expanduser().resolve())
        selected = self.runner_config or bundled_runner_config()
        object.__setattr__(self, "runner_config", selected.expanduser().resolve())
        ports = (self.gateway_port, self.scoreboard_port, self.engine_port)
        if any(isinstance(port, bool) or not 1 <= port <= 65535 for port in ports):
            raise ValueError("runtime ports must be integers from 1 to 65535")
        if len(set(ports)) != len(ports):
            raise ValueError("gateway, scoreboard, and engine ports must be unique")

    @property
    def services(self) -> dict[str, str]:
        return {
            "gateway": f"http://127.0.0.1:{self.gateway_port}",
            "scoreboard": f"http://127.0.0.1:{self.scoreboard_port}",
            "engine": f"http://127.0.0.1:{self.engine_port}",
        }

    @property
    def gateway_database_url(self) -> str:
        return f"sqlite://{self.data_dir / 'aigateway.sqlite3'}"

    @property
    def scoreboard_database_url(self) -> str:
        return f"sqlite://{self.data_dir / 'scoreboard.sqlite3'}"

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "benchmark-assets"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    def artifacts_override(self, environ: Mapping[str, str]) -> Path | None:
        """The folder the user chose for spilled results, or None when unset.

        WHY a blank value is unset: the Engine reads it that way (its `artifacts_dir`
        validator), so this must too, or the two sides would disagree.
        """
        value = environ.get(ARTIFACTS_DIR_ENV, "").strip()
        return Path(value) if value else None

    def effective_artifacts_dir(self, environ: Mapping[str, str]) -> Path:
        """The one folder the local Engine spills into: the user's choice, else the default."""
        return self.artifacts_override(environ) or self.artifacts_dir

    @property
    def state_path(self) -> Path:
        return self.data_dir / STATE_FILENAME

    @property
    def log_path(self) -> Path:
        return self.data_dir / "runtime.log"


def bundled_runner_config() -> Path:
    from importlib.resources import files

    resource = files("screamingface._runtime.resources").joinpath("url4.toml")
    path = Path(str(resource)).resolve()
    if path.is_file():
        return path
    checkout = Path(__file__).resolve().parents[5] / "apps" / "screamingface-engine" / "url4.toml"
    if checkout.is_file():
        return checkout
    raise FileNotFoundError(f"bundled URL4 runner config not found: {path}")


def scoreboard_assets() -> tuple[Path, Path]:
    from importlib.resources import files

    root = files("screamingface._runtime")
    portal = Path(str(root / "scoreboard_portal"))
    artifacts = Path(str(root / "scoreboard_artifacts"))
    if portal.is_dir() and artifacts.is_dir():
        return portal, artifacts
    checkout = Path(__file__).resolve().parents[5] / "apps" / "scoreboard"
    portal, artifacts = checkout / "portal", checkout / "artifacts"
    if portal.is_dir() and artifacts.is_dir():
        return portal, artifacts
    raise FileNotFoundError("bundled Scoreboard portal assets were not found")
