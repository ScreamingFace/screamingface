"""Flatten a GDPval reference file to text, or fail the build saying which one could not be.

FEATURE: GDPval hands the worker the files a professional would have been given — a population
spreadsheet, a prior report, an intake form. This board serves TEXT, so those files are flattened
once at image build time and baked into the Case input.

INVARIANT: extraction happens at BUILD time only. A Runner Job is offline with a read-only disk;
nothing here may run while a Candidate is being evaluated.

INVARIANT: a reference that does not yield usable text FAILS THE BUILD. It is never baked empty.
A silently empty reference produces a task the model cannot do and a score that reads as model
weakness rather than as a broken input — the same failure the seven excluded tasks avoid.

AIDEV-NOTE: the reader is INJECTED. `pdfplumber` and `python-docx` are build-time dependencies
absent from the runtime and test environments, exactly as `datasets` is for the other preparers,
so the policy in this module is unit-testable while the concrete adapters are exercised only when
an image is built. Callers in `prepare` pass `pdf_reader()` / `docx_reader()` below.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

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


__all__ = [
    "MIN_VIABLE_CHARS",
    "IngestionError",
    "Reader",
    "docx_reader",
    "extract_reference_text",
    "pdf_reader",
]
