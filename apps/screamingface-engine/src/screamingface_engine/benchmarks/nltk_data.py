"""The nltk corpus a Benchmark's grader reads, fetched at image build and read offline.

Think of it as packing a dictionary into the exam box: Case Preparation (image build, which
has network) downloads the named nltk resources into ``<bundle>/nltk_data/``, and the grading
job (no network, read-only rootfs) points nltk at that folder instead of downloading.
Shared by the hand-built ifeval and the plugin lane's local Tasks (OME-1527, R8).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from screamingface_engine.benchmarks.deployment import BenchmarkAssetPreparationError

#: The bundle sub-folder the corpus lands in and the grading job reads.
NLTK_DATA_DIR: str = "nltk_data"


class NltkDataError(BenchmarkAssetPreparationError):
    """An nltk resource could not be downloaded at image build. Names the resource."""


class NltkDataMissingError(ValueError):
    """A finished bundle whose row reads nltk data holds no corpus folder. Names the folder.

    WHY ValueError: world build turns an install-time ValueError into its one loud
    WorldConfigError, so a broken image refuses to start instead of grading with whatever
    corpus nltk finds elsewhere on the machine.
    """


def configure_nltk(data_dir: Path) -> None:
    """Point nltk at the prepared offline corpus, once.

    INVARIANT: the verifier's own ``ensure_nltk_resource`` downloader is NEVER called — a
    Runner Job has a read-only rootfs and no network egress, so tokenizer data must come
    from the benchmark's prepared assets.
    """

    import nltk

    selected = str(data_dir)
    if data_dir.is_dir() and selected not in nltk.data.path:
        nltk.data.path.insert(0, selected)


def download_nltk_data(target: Path, resources: Sequence[str]) -> str:
    """Download each nltk resource into ``target`` (image build only) and return its digest.

    Raises:
        NltkDataError: nltk reported a resource it could not download.
    """

    import nltk

    target.mkdir(parents=True, exist_ok=True)
    # WHY: nltk>=3.10's downloader rejects any target not registered in nltk.data.path
    # ("Security Violation: Unauthorized path"), so the directory is authorized first —
    # the same registration the run-time reader uses.
    configure_nltk(target)
    for resource in resources:
        if not nltk.download(resource, quiet=True, download_dir=str(target)):
            raise NltkDataError(f"could not download the nltk resource {resource!r}")
    return nltk_data_digest(target)


def nltk_data_digest(data_dir: Path) -> str:
    """Fingerprint every file under ``data_dir``: the sha256 of a ``sha256sum``-style listing.

    One ``<file sha256>  <path relative to data_dir>`` line per file, sorted by path, so the
    same corpus seals to the same 64 hex characters on any machine; file times never count.
    Reproduce by hand: ``cd nltk_data && find . -type f | sed 's|^./||' | LC_ALL=C sort |
    xargs sha256sum | sha256sum``.
    """

    files: list[tuple[str, Path]] = sorted(
        (path.relative_to(data_dir).as_posix(), path)
        for path in data_dir.rglob("*")
        if path.is_file()
    )
    listing: str = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}\n" for relative, path in files
    )
    return hashlib.sha256(listing.encode("utf-8")).hexdigest()


__all__ = [
    "NLTK_DATA_DIR",
    "NltkDataError",
    "NltkDataMissingError",
    "configure_nltk",
    "download_nltk_data",
    "nltk_data_digest",
]
