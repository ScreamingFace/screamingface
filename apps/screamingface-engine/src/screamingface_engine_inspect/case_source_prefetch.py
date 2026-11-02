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
commit and is not bound by that API limit. cyse4_threat_intelligence fetches 26 report PDFs
from web.archive.org, which refuses connections partway through the burst; the owner's
Hugging Face mirror serves the same bytes (OME-1602).

INVARIANT: this is still a real fetch into the replay's own empty cache (the clean room in
:mod:`screamingface_engine_inspect.task_replay`), verified by inspect's own ``download``
against inspect_evals' pinned sha256, so a different blob fails the replay exactly as before.
Every address part, checksum and path is imported from inspect_evals, never copied.
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
        ValueError: a fetched zip's sha256 is not inspect_evals' pin (from inspect's ``download``).
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

    # WHY not CACHE_DIR itself: inspect_evals computes it once, from whichever environment first
    # imported inspect_evals; only its place under the cache root is taken from it.
    sad_cache: Path = inspect_evals_cache / CACHE_DIR.relative_to(INSPECT_EVALS_CACHE_PATH)
    for zip_path in ZIP_PATHS.values():
        url: str = _SAD_RAW_URL.format(
            revision=SAD_GITHUB_REVISION, zip_path=zip_path, file_name=ZIP_FILE_NAME
        )
        download(url, ZIP_CHECKSUMS[zip_path], sad_cache / zip_path / ZIP_FILE_NAME)


#: One of the 26 non-CrowdStrike threat-intelligence report PDFs on the owner's Hugging Face
#: mirror, at the commit uploaded 2026-10-20 (OME-1602). Ours, so not imported from inspect_evals:
#: each file is byte-identical to what inspect_evals fetches from web.archive.org.
_THREAT_INTEL_MIRROR_URL: str = (
    "https://huggingface.co/datasets/khoaguin/cyberseceval4-threat-intel-reports/resolve/"
    "ab38cf24125e38b88ef0f2dd866d5d3cc12965cb/pdfs/{report_id}.pdf"
)


def prefetch_cyse4_threat_intelligence(inspect_evals_cache: Path) -> None:
    """Stock inspect_evals' threat-intelligence reports folder: CrowdStrike's zip first, then the
    26 other report PDFs from the owner's mirror instead of web.archive.org.

    WHY: inspect_evals fetches those 26 PDFs from web.archive.org, whose rate limiter refuses
    connections partway through a burst of that size, so a build that fetches them fails
    (OME-1273, 2026-10-02). inspect_evals' fetch step skips a PDF already in the folder with the
    pinned sha256, so a stocked folder means it asks no host.

    Stage 1 — find the folder inspect_evals' loader will read, by inspect_evals' own rule (an env
    override, the package's folder, else the user cache, which the replay child points at a
    clean one through XDG_CACHE_HOME).
    Stage 2 — if it is empty, unpack CrowdStrike's pinned zip into it with inspect_evals' own
    step. INVARIANT: this comes first, because inspect_evals unpacks the zip only into an EMPTY
    folder; one stocked with the 26 PDFs alone would skip the 19 CrowdStrike reports.
    Stage 3 — fetch each of the 26 PDFs from the mirror, verified by inspect's ``download``
    against inspect_evals' ``THREAT_INTEL_PDF_SHA256``. Example: report ``200707-2`` →
    ``…/pdfs/200707-2.pdf`` lands at ``<reports>/200707-2.pdf`` after its sha256 matches
    ``d8ee…``.

    Args:
        inspect_evals_cache: the replay's ``INSPECT_EVALS_CACHE_DIR``. Unread: inspect_evals keeps
            these reports under platformdirs' user cache, not under this root (the zip itself
            does go there, by inspect_evals' own path).

    Raises:
        ValueError: a mirrored PDF's sha256 is not inspect_evals' pin (from inspect's ``download``).
        httpx.HTTPStatusError: the mirror or GitHub refused a file.
    """

    # WHY imported here: only a threat_intelligence replay's child needs these, and they must
    # be imported there, after the clean-room environment is in place.
    from inspect_ai.util import download
    from inspect_evals.cyberseceval_4 import threat_intelligence
    from inspect_evals.cyberseceval_4._constants import THREAT_INTEL_PDF_SHA256
    from inspect_evals.cyberseceval_4._data_utils import (
        resolve_data_location,
        resolve_nested_data_dir,
    )

    # Stage 1 — the same call inspect_evals' ensure_threat_intel_data makes.
    reports_dir: Path
    needs_unpack: bool
    reports_dir, needs_unpack = resolve_data_location(
        env_var=threat_intelligence.THREAT_INTEL_ENV_VAR,
        local_dir=Path(threat_intelligence.__file__).parent / "threat_intel_reasoning" / "reports",
        cache_parts=("threat_intelligence", "reports"),
    )
    # Stage 2 — CrowdStrike's zip, from GitHub at inspect_evals' pinned commit and checksum.
    if needs_unpack:
        reports_dir = threat_intelligence.download_threat_intel_data(reports_dir)
    reports_dir = resolve_nested_data_dir(reports_dir, "reports")
    # Stage 3 — the 26 others, from the mirror.
    for report_id, sha256 in THREAT_INTEL_PDF_SHA256.items():
        download(
            _THREAT_INTEL_MIRROR_URL.format(report_id=report_id),
            sha256,
            reports_dir / f"{report_id}.pdf",
        )


#: inspect_evals package → the prefetch every Task in it needs. Most packages need none.
_PREFETCHES: dict[str, Callable[[Path], None]] = {
    "inspect_evals.sad": prefetch_sad,
    # WHY the module, not the package: the other cyse4 Tasks fetch only CrowdStrike's zip.
    "inspect_evals.cyberseceval_4.threat_intelligence": prefetch_cyse4_threat_intelligence,
}


def prefetch_case_sources(task: str, inspect_evals_cache: Path) -> None:
    """Run the prefetch the Task's inspect_evals package needs, if it has one.

    Args:
        task: the declaration's ``"module:attr"`` reference, e.g.
            ``"inspect_evals.sad.sad:sad_facts_llms"``.
        inspect_evals_cache: the replay's ``INSPECT_EVALS_CACHE_DIR``.
    """

    module: str = task.partition(":")[0]
    for package, prefetch in _PREFETCHES.items():
        if module == package or module.startswith(package + "."):
            prefetch(inspect_evals_cache)
