"""The stacks a workbench notebook runs against (e2e workbench spec §3.1): ``replay`` and ``local``.

Selection is by env var, not a pytest option: ``pytest_addoption`` in a nested conftest does not
register when the invocation is ``pytest tests/e2e``.

INVARIANT: a target that cannot run here SKIPS with the reason (``pytest.skip``) BEFORE booting
anything, and never spends unless the paid opt-in and the BYOK key are both present. Once its
gate is passed, a broken target is a hard FAILURE, not a skip: on ``local``, an Engine that does
not list ifeval raises. Whatever was started is torn down on every exit path, a partial boot
included: ``down`` runs once ``up`` was invoked (even if ``up`` itself failed), and the Engine is
stopped once its start was attempted.
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
from harness._local_proc import clean_env
from harness.benchmark_assets import ASSETS_ENV, assets_root
from harness.cache_seeded import CacheSeededGateway
from harness.stack import EngineProcess, replay_stack

from screamingface._runtime.source import MODE_CHECKOUT, SOURCE_ENVIRONMENT_VARIABLE
from workbench.evidence import FileLogSource, LogSource, ServiceLogSource

TARGET_ENV: Final = "SCREAMINGFACE_WORKBENCH_TARGET"
KNOWN_TARGETS: Final = ("replay", "local")
_DEFAULT_TARGET: Final = "replay"

PAID_ENV: Final = "SCREAMINGFACE_TEST_PAID"
KEY_ENV: Final = "OPENROUTER_API_KEY"
# The runtime's default ports (RuntimeConfig); passed explicitly to `up` so a stray
# SCREAMINGFACE_*_PORT in the environment cannot move the stack away from these URLs.
# The runtime's OWN Engine (9108) goes unused, as in `just local-stack-notebooks`: the
# notebook talks to a separate inspect-capable Engine on a free port.
_LOCAL_GATEWAY_PORT: Final = 9105
_LOCAL_ENGINE_PORT: Final = 9108
_LOCAL_SCOREBOARD_PORT: Final = 9106
# Spec §3.1: scoreboard_url is always explicit. The replay stack runs no Scoreboard and the
# notebook never calls the leaderboard there, so this loopback (discard port) is UNUSED on
# replay — it only keeps the SDK off its hosted default.
REPLAY_SCOREBOARD_URL: Final = "http://127.0.0.1:9"


@dataclass(frozen=True)
class LiveTarget:
    name: str
    engine_url: str
    scoreboard_url: str  # always explicit (spec §3.1); a placeholder on replay
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
            scoreboard_url=REPLAY_SCOREBOARD_URL,
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
    """The environment ``screamingface up``/``down`` run under: an ALLOWLIST, never the shell.

    Same rule as every other harness child (``harness._local_proc.clean_env``): PATH/HOME/
    locale basics plus exactly what this target sets. WHY (review finding 3): a copied shell
    let a forced ``SCREAMINGFACE_RUNTIME_SOURCE``, ``AIGW_*``/``SCOREBOARD_*`` service settings,
    ``SCREAMINGFACE_*_PORT``/``_DATA_DIR`` overrides, a foreign ``AIGATEWAY_DATABASE_URL`` (which
    the runtime refuses to boot under, OME-1169) and the provider key reach the runtime, so a
    green bundle could come from another source tree or a reconfigured service.

    WHY pin the source to ``checkout``: the lane lives in this checkout and vouches for ITS
    code; pinned, the runtime serves this tree or refuses to start, never a bundled copy.
    The BYOK key is deliberately absent — the notebook connects it from its own environment.
    """
    return clean_env({SOURCE_ENVIRONMENT_VARIABLE: MODE_CHECKOUT})


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
        # WHY the Engine's preparer: ifeval is not a `screamingface prepare` board; the Engine
        # builds it, as .github/workflows/screamingface-e2e-replay.yml does.
        pytest.skip(
            f"local workbench target needs prepared ifeval assets at {root / 'ifeval'} — from "
            "apps/screamingface-engine run `uv run --extra benchmarks python -m "
            f"screamingface_engine.benchmarks.prepare --root {root} --bundle ifeval`, or point "
            f"{ASSETS_ENV} at a prepared root"
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
    """``screamingface up`` (Gateway + Scoreboard) plus an inspect-capable Engine; UNGATED.

    Same layout as ``just local-stack-notebooks``: the runtime's own Engine serves only the
    built-in boards, so a separate Engine (``harness.stack.EngineProcess`` — synced with the
    inspect extra, reading ``assets``) serves ifeval against the runtime's Gateway.

    The paid/key gate lives in ``_local``. This boot itself spends nothing (no key is connected
    here), which is what lets ``test_local_boot`` check it without a provider key.
    """
    data_dir = work_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # WHY a symlink: the runtime hard-wires its assets to <data-dir>/benchmark-assets
    # (RuntimeConfig.assets_dir) with no override, and a fresh data dir has none prepared.
    # Linking reuses the prepared root without re-downloading or touching the developer's
    # own data dir.
    link = data_dir / "benchmark-assets"
    if not link.exists():
        link.symlink_to(assets.resolve(), target_is_directory=True)
    # The runtime runs auth-free on loopback and owns its sqlite gateway DB, so unlike
    # tests/paid/conftest.py there is no AIGW_AUTH_MODE / database env to mirror here.
    # NOTE the BYOK key is NOT a parameter: the notebook connects it from os.environ.
    # WHY `up` inside the try: it can start the Gateway and then fail on the Scoreboard, so
    # `down` must run even when `up` raises. `engine` stays None until it is built, so a failed
    # construction only downs the runtime; once start is attempted, stop runs (start can fail
    # after spawning the process).
    engine: EngineProcess | None = None
    try:
        _runtime_cli(
            "up",
            "--data-dir",
            str(data_dir),
            "--gateway-port",
            str(_LOCAL_GATEWAY_PORT),
            "--engine-port",
            str(_LOCAL_ENGINE_PORT),
            "--scoreboard-port",
            str(_LOCAL_SCOREBOARD_PORT),
        )
        engine = EngineProcess(work_dir=work_dir, assets_dir=assets)
        engine_url = engine.start(f"http://127.0.0.1:{_LOCAL_GATEWAY_PORT}")
        # WHY a hard failure, not a skip: this Engine has the inspect extra and the prepared
        # ifeval root, so an Engine without ifeval is a broken target, not a missing optional.
        listed = _listed_benchmarks(engine_url)
        if "ifeval" not in listed:
            raise RuntimeError(
                f"the local target's Engine does not list ifeval (listed: {listed}) although "
                f"it was given {assets}; see {work_dir / 'engine.log'}"
            )
        yield LiveTarget(
            name="local",
            engine_url=engine_url,
            scoreboard_url=f"http://127.0.0.1:{_LOCAL_SCOREBOARD_PORT}",
            # The Engine is its own process with its own log; the Gateway still runs inside the
            # runtime, so its hop is the "gateway"-tagged lines of runtime.log (the tag drops the
            # "AI " of the service name, server._serve_service). Both hop checks AND the
            # aigateway gateway_call_id check run as on replay.
            sources=(
                FileLogSource("engine", work_dir / "engine.log"),
                ServiceLogSource("aigateway", data_dir / "runtime.log", service="gateway"),
            ),
            required_hops=("engine", "aigateway"),
            params={"RECIPE": "authored", "EXPECT_CACHED": False},
        )
    finally:
        try:
            if engine is not None:
                engine.stop()
        finally:
            _runtime_cli("down", "--data-dir", str(data_dir))
