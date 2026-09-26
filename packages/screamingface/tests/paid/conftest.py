"""Gating + real-key stack boot for the OME-1275 paid smoke lane.

Mental model: this is the e2e replay harness's paid sibling. The replay harness
(`tests/e2e/harness/`) makes spend IMPOSSIBLE by construction — scrubbed child
environments, zero provider keys — and must stay that way. This lane is the one
place that does the opposite ON PURPOSE: it boots the same real stack (Postgres +
aigateway + engine) and then hands the gateway a real OpenRouter key, so every
imported board can prove its full product pipe with actual model calls.

Stages of the session boot, in execution order:

1. **Gate** — `SCREAMINGFACE_TEST_PAID=1` + `OPENROUTER_API_KEY` + a live Docker
   daemon, or every test here SKIPS loudly with the exact reason. Spend stays opt-in.
2. **Postgres + migrations** — the gateway's own Tortoise migrate, same invocation as
   the replay harness and the Helm migrate job.
3. **Gateway** — the REAL app (`aigateway.main:app`, not the replay lane's test-only
   discovery wrapper), auth disabled (loopback anonymous mode), openrouter plugin ON,
   discovery ON (live datasheets are the production posture this lane smokes).
4. **Engine** — synced WITH `--extra benchmarks`: the imported boards only register
   when `inspect_ai`/`inspect_evals` import, and the extra is uncoinstallable with the
   SDK's runtime extra, so the engine must run from its own venv. Prepared benchmark
   assets are required (skip tells you how to prepare them).
5. **Key** — the SDK's own `client.connect("openrouter", api_key=...)` path, i.e. the
   exact route a user takes; the gateway validates the key live and stores it
   encrypted. Failure here fails the boot, not the per-board tests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

import pytest

# The replay harness's subprocess plumbing is deliberately reused (venv-per-app boot,
# health-checked children, scrubbed base env); only the ENV CONTENTS differ here.
_E2E_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "e2e"
if str(_E2E_DIR) not in sys.path:
    sys.path.insert(0, str(_E2E_DIR))

from harness._local_proc import (  # noqa: E402
    ManagedProcess,
    clean_env,
    free_port,
    repo_root,
    venv_bin,
)

PAID_ENV: Final = "SCREAMINGFACE_TEST_PAID"
KEY_ENV: Final = "OPENROUTER_API_KEY"
_ASSETS_ENV: Final = "SCREAMINGFACE_E2E_ASSETS"
# INVARIANT (PR #1035 review): set ONLY by the just recipe and the workflow — the two
# "paid button" surfaces. There, an unavailable stack must FAIL the run: a pytest skip
# exits 0, so without this flag a broken gate or empty assets would show the owner a
# green run that re-proved nothing. Plain `pytest tests/paid` keeps skipping politely.
REQUIRED_ENV: Final = "SCREAMINGFACE_PAID_REQUIRED"
# Where child logs (aigateway.log, engine.log) land. The workflow pins this to a fixed
# path and uploads it with if:always(), so a failed CI run's stack logs outlive the
# runner — a pytest tmp dir dies with it, and the failure code alone rarely debugs a
# mid-run 500.
LOG_DIR_ENV: Final = "SCREAMINGFACE_PAID_LOG_DIR"


def work_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The stack's log directory: the pinned CI path when set, else a session tmp dir."""
    configured: str | None = os.environ.get(LOG_DIR_ENV)
    if configured:
        pinned = Path(configured)
        pinned.mkdir(parents=True, exist_ok=True)
        return pinned
    return tmp_path_factory.mktemp("paid-stack")


def _refuse(reason: str) -> None:
    """Skip in ordinary runs; FAIL when the paid button was pressed (REQUIRED set)."""
    if os.environ.get(REQUIRED_ENV) == "1":
        pytest.fail(f"paid smoke was REQUIRED but cannot run: {reason}", pytrace=False)
    pytest.skip(f"paid smoke stack unavailable: {reason}")


def paid_unavailable_reason() -> str | None:
    """Why the paid stack cannot run here, or ``None`` when it can."""
    reason: str | None = None
    if os.environ.get(PAID_ENV) != "1":
        reason = f"{PAID_ENV}=1 not set (the paid smoke lane spends real money and is opt-in)"
    elif not os.environ.get(KEY_ENV):
        reason = f"{KEY_ENV} not set (the lane needs a real OpenRouter key to smoke the boards)"
    elif shutil.which("docker") is None:
        reason = "docker CLI not on PATH (Postgres testcontainer needs it)"
    elif subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        reason = "docker daemon unreachable (Postgres testcontainer needs it)"
    return reason


def require_paid_stack() -> None:
    """Skip (or FAIL under the button flag) — loudly, with the reason — when the
    paid stack cannot run here."""
    reason: str | None = paid_unavailable_reason()
    if reason is not None:
        _refuse(reason)


def assets_root() -> Path:
    """Where prepared benchmark assets live — same resolution as the e2e lane."""
    configured: str | None = os.environ.get(_ASSETS_ENV)
    if configured:
        return Path(configured)
    from screamingface._runtime.config import default_data_dir

    return default_data_dir() / "benchmark-assets"


def _require_imported_assets() -> Path:
    """The assets root with at least one prepared imported bundle — or a loud skip."""
    root: Path = assets_root()
    has_imported: bool = root.is_dir() and any(root.glob("inspect-*/cases.json"))
    if not has_imported:
        _refuse(
            f"no prepared imported-board assets under {root} — run "
            f"`just screamingface test-paid-inspect` (it prepares them), or point "
            f"{_ASSETS_ENV} at a prepared root"
        )
    return root


@dataclass(frozen=True, slots=True)
class PaidStack:
    """The two URLs a smoke test needs, plus where its debugging evidence lands.

    The SDK talks only to ``engine_url``. ``log_dir`` holds the child logs, and the
    smoke writes each board's Report under ``log_dir / "reports"`` — one directory
    that CI uploads and the just recipe prints, so a run's evidence travels together.
    """

    engine_url: str
    aigateway_url: str
    log_dir: Path


class _PaidStackBoot:
    """Postgres → migrate → real gateway → inspect-capable engine → real key.

    WHY not the replay harness's ``CacheSeededGateway``/``EngineProcess``: that pair
    is welded to the zero-spend invariant (test-only discovery wrapper, snapshot
    seeding required, plain ``uv sync`` that would STRIP the engine's inspect extra).
    Copying the ~60 boot lines keeps the replay harness byte-untouched; fold the two
    together only if a third stack flavor ever appears.
    """

    def __init__(self, *, work_dir: Path, assets_dir: Path) -> None:
        self._work_dir = work_dir
        self._assets_dir = assets_dir
        self._container: Any = None
        self._gateway: ManagedProcess | None = None
        self._engine: ManagedProcess | None = None

    def start(self) -> PaidStack:
        try:
            database_url: str = self._start_postgres()
            self._migrate(database_url)
            aigateway_url: str = self._start_gateway(database_url)
            engine_url: str = self._start_engine(aigateway_url)
            self._connect_key(engine_url)
        except BaseException:
            self.stop()
            raise
        return PaidStack(engine_url=engine_url, aigateway_url=aigateway_url, log_dir=self._work_dir)

    def stop(self) -> None:
        for process in (self._engine, self._gateway):
            if process is not None:
                process.stop()
        self._engine = None
        self._gateway = None
        if self._container is not None:
            self._container.stop()
            self._container = None

    def _start_postgres(self) -> str:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver=None)
        container.start()
        self._container = container
        password: str = quote(container.password, safe="")
        return (
            f"postgres://{container.username}:{password}"
            f"@{container.get_container_host_ip()}:{container.get_exposed_port(5432)}"
            f"/{container.dbname}"
        )

    def _migrate(self, database_url: str) -> None:
        gateway_dir: Path = repo_root() / "apps" / "aigateway"
        _sync(gateway_dir)
        subprocess.run(
            [
                str(venv_bin(gateway_dir, "python")),
                "-m",
                "tortoise",
                "-c",
                "aigateway.db.TORTOISE_CONFIG",
                "migrate",
            ],
            cwd=gateway_dir,
            env=clean_env({"AIGATEWAY_DATABASE_URL": database_url}),
            check=True,
            capture_output=True,
            text=True,
        )

    def _start_gateway(self, database_url: str) -> str:
        gateway_dir: Path = repo_root() / "apps" / "aigateway"
        port: int = free_port()
        env: dict[str, str] = clean_env(
            {
                "AIGATEWAY_DATABASE_URL": database_url,
                # Loopback-only anonymous mode: the engine calls with no credential,
                # and the SDK's connect route answers without identity headers.
                "AIGW_AUTH_MODE": "disabled",
                "AIGATEWAY_ADMIN_EMAILS": "paid-smoke-admin@localhost",
                "AIGW_OPENROUTER_ENABLED": "true",
                # WHY discovery ON (the replay lane keeps it off): live datasheets +
                # execution_access are the production posture, and this lane exists
                # to smoke exactly that posture. Egress is fine here — spending is
                # the point.
                "AIGW_DISCOVERY_ENABLED": "true",
                # NOTE the key is NOT in the environment: it enters through the
                # product's own connect route below, encrypted at rest.
            }
        )
        self._gateway = ManagedProcess(
            name="aigateway",
            command=[
                str(venv_bin(gateway_dir, "uvicorn")),
                "aigateway.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                # WHY info (the replay lane uses warning): this lane exists to debug
                # real runs — info carries the engine's model-call lifecycle lines and
                # the gateway's request lines, and the logs are uploaded on CI failure.
                "--log-level",
                "info",
            ],
            env=env,
            cwd=gateway_dir,
            log_path=self._work_dir / "aigateway.log",
        )
        base_url: str = f"http://127.0.0.1:{port}"
        self._gateway.start(f"{base_url}/healthz")
        return base_url

    def _start_engine(self, aigateway_url: str) -> str:
        engine_dir: Path = repo_root() / "apps" / "screamingface-engine"
        # INVARIANT: the engine venv carries the `benchmarks` extra, or the imported
        # boards silently do not register and the smoke finds an empty shelf. A plain
        # `uv sync` (the replay harness's) would REMOVE the extra again.
        _sync(engine_dir, extra="benchmarks")
        port: int = free_port()
        env: dict[str, str] = clean_env(
            {
                # The App half (catalog, model-parameters, connections routes).
                "URL4_CLOUD_AIGATEWAY_BASE_URL": aigateway_url,
                # The run half (the actual /v1/chat/completions calls).
                "AIGATEWAY_BASE_URL": aigateway_url,
                "URL4_RUNNER_CONFIG": str(engine_dir / "url4.toml"),
                "URL4_BENCHMARK_ASSETS": str(self._assets_dir),
            }
        )
        self._engine = ManagedProcess(
            name="screamingface-engine",
            command=[
                str(venv_bin(engine_dir, "python")),
                "-m",
                "uvicorn",
                "--factory",
                "screamingface_engine.local:create_local_app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                # WHY info (the replay lane uses warning): this lane exists to debug
                # real runs — info carries the engine's model-call lifecycle lines and
                # the gateway's request lines, and the logs are uploaded on CI failure.
                "--log-level",
                "info",
            ],
            env=env,
            cwd=engine_dir,
            log_path=self._work_dir / "engine.log",
        )
        engine_url: str = f"http://127.0.0.1:{port}"
        self._engine.start(f"{engine_url}/healthz")
        return engine_url

    def _connect_key(self, engine_url: str) -> None:
        """Store the real key through the product's own connect path (validated live)."""
        import screamingface as sf

        with sf.Client(engine_url=engine_url) as client:
            client.connect("openrouter", api_key=os.environ[KEY_ENV])


def _sync(project_dir: Path, *, extra: str | None = None) -> None:
    """``uv sync`` an app's venv, optionally with one extra (idempotent)."""
    command: list[str] = ["uv", "sync", "--quiet"]
    if extra is not None:
        command += ["--extra", extra]
    subprocess.run(
        command,
        cwd=project_dir,
        env=clean_env({}),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def paid_stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PaidStack]:
    """One real-key stack for the whole paid session — boot is minutes, spend is real."""
    require_paid_stack()
    assets: Path = _require_imported_assets()
    boot = _PaidStackBoot(work_dir=work_dir(tmp_path_factory), assets_dir=assets)
    stack: PaidStack = boot.start()
    try:
        yield stack
    finally:
        boot.stop()
