"""The stacks a workbench notebook runs against (e2e workbench spec §3.1): ``replay`` and ``local``.

Selection is by env var, not a pytest option: ``pytest_addoption`` in a nested conftest does not
register when the invocation is ``pytest tests/e2e``.

INVARIANT: a target that cannot run here SKIPS with the reason (``pytest.skip``); it never boots
half a stack and never spends unless the paid opt-in and the BYOK key are both present.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import pytest
from harness._gating import SNAPSHOTS_DIR, require_e2e_stack
from harness.benchmark_assets import ASSETS_ENV, assets_root
from harness.cache_seeded import CacheSeededGateway
from harness.stack import replay_stack

from workbench.evidence import FileLogSource, LogSource, ServiceLogSource

TARGET_ENV: Final = "SCREAMINGFACE_WORKBENCH_TARGET"
KNOWN_TARGETS: Final = ("replay", "local")
_DEFAULT_TARGET: Final = "replay"

PAID_ENV: Final = "SCREAMINGFACE_TEST_PAID"
KEY_ENV: Final = "OPENROUTER_API_KEY"
# The runtime's default ports (RuntimeConfig); passed explicitly to `up` so a stray
# SCREAMINGFACE_*_PORT in the environment cannot move the stack away from these URLs.
_LOCAL_ENGINE_PORT: Final = 9108
_LOCAL_SCOREBOARD_PORT: Final = 9106


@dataclass(frozen=True)
class LiveTarget:
    name: str
    engine_url: str
    scoreboard_url: str | None  # None on replay: the replay stack has no Scoreboard
    sources: tuple[LogSource, ...]
    required_hops: tuple[str, ...]
    params: dict[str, Any] = field(default_factory=dict)  # merged into injected parameters


def selected_target() -> str:
    """The target named by ``SCREAMINGFACE_WORKBENCH_TARGET``; unset or empty means replay."""
    name = os.environ.get(TARGET_ENV) or _DEFAULT_TARGET
    if name not in KNOWN_TARGETS:
        raise ValueError(f"{TARGET_ENV}={name!r} is not one of {', '.join(KNOWN_TARGETS)}")
    return name


def start_target(name: str, work_dir: Path) -> AbstractContextManager[LiveTarget]:
    """Boot ``name`` for the duration of the ``with`` block; skips (pytest) when gated off."""
    if name == "replay":
        return _replay(work_dir)
    if name == "local":
        return _local(work_dir)
    raise ValueError(f"unknown workbench target {name!r}; known: {', '.join(KNOWN_TARGETS)}")


@contextmanager
def _replay(work_dir: Path) -> Iterator[LiveTarget]:
    require_e2e_stack()
    assets = assets_root()
    if not (assets / "ifeval").is_dir():
        pytest.skip(f"replay target needs prepared ifeval assets at {assets / 'ifeval'}")
    backend = CacheSeededGateway(
        snapshot=SNAPSHOTS_DIR / "ifeval.snapshot.gz",
        manifest=SNAPSHOTS_DIR / "ifeval.manifest.json",
        work_dir=work_dir,
    )
    with replay_stack(backend, work_dir=work_dir, assets_dir=assets) as stack:
        yield LiveTarget(
            name="replay",
            engine_url=stack.engine_url,
            scoreboard_url=None,
            sources=(
                FileLogSource("engine", work_dir / "engine.log"),
                FileLogSource("aigateway", work_dir / "aigateway.log"),
            ),
            required_hops=("engine", "aigateway"),
            params={"RECIPE": "golden", "EXPECT_CACHED": True},
        )


def _local_unavailable_reason() -> str | None:
    if os.environ.get(PAID_ENV) != "1":
        return f"{PAID_ENV}=1 not set (the local target spends real tokens; opt-in only)"
    if not os.environ.get(KEY_ENV):
        return f"{KEY_ENV} not set (the local target connects it as the BYOK key)"
    return None


def _runtime_child_env() -> dict[str, str]:
    """The environment ``screamingface up``/``down`` run under.

    WHY scrub AIGATEWAY_DATABASE_URL: the runtime owns its sqlite gateway DB and REFUSES to boot
    or adopt while that variable is set (OME-1169); a developer shell that exports it for the
    aigateway app would otherwise turn every local run into a boot error.
    """
    env = dict(os.environ)
    env.pop("AIGATEWAY_DATABASE_URL", None)
    return env


def _runtime_cli(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "screamingface._runtime.cli", *args],
        check=True,
        env=_runtime_child_env(),
    )


def _prepared_ifeval_assets() -> Path:
    """The prepared assets root holding ifeval — or a skip that says how to prepare it.

    WHY ifeval specifically (tests/paid/conftest.py accepts any bundle): the quickstart notebook
    evaluates ifeval, so a root without it would boot a stack that cannot run the notebook.
    """
    root = assets_root()
    if not (root / "ifeval" / "cases.json").is_file():
        pytest.skip(
            f"local workbench target needs prepared ifeval assets at {root / 'ifeval'} — run "
            f"`screamingface prepare ifeval`, or point {ASSETS_ENV} at a prepared root"
        )
    return root


def _listed_benchmarks(engine_url: str) -> list[str]:
    """The Benchmark ids the running Engine lists (``GET /v1/benchmarks``)."""
    with urllib.request.urlopen(f"{engine_url}/v1/benchmarks", timeout=30) as response:
        body = json.load(response)
    return [str(row.get("id")) for row in body.get("data", []) if isinstance(row, dict)]


@contextmanager
def _local(work_dir: Path) -> Iterator[LiveTarget]:
    reason = _local_unavailable_reason()
    if reason is not None:
        pytest.skip(f"local workbench target unavailable: {reason}")
    with local_stack(work_dir, _prepared_ifeval_assets()) as target:
        yield target


@contextmanager
def local_stack(work_dir: Path, assets: Path) -> Iterator[LiveTarget]:
    """Boot ``screamingface up`` on a fresh data dir wired to ``assets``; UNGATED.

    The paid/key gate lives in ``_local``. This boot itself spends nothing (no key is connected
    here), which is what lets the boot be smoke-checked without a provider key.
    """
    data_dir = work_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # WHY a symlink: the runtime hard-wires its assets to <data-dir>/benchmark-assets
    # (RuntimeConfig.assets_dir) with no override, and a fresh data dir has none prepared.
    # Linking reuses the prepared root (as tests/paid boots its engine on it) without
    # re-downloading or touching the developer's own data dir.
    link = data_dir / "benchmark-assets"
    if not link.exists():
        link.symlink_to(assets.resolve(), target_is_directory=True)
    # The runtime runs auth-free on loopback and owns its sqlite gateway DB, so unlike
    # tests/paid/conftest.py there is no AIGW_AUTH_MODE / database env to mirror here.
    # NOTE the BYOK key is NOT a parameter: the notebook connects it from os.environ.
    _runtime_cli(
        "up",
        "--data-dir",
        str(data_dir),
        "--engine-port",
        str(_LOCAL_ENGINE_PORT),
        "--scoreboard-port",
        str(_LOCAL_SCOREBOARD_PORT),
    )
    runtime_log = data_dir / "runtime.log"
    engine_url = f"http://127.0.0.1:{_LOCAL_ENGINE_PORT}"
    try:
        # WHY after boot: assets alone do not install a board. ifeval is contributed by the
        # engine's entry-point plugin (benchmarks/discovery.py), so an interpreter without it
        # serves only the built-ins; skip with what IS listed rather than fail mid-notebook.
        listed = _listed_benchmarks(engine_url)
        if "ifeval" not in listed:
            pytest.skip(
                f"the local runtime does not list ifeval (listed: {listed}); its board comes "
                "from the engine's benchmark plugin, which this interpreter does not install"
            )
        yield LiveTarget(
            name="local",
            engine_url=engine_url,
            scoreboard_url=f"http://127.0.0.1:{_LOCAL_SCOREBOARD_PORT}",
            # One process, one log: the service tag splits it into the replay stack's hops,
            # so the hop check AND the aigateway gateway_call_id check run here too. The
            # gateway's tag is "gateway" (server._serve_service strips the "AI " of its name).
            sources=(
                ServiceLogSource("engine", runtime_log, service="engine"),
                ServiceLogSource("aigateway", runtime_log, service="gateway"),
            ),
            required_hops=("engine", "aigateway"),
            params={"RECIPE": "authored", "EXPECT_CACHED": False},
        )
    finally:
        _runtime_cli("down", "--data-dir", str(data_dir))
