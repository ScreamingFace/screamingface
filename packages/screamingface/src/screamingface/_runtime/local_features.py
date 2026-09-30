"""Local E14 flags and the archive dir for `screamingface up` (OME-1307, WIRING, D6).

FEATURE: OME-1307 (E14) D6, STORY: as a researcher, I run `screamingface up` and a traced run is
captured, frozen and archived with no setup. The two E14 flags are off in code (X-12), so `up`
turns them on, and it points the gateway writer and the scoreboard reader at ONE directory.

INVARIANT: the gateway writer root and the scoreboard reader root are the same directory (contracts
C8, local mode). An operator value always wins (the `enable_local_providers` rule).
AIDEV-NOTE: this module prints nothing and logs nothing. The `up` banner and
`_gateway_config_summary` do not name these flags (`tests/test_runtime_cli.py` asserts their exact
shape), and `AIGW_REQUEST_CACHE_ENABLED` is not set here: capture works with the live cache off.
AIDEV-NOTE: `screamingface up` keeps `auth_mode="disabled"` (D5), so locally publish and the admin
route answer 503. That is the dev fallback. Do not change it here.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

from screamingface._runtime.signing_keys import group_is_open

ARCHIVE_DIRNAME: Final = "cache-version-archive"

LOCAL_E14_FLAGS: Final = MappingProxyType(
    {
        "AIGW_CACHE_VERSIONS_ENABLED": "true",  # GW-capture 4.1 (code default False)
        "SCOREBOARD_CLUSTERING_ENABLED": "true",  # SB-submit 4.1 (code default False)
    }
)

_WRITER_BACKEND: Final = "AIGW_CACHE_VERSION_ARCHIVE_BACKEND"  # GW-freeze 4.1
_WRITER_DIR: Final = "AIGW_CACHE_VERSION_ARCHIVE_DIR"  # GW-freeze 4.1
_READER_BACKEND: Final = "SCOREBOARD_ARCHIVE_BACKEND"  # SB-publish 4.1
_READER_DIR: Final = "SCOREBOARD_ARCHIVE_FS_ROOT"  # SB-publish 4.1
ARCHIVE_ENV_GROUP: Final = (_WRITER_BACKEND, _WRITER_DIR, _READER_BACKEND, _READER_DIR)


def local_archive_dir(data_dir: Path) -> Path:
    return data_dir / ARCHIVE_DIRNAME


def apply_local_e14_environment(environment: MutableMapping[str, str], data_dir: Path) -> None:
    """Turn the local E14 flags on and wire one archive directory, per the rules above.

    The archive group is all-or-none: none set means make the private dir and set all four; all
    four set means change nothing (but two different filesystem dirs are a `RuntimeError`); some
    set is a `RuntimeError`. Both checks run before anything is written.
    """
    archive_action = _archive_action(environment)
    for name, value in LOCAL_E14_FLAGS.items():
        environment.setdefault(name, value)
    if archive_action == "make":
        _make_archive(environment, local_archive_dir(data_dir))


def _archive_action(environment: MutableMapping[str, str]) -> str:
    if group_is_open(environment, ARCHIVE_ENV_GROUP):
        return "make"
    if (
        environment[_WRITER_BACKEND] == environment[_READER_BACKEND] == "filesystem"
        and environment[_WRITER_DIR] != environment[_READER_DIR]
    ):
        raise RuntimeError(
            "AIGW_CACHE_VERSION_ARCHIVE_DIR and SCOREBOARD_ARCHIVE_FS_ROOT must name one "
            "directory in local mode (contracts C8)"
        )
    return "keep"


def _make_archive(environment: MutableMapping[str, str], archive: Path) -> None:
    # WHY 0700: the archive holds full prompts and model answers (erd 3.5). `mkdir(mode=...)` is
    # cut by the umask and does not touch an existing dir, so `chmod` sets the mode for both.
    archive.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive.chmod(0o700)
    environment[_WRITER_BACKEND] = environment[_READER_BACKEND] = "filesystem"
    environment[_WRITER_DIR] = environment[_READER_DIR] = str(archive)
