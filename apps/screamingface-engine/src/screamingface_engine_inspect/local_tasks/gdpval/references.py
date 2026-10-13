"""Flatten a GDPval reference file to text, or fail the build saying which one could not be.

FEATURE: GDPval hands the worker the files a professional would have been given — a population
spreadsheet, a prior report, an intake form. This benchmark serves TEXT, so those files are
flattened once at image build time and written into the Case input.

INVARIANT: extraction happens at BUILD time only. A Runner Job is offline with a read-only disk;
nothing here may run while a Candidate is being evaluated.

INVARIANT: a reference that does not yield usable text FAILS THE BUILD. It is never prepared empty.
A silently empty reference produces a task the model cannot do and a score that reads as model
weakness rather than as a broken input — the same failure the seven excluded tasks avoid.

AIDEV-NOTE: the reader is INJECTED. `pdfplumber` and `python-docx` are build-time dependencies
absent from the runtime and test environments, exactly as `datasets` is for the other preparers,
so the policy in this module is unit-testable while the concrete adapters are exercised only when
an image is built. :func:`build_reader` passes `pdf_reader()` / `docx_reader()` below.

The download half (:func:`reference_urls`, :func:`build_reader`) moved here verbatim from the
hand-built ``prepare.py`` (OME-1527): the Task's loader calls it, at import and at image build.
"""

from __future__ import annotations

import importlib
import os
import tempfile
import time
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

# WHY 200: measured over all 85 reference files carried by the 109 prose-only tasks (2026-08-24).
# The six unusable extractions clustered at 0, 0, 0, 0, 81 and 106 characters — image-only PDFs
# such as a 1099-INT and a mortgage form, plus a docx holding just a logo. The smallest GENUINE
# extraction was 261 characters (a short tax summary). Any threshold in (106, 261] separates the
# two populations; 200 sits in the middle of that gap.
#
# AIDEV-NOTE: this is a floor on USABILITY, not a quality score. A build failure here is a signal
# for a human to look at the file, not something to tune away — the seven known-bad tasks are
# already excluded in `subset.py`, so a NEW failure means the dataset or the reader changed.
MIN_VIABLE_CHARS = 200

Reader = Callable[[str], str]

#: ``(task_id, file_name) -> text``. Injected so the policy is testable without the build-time
#: parsing libraries; the loader supplies the real one.
ReferenceReader = Callable[[str, str], str]

#: Per-file download budget. A reference is a working document, not a dataset.
_FETCH_TIMEOUT_S = 120
_FETCH_ATTEMPTS = 4
_FETCH_BACKOFF_S = 2.0


class IngestionError(RuntimeError):
    """A reference file could not be turned into usable text. Always names task and file."""


def extract_reference_text(task_id: str, file_name: str, *, reader: Reader) -> str:
    """Return the reference's text, or raise naming the task and file.

    INVARIANT: the returned text is stripped, so trailing whitespace can never pad a file over
    the viability threshold.
    """

    try:
        raw = reader(file_name)
    except Exception as exc:  # noqa: BLE001 — re-raised immediately with the identifying context
        # WHY catch broadly: readers fail in library-specific ways (python-docx raises
        # XMLSyntaxError for a malformed package, pdfplumber raises its own errors). What the
        # operator needs is WHICH file broke, out of 85 — not the exception's pedigree, which is
        # preserved as the cause.
        raise IngestionError(
            f"task {task_id}: reference {file_name!r} could not be read: {exc}"
        ) from exc

    text = raw.strip()
    if len(text) < MIN_VIABLE_CHARS:
        raise IngestionError(
            f"task {task_id}: reference {file_name!r} extracted to {len(text)} characters, "
            f"below the {MIN_VIABLE_CHARS}-character viability floor — it is most likely a "
            f"scan or an image. Exclude the task in subset.py, or supply a text reference."
        )
    return text


def pdf_reader(root: Path) -> Reader:
    """A reader that flattens a PDF's text and tables. Build time only."""

    pdfplumber = _require("pdfplumber")

    def read(file_name: str) -> str:
        parts: list[str] = []
        with pdfplumber.open(root / file_name) as document:
            for page in document.pages:
                parts.append(page.extract_text() or "")
                # WHY tables too: GDPval references are working documents — intake forms, rate
                # schedules — whose numbers live in tables that `extract_text` alone drops.
                for table in page.extract_tables() or []:
                    parts.append("\n".join("\t".join(cell or "" for cell in row) for row in table))
        return "\n".join(parts)

    return read


def docx_reader(root: Path) -> Reader:
    """A reader that flattens a DOCX's paragraphs and tables. Build time only."""

    docx = _require("docx")

    def read(file_name: str) -> str:
        document = docx.Document(str(root / file_name))
        parts = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append("\t".join(cell.text for cell in row.cells))
        return "\n".join(parts)

    return read


def _require(module: str):
    """Import a build-time-only dependency, or say how to install it."""

    package = {"docx": "python-docx"}.get(module, module)
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as exc:
        raise IngestionError(
            f"the `{package}` package is required to prepare the GDPval benchmark — "
            f"`uv pip install {package}` in the build environment"
        ) from exc


def reference_urls(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Map every reference file's dataset path to its download URL.

    WHY a map built from ALL rows rather than a per-row lookup: the reader is constructed once
    and closes over this, so the loader hands every row the same two-argument reader. Dataset
    paths embed a content hash, so they are unique.
    """

    urls: dict[str, str] = {}
    for row in rows:
        names = row.get("reference_files") or []
        sources = row.get("reference_file_urls") or []
        for name, url in zip(names, sources, strict=False):
            urls[str(name)] = str(url)
    return urls


def build_reader(cache: Path, urls: Mapping[str, str]) -> ReferenceReader:
    """Download each reference once, then flatten it with the reader for its extension.

    INVARIANT: build time only. The download happens here so a Runner Job — offline, read-only
    rootfs — never needs the network or the original binaries.

    AIDEV-NOTE: the concrete readers are built LAZILY, on first use of each extension. 66 of the
    102 selected tasks carry no reference files at all, and eagerly constructing them would make
    `pdfplumber` and `python-docx` hard requirements of a build that may never open a PDF — and
    would make this function untestable without both installed.
    """

    cache.mkdir(parents=True, exist_ok=True)
    factories = {".pdf": pdf_reader, ".docx": docx_reader, ".doc": docx_reader}
    built: dict[str, Reader] = {}

    def read(task_id: str, file_name: str) -> str:
        """One reference's flattened text: fetched into the cache once, then read."""

        suffix = Path(file_name).suffix.casefold()
        factory = factories.get(suffix)
        if factory is None:
            raise IngestionError(
                f"task {task_id}: reference {file_name!r} has no reader for {suffix!r} — the "
                f"selection should contain only prose formats"
            )
        _fetch(task_id, file_name, urls, cache)
        if suffix not in built:
            built[suffix] = factory(cache)
        return extract_reference_text(task_id, file_name, reader=built[suffix])

    return read


def _fetch(task_id: str, file_name: str, urls: Mapping[str, str], cache: Path) -> None:
    """Download one reference into the cache, unless it is already there."""

    destination = cache / file_name
    if destination.is_file() and destination.stat().st_size > 0:
        return
    url = urls.get(file_name)
    if not url:
        raise IngestionError(
            f"task {task_id}: reference {file_name!r} has no download URL in the dataset"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    # INVARIANT: the destination path only ever appears COMPLETE. The cache-hit check above is
    # presence plus non-zero size, so a download killed mid-write (Ctrl-C, disk full) would
    # otherwise leave a truncated file that every later run accepts forever — and a truncated
    # PDF that still parses past MIN_VIABLE_CHARS would prepare truncated reference text into the
    # answer key. Bytes land in a temp sibling; only a finished download is renamed into place.
    part = destination.with_suffix(destination.suffix + ".part")
    # WHY retry: this fetches 85 files in sequence from a public CDN, and a single reset
    # ("Connection reset by peer") would otherwise abandon a multi-minute build. Bounded, so a
    # genuinely missing file still fails rather than looping.
    last: OSError | None = None
    for attempt in range(_FETCH_ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_S) as response:
                part.write_bytes(response.read())
        except OSError as exc:
            last = exc
            if attempt + 1 < _FETCH_ATTEMPTS:
                time.sleep(_FETCH_BACKOFF_S * (attempt + 1))
        else:
            os.replace(part, destination)
            return
    part.unlink(missing_ok=True)
    raise IngestionError(
        f"task {task_id}: reference {file_name!r} could not be downloaded after "
        f"{_FETCH_ATTEMPTS} attempts: {last}"
    ) from last


def default_reference_cache(dataset_revision: str) -> Path:
    """Where downloaded reference binaries live: outside the served bundle.

    WHY outside the bundle: the references are already flattened into the Case inputs, so a
    cache inside the asset tree would ship all 85 original PDF/DOCX binaries (tens of MB) for
    nothing. The dataset revision is part of the path so a re-pin can never serve stale
    binaries from a prior pin.
    """

    return Path(tempfile.gettempdir()) / f"gdpval-references-{dataset_revision[:12]}"


__all__ = [
    "MIN_VIABLE_CHARS",
    "IngestionError",
    "Reader",
    "ReferenceReader",
    "build_reader",
    "default_reference_cache",
    "docx_reader",
    "extract_reference_text",
    "pdf_reader",
    "reference_urls",
]
