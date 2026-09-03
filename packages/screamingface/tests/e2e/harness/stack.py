"""Boot the real engine against a replay backend, notebook-shaped (OME-961).

Mental model: this module is ``screamingface up`` for one test — the engine runs exactly
as local mode ships it (``screamingface_engine.local:create_local_app`` under uvicorn,
in-process runs, in-memory event stream), pointed at whatever base URL the
``ReplayBackend`` handed back. The SDK then connects to the engine the way a notebook
does: ``sf.Client(engine_url=stack.engine_url)``.

Stages of ``replay_stack``, in execution order:

1. **Backend** — ``backend.start()`` returns the aigateway base URL. The engine never
   learns anything else about it (the ``ports.ReplayBackend`` seam).
2. **Engine** — a subprocess from ``apps/screamingface-engine``'s own venv. BOTH
   gateway variables are set, because they are read by different halves of the engine
   (``URL4_CLOUD_AIGATEWAY_BASE_URL`` wires the App's catalog/connections routes;
   ``AIGATEWAY_BASE_URL`` wires the run-mode model calls) — setting only one is the
   classic mis-boot where discovery works and every model call goes to :9105.
   ``URL4_RUNNER_CONFIG`` names the checkout's ``url4.toml`` explicitly, and
   ``URL4_BENCHMARK_ASSETS`` is set only when a board test supplies prepared assets —
   without it the engine (by design) installs no benchmarks.
3. **Teardown** — reverse order, even on a failed boot.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ._local_proc import ManagedProcess, clean_env, free_port, repo_root, sync_project, venv_bin
from .ports import ReplayBackend


@dataclass(frozen=True, slots=True)
class ReplayStack:
    """The two URLs a test needs: the SDK talks to ``engine_url``; the engine alone
    talks to ``aigateway_url`` (exposed for direct seam assertions)."""

    engine_url: str
    aigateway_url: str


class EngineProcess:
    """The engine's local mode as a supervised subprocess on a free loopback port."""

    def __init__(self, *, work_dir: Path, assets_dir: Path | None = None) -> None:
        self._work_dir = work_dir
        self._assets_dir = assets_dir
        self._process: ManagedProcess | None = None

    def start(self, aigateway_base_url: str) -> str:
        engine_dir = repo_root() / "apps" / "screamingface-engine"
        sync_project(engine_dir)
        port = free_port()
        env = clean_env(
            {
                # The App half (catalog, model-parameters, connections routes).
                "URL4_CLOUD_AIGATEWAY_BASE_URL": aigateway_base_url,
                # The run half (the actual /v1/chat/completions calls).
                "AIGATEWAY_BASE_URL": aigateway_base_url,
                # Explicit, so the boot does not depend on the checkout-relative
                # fallback inside screamingface_engine.local.
                "URL4_RUNNER_CONFIG": str(engine_dir / "url4.toml"),
                # No web tools: TAVILY_API_KEY deliberately absent (deny by default).
            }
        )
        if self._assets_dir is not None:
            env["URL4_BENCHMARK_ASSETS"] = str(self._assets_dir)
        self._process = ManagedProcess(
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
                "--log-level",
                "warning",
            ],
            env=env,
            cwd=engine_dir,
            log_path=self._work_dir / "engine.log",
        )
        engine_url = f"http://127.0.0.1:{port}"
        self._process.start(f"{engine_url}/healthz")
        return engine_url

    def stop(self) -> None:
        if self._process is not None:
            self._process.stop()
            self._process = None


@contextmanager
def replay_stack(
    backend: ReplayBackend,
    *,
    work_dir: Path,
    assets_dir: Path | None = None,
) -> Iterator[ReplayStack]:
    """Backend up → engine up → yield the URLs → tear both down (reverse order).

    Synchronous on purpose: the SDK client under test is synchronous, and pytest
    fixtures compose ``with`` blocks more honestly than event loops. The backend's
    async Protocol methods are driven through ``asyncio.run``.
    """
    engine = EngineProcess(work_dir=work_dir, assets_dir=assets_dir)
    aigateway_url = asyncio.run(backend.start())
    try:
        engine_url = engine.start(aigateway_url)
        yield ReplayStack(engine_url=engine_url, aigateway_url=aigateway_url)
    finally:
        engine.stop()
        asyncio.run(backend.stop())
