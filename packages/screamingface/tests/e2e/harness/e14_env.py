"""The E14 env of the stack: keys, flags and the archive dir (unit E2E, OME-1307).

FEATURE: OME-1307 (E14) E2E. The stack runs the SAME env builders that `screamingface up` runs:
the SDK key builder (`apply_local_signing_environment`) and the WIRING hook
(`apply_local_e14_environment`). A wrong key or flag in those builders fails the E2E spines.
INVARIANT: the fallback is the harness copy of what the WIRING hook sets. The harness self-test
fails when the two drift, so the fallback can never hide a missing WIRING flag.
INVARIANT: the harness never logs a key value. The private receipt key goes only to the gateway
map, and the private grant key only to the scoreboard map.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from screamingface._runtime.signing_keys import apply_local_signing_environment

GATEWAY_PREFIXES: Final = ("AIGATEWAY_", "AIGW_")
SCOREBOARD_PREFIXES: Final = ("SCOREBOARD_",)

WIRING_HOOK_MODULE: Final = "screamingface._runtime.local_features"
WIRING_HOOK_FUNCTION: Final = "apply_local_e14_environment"

FALLBACK_FLAGS: Final[Mapping[str, str]] = {
    "AIGW_CACHE_VERSIONS_ENABLED": "true",
    "SCOREBOARD_CLUSTERING_ENABLED": "true",
}
FALLBACK_ARCHIVE_BACKENDS: Final = (
    "AIGW_CACHE_VERSION_ARCHIVE_BACKEND",
    "SCOREBOARD_ARCHIVE_BACKEND",
)
FALLBACK_ARCHIVE_DIRS: Final = ("AIGW_CACHE_VERSION_ARCHIVE_DIR", "SCOREBOARD_ARCHIVE_FS_ROOT")
_ARCHIVE_DIRNAME: Final = "cache-version-archive"


@dataclass(frozen=True, slots=True)
class E14Env:
    gateway: Mapping[str, str]  # AIGATEWAY_* and AIGW_* keys only
    scoreboard: Mapping[str, str]  # SCOREBOARD_* keys only
    archive_dir: Path  # the root of the filesystem archive adapter (C8 local mode)
    source: Literal["wiring", "fallback"]


def wiring_hook() -> Callable[[MutableMapping[str, str], Path], None] | None:
    """The WIRING local-runtime hook, or `None` when WIRING is not merged on this branch."""
    try:
        module = importlib.import_module(WIRING_HOOK_MODULE)
        hook: Callable[[MutableMapping[str, str], Path], None] = getattr(
            module, WIRING_HOOK_FUNCTION
        )
    except (ImportError, AttributeError):
        return None
    return hook


def e14_env(data_dir: Path) -> E14Env:
    env: dict[str, str] = {}
    data_dir.mkdir(parents=True, exist_ok=True)
    # WHY: the code `screamingface up` runs, so the keys have the local-runtime form (D7 X-4).
    apply_local_signing_environment(env, data_dir)
    hook = wiring_hook()
    source: Literal["wiring", "fallback"]
    if hook is not None:
        hook(env, data_dir)
        source = "wiring"
    else:
        env.update(FALLBACK_FLAGS)
        env.update(dict.fromkeys(FALLBACK_ARCHIVE_BACKENDS, "filesystem"))
        env.update(dict.fromkeys(FALLBACK_ARCHIVE_DIRS, str(data_dir / _ARCHIVE_DIRNAME)))
        source = "fallback"
    archive_dir = Path(env["AIGW_CACHE_VERSION_ARCHIVE_DIR"])
    archive_dir.mkdir(parents=True, exist_ok=True)
    if env["SCOREBOARD_ARCHIVE_FS_ROOT"] != env["AIGW_CACHE_VERSION_ARCHIVE_DIR"]:
        raise RuntimeError("the gateway writer and the scoreboard reader must share one directory")
    gateway, scoreboard = split_env(env)
    return E14Env(gateway=gateway, scoreboard=scoreboard, archive_dir=archive_dir, source=source)


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
