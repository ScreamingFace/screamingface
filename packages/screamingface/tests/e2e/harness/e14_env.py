"""The E14 env of the stack: keys, flags and the archive dir (unit E2E, OME-1307).

FEATURE: OME-1307 (E14) E2E. The stack runs the SAME env builders that `screamingface up` runs:
the SDK key builder (`apply_local_signing_environment`) and the WIRING hook
(`apply_local_e14_environment`). A wrong key or flag in those builders fails the E2E spines.
INVARIANT: no harness copy of the WIRING flags exists. The hook is imported directly, so a
renamed or broken hook is an import error or a failure, never a silent fallback.
INVARIANT: the harness never logs a key value. The private receipt key goes only to the gateway
map, and the private grant key only to the scoreboard map.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from screamingface._runtime.local_features import apply_local_e14_environment
from screamingface._runtime.signing_keys import apply_local_signing_environment

GATEWAY_PREFIXES: Final = ("AIGATEWAY_", "AIGW_")
SCOREBOARD_PREFIXES: Final = ("SCOREBOARD_",)


@dataclass(frozen=True, slots=True)
class E14Env:
    gateway: Mapping[str, str]  # AIGATEWAY_* and AIGW_* keys only
    scoreboard: Mapping[str, str]  # SCOREBOARD_* keys only
    archive_dir: Path  # the root of the filesystem archive adapter (C8 local mode)


def e14_env(data_dir: Path) -> E14Env:
    env: dict[str, str] = {}
    data_dir.mkdir(parents=True, exist_ok=True)
    # WHY: the code `screamingface up` runs, so the keys have the local-runtime form (D7 X-4).
    apply_local_signing_environment(env, data_dir)
    apply_local_e14_environment(env, data_dir)
    archive_dir = Path(env["AIGW_CACHE_VERSION_ARCHIVE_DIR"])
    archive_dir.mkdir(parents=True, exist_ok=True)
    if env["SCOREBOARD_ARCHIVE_FS_ROOT"] != env["AIGW_CACHE_VERSION_ARCHIVE_DIR"]:
        raise RuntimeError("the gateway writer and the scoreboard reader must share one directory")
    gateway, scoreboard = split_env(env)
    return E14Env(gateway=gateway, scoreboard=scoreboard, archive_dir=archive_dir)


def split_env(env: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Route each key to its service by prefix. A key with no service prefix is an error."""
    gateway: dict[str, str] = {}
    scoreboard: dict[str, str] = {}
    for key, value in env.items():
        if key.startswith(GATEWAY_PREFIXES):
            gateway[key] = value
        elif key.startswith(SCOREBOARD_PREFIXES):
            scoreboard[key] = value
        else:
            # INVARIANT: the message names the key, never the value.
            raise ValueError(f"E14 env key has no service prefix: {key}")
    return gateway, scoreboard
