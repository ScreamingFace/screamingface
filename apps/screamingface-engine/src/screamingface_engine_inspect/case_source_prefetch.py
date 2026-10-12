# pyright: reportMissingImports=false
# WHY file-level: the prefetch imports the `inspect` extra's packages, absent in the default
# (extra-less) install the typecheck gate runs against.
"""Case Source prefetch: fetch an eval's files into the replay's empty cache from a host
that will serve them, before the eval's own loader asks for them (OME-1574).

Think of it as stocking the clean room's shelf before the eval walks in: the eval's loader
looks on the shelf first, finds each file it wants with the checksum it wants, and never
goes out to fetch it.

WHY: SAD's loader fetches its five zips through GitHub's contents API, which allows 60
anonymous calls an hour per IP address. Five SAD Benchmarks each fetch all five zips, so one
image build makes 25 calls, and a CI runner sharing its IP address with other jobs gets
HTTP 403, which SKIPs all five Benchmarks. GitHub's raw host serves the same blob at the same
commit and is not bound by that API limit.

INVARIANT: this is still a real fetch into the replay's own empty cache (the clean room in
:mod:`screamingface_engine_inspect.task_replay`), verified by inspect's own ``download``
against upstream's pinned sha256, so a different blob fails the replay exactly as before.
Every address part, checksum and path is imported from upstream, never copied.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

#: One SAD zip on GitHub's raw host: the repo's own path layout, at the pinned commit.
_SAD_RAW_URL: str = (
    "https://raw.githubusercontent.com/LRudL/sad/{revision}/sad/{zip_path}{file_name}"
)


def prefetch_sad(inspect_evals_cache: Path) -> None:
    """Fetch SAD's five zips from GitHub's raw host to where SAD's loader looks for them.

    Example: ``facts/llms/`` → ``https://raw.githubusercontent.com/LRudL/sad/dfc5…/sad/
    facts/llms/structs.zip`` lands at ``<inspect_evals_cache>/sad/facts/llms/structs.zip``
    after its sha256 matches ``c05b…``; the loader's ``download`` then finds it and skips.

    Args:
        inspect_evals_cache: the replay's ``INSPECT_EVALS_CACHE_DIR``.

    Raises:
        ValueError: a fetched zip's sha256 is not upstream's pin (from inspect's ``download``).
        httpx.HTTPStatusError: the raw host refused a zip.
    """

    # WHY imported here: only a SAD replay's child needs inspect_evals.sad, and it must be
    # imported there, after the clean-room environment is in place.
    from inspect_ai.util import download
    from inspect_evals.constants import INSPECT_EVALS_CACHE_PATH
    from inspect_evals.sad.download_data import (
        CACHE_DIR,
        SAD_GITHUB_REVISION,
        ZIP_CHECKSUMS,
        ZIP_FILE_NAME,
        ZIP_PATHS,
    )

    # WHY not CACHE_DIR itself: upstream computes it once, from whichever environment first
    # imported inspect_evals; only its place under the cache root is taken from it.
    sad_cache: Path = inspect_evals_cache / CACHE_DIR.relative_to(INSPECT_EVALS_CACHE_PATH)
    for zip_path in ZIP_PATHS.values():
        url: str = _SAD_RAW_URL.format(
            revision=SAD_GITHUB_REVISION, zip_path=zip_path, file_name=ZIP_FILE_NAME
        )
        download(url, ZIP_CHECKSUMS[zip_path], sad_cache / zip_path / ZIP_FILE_NAME)


#: Upstream package → the prefetch every Task in it needs. Most packages need none.
_PREFETCHES: dict[str, Callable[[Path], None]] = {"inspect_evals.sad": prefetch_sad}


def prefetch_case_sources(task: str, inspect_evals_cache: Path) -> None:
    """Run the prefetch the Task's upstream package needs, if it has one.

    Args:
        task: the declaration's ``"module:attr"`` reference, e.g.
            ``"inspect_evals.sad.sad:sad_facts_llms"``.
        inspect_evals_cache: the replay's ``INSPECT_EVALS_CACHE_DIR``.
    """

    module: str = task.partition(":")[0]
    for package, prefetch in _PREFETCHES.items():
        if module == package or module.startswith(package + "."):
            prefetch(inspect_evals_cache)
