"""The E14 stack: real gateway, real engine and real scoreboard (unit E2E, OME-1307).

Mental model: ``stack.replay_stack`` plus the scoreboard. The gateway is the OME-961 cache-seeded
one, with the request cache seeded from the committed snapshot and zero provider keys, so a cache
miss is a loud ``404 profile_not_found``, never spend. It now runs ``cloudflare_headers`` (D5).
The engine keeps its local mode and forwards the inbound ``X-User-Email`` to the gateway. The
scoreboard is a third process. One directory is the filesystem archive of contracts C8 (the
gateway writes, the scoreboard reads).

Stages of ``e14_stack``, in execution order (teardown in reverse, also after a failed boot):

1. **Env** - ``e14_env``: keys, flags and the archive dir, from the local-runtime builders.
2. **Gateway** - ``CacheSeededGateway(auth_mode="cloudflare_headers", extra_env=env.gateway)``.
3. **Engine** - ``EngineProcess`` against the gateway.
4. **Scoreboard** - ``ScoreboardProcess.start(engine_url=..., board=...)``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import screamingface as sf

from ._gating import SNAPSHOTS_DIR
from .cache_seeded import CacheSeededGateway
from .e14_env import e14_env
from .goldens import GoldenReport, spec_model
from .scoreboard_proc import ScoreboardProcess
from .stack import EngineProcess


@dataclass(frozen=True, slots=True)
class E14Stack:
    engine_url: str
    aigateway_url: str
    scoreboard_url: str
    archive_dir: Path


@contextmanager
def e14_stack(
    *,
    work_dir: Path,
    assets_dir: Path,
    board: str = "ifeval",
    scoreboard_extra_env: Mapping[str, str] | None = None,
) -> Iterator[E14Stack]:
    env = e14_env(work_dir / "runtime-data")
    manifest = SNAPSHOTS_DIR / f"{board}.manifest.json"
    gateway = CacheSeededGateway(
        snapshot=SNAPSHOTS_DIR / f"{board}.snapshot.gz",
        manifest=manifest if manifest.exists() else None,
        work_dir=work_dir,
        auth_mode="cloudflare_headers",
        extra_env=env.gateway,
    )
    engine = EngineProcess(work_dir=work_dir, assets_dir=assets_dir)
    scoreboard = ScoreboardProcess(
        work_dir=work_dir,
        extra_env={**env.scoreboard, **(scoreboard_extra_env or {})},
    )
    try:
        aigateway_url = asyncio.run(gateway.start())
        engine_url = engine.start(aigateway_url)
        scoreboard_url = scoreboard.start(engine_url=engine_url, board=board)
        yield E14Stack(
            engine_url=engine_url,
            aigateway_url=aigateway_url,
            scoreboard_url=scoreboard_url,
            archive_dir=env.archive_dir,
        )
    finally:
        scoreboard.stop()
        engine.stop()
        asyncio.run(gateway.stop())


def e14_candidate(
    golden: GoldenReport, *, name: str = "e2e-ifeval-loop", max_rounds: int | None = None
) -> sf.CorrectiveLoop:
    """The golden's corrective loop, rebuilt with an explicit system name.

    WHY not ``build_candidate``: its inferred name joins the member names with ``+`` and ``/``
    (``openrouter/...+openrouter/...``), and the scoreboard refuses that as a system name
    (``422 invalid_system_name``, SR pattern ``a-z0-9._-``). A submit needs a valid name.
    INVARIANT: only the name changes. The model requests are the recorded ones, so the seeded
    snapshot still serves every call (the name is not part of a model request).
    """
    assert golden.judge_spec is not None and golden.max_rounds is not None
    return sf.CorrectiveLoop(
        [spec_model(spec) for spec in golden.member_specs],
        judge=spec_model(golden.judge_spec),
        max_rounds=golden.max_rounds if max_rounds is None else max_rounds,
        name=name,
    )
