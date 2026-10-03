"""The replay stack with an Engine that serves the imported (inspect) boards (OME-1289 E4a, EV-12).

Mental model: ``stack.replay_stack`` with one change. ``stack.EngineProcess`` syncs the Engine venv
with a plain ``uv sync``, and that REMOVES the ``benchmarks`` extra, which carries ``inspect_ai``
and ``inspect_evals``. Without them the imported boards (``inspect-gsm8k``) do not register, so the
reducer lane could not run on the replay stack as it is.

WHY a copy and not an edit of ``stack.py``: the replay harness stays byte-untouched (its files are
append-only). The paid lane did the same for the same reason (``tests/paid/conftest.py``,
``_PaidStackBoot``: "Copying the ~60 boot lines keeps the replay harness byte-untouched; fold
the two together only if a third stack flavor ever appears"). This is that third flavor, and the
fold-in is left for a change that may edit ``stack.py``.

The environment of the Engine child is the same as in ``stack.py``: ``clean_env`` plus the gateway
URLs, so no provider key can reach it.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ._local_proc import ManagedProcess, clean_env, free_port, repo_root, venv_bin
from .ports import ReplayBackend
from .stack import EngineProcess, ReplayStack


class InspectEngineProcess(EngineProcess):
    """``EngineProcess`` whose venv is synced WITH the ``benchmarks`` extra."""

    def start(self, aigateway_base_url: str) -> str:
        engine_dir = repo_root() / "apps" / "screamingface-engine"
        subprocess.run(
            ["uv", "sync", "--quiet", "--extra", "benchmarks"],
            cwd=engine_dir,
            env=clean_env({}),
            check=True,
            capture_output=True,
            text=True,
        )
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


@contextmanager
def inspect_replay_stack(
    backend: ReplayBackend,
    *,
    work_dir: Path,
    assets_dir: Path | None = None,
) -> Iterator[ReplayStack]:
    """``stack.replay_stack`` with an ``InspectEngineProcess``: same order, same teardown."""
    engine = InspectEngineProcess(work_dir=work_dir, assets_dir=assets_dir)
    aigateway_url = asyncio.run(backend.start())
    try:
        engine_url = engine.start(aigateway_url)
        yield ReplayStack(engine_url=engine_url, aigateway_url=aigateway_url)
    finally:
        engine.stop()
        asyncio.run(backend.stop())


@contextmanager
def inspect_capture_stack(
    backend: ReplayBackend,
    *,
    work_dir: Path,
    assets_dir: Path | None = None,
) -> Iterator[tuple[ReplayStack, Any]]:
    """``inspect_replay_stack`` with ``slice_snapshot._CaptureProxy`` between Engine and gateway.

    The Engine is handed the proxy URL, so every ``/chat/completions`` body it sends is recorded
    in ``proxy.records`` (a list of ``{"request_body", "status", "cache_header"}``) before the
    gateway answers it (FR#13). ``ReplayStack.aigateway_url`` is still the gateway's own.
    """
    # Lazy: slice_snapshot is a script-sized module that the other lanes do not need.
    from fixtures.slice_snapshot import _CaptureProxy

    engine = InspectEngineProcess(work_dir=work_dir, assets_dir=assets_dir)
    aigateway_url = asyncio.run(backend.start())
    proxy: Any = None
    try:
        proxy = _CaptureProxy(aigateway_url)
        engine_url = engine.start(proxy.url)
        yield ReplayStack(engine_url=engine_url, aigateway_url=aigateway_url), proxy
    finally:
        engine.stop()
        if proxy is not None:
            proxy.shutdown()
        asyncio.run(backend.stop())
