"""Reference-file extraction policy — what counts as a usable reference, and what fails the build.

FEATURE: GDPval tasks hand the worker the files a professional would have been given. This board
serves text, so those files are flattened to text ONCE at image build time — a Runner Job is
offline with a read-only disk and cannot parse anything.

INVARIANT under test: a reference that does not yield usable text FAILS THE BUILD, naming the
task and the file. It is never baked as an empty reference. A silently empty reference produces
a task the model cannot do and a score that reads as model weakness — the same failure mode the
seven excluded tasks exist to prevent.

AIDEV-NOTE: the concrete pdf/docx readers are injected. `pdfplumber` and `python-docx` are build-
time only and absent from the test environment, exactly as `datasets` is for the other preparers,
so the POLICY is tested here with fakes and the adapters are exercised at build time.
"""

from __future__ import annotations

import pytest

from screamingface_engine.benchmarks.gdpval.ingestion import (
    MIN_VIABLE_CHARS,
    IngestionError,
    extract_reference_text,
)

_TASK = "83d10b06-26d1-4636-a32c-23f92c57f30b"


def _reader(text: str):
    def read(_path: str) -> str:
        return text

    return read


def test_a_healthy_reference_returns_its_text() -> None:
    body = "x" * (MIN_VIABLE_CHARS + 1)
    assert extract_reference_text(_TASK, "Population.pdf", reader=_reader(body)) == body


def test_text_is_returned_stripped_so_whitespace_cannot_pad_the_threshold() -> None:
    body = "y" * (MIN_VIABLE_CHARS + 1)
    got = extract_reference_text(_TASK, "Notes.pdf", reader=_reader(f"\n\n  {body}  \n"))
    assert got == body


def test_a_scanned_pdf_yielding_no_text_fails_the_build() -> None:
    # WHY this case: four of the six real failures were image-only PDFs — a 1099-INT, a mortgage
    # form — which extract to exactly zero characters.
    with pytest.raises(IngestionError) as excinfo:
        extract_reference_text(_TASK, "BOB 1099-INT.pdf", reader=_reader(""))
    assert _TASK in str(excinfo.value)
    assert "BOB 1099-INT.pdf" in str(excinfo.value)


def test_a_near_empty_reference_fails_the_build() -> None:
    # WHY: an embedded-logo docx returned 106 characters. Non-zero, and still unusable.
    with pytest.raises(IngestionError) as excinfo:
        extract_reference_text(_TASK, "Clinic Logo 2.docx", reader=_reader("z" * 106))
    assert "106" in str(excinfo.value), "the error must state what was actually extracted"


def test_the_threshold_boundary_is_inclusive() -> None:
    # INVARIANT: exactly MIN_VIABLE_CHARS is viable; one fewer is not. Pinned so the boundary
    # cannot drift silently when the constant is retuned.
    ok = "a" * MIN_VIABLE_CHARS
    assert extract_reference_text(_TASK, "Edge.pdf", reader=_reader(ok)) == ok
    with pytest.raises(IngestionError):
        extract_reference_text(_TASK, "Edge.pdf", reader=_reader("a" * (MIN_VIABLE_CHARS - 1)))


def test_a_reader_failure_is_reported_against_its_task_and_file() -> None:
    # WHY: two real DOCX files raise XMLSyntaxError from python-docx. The build must say WHICH
    # file, or the operator is left grepping 85 of them.
    def broken(_path: str) -> str:
        raise ValueError("XMLSyntaxError: not a zip file")

    with pytest.raises(IngestionError) as excinfo:
        extract_reference_text(_TASK, "Research Material.docx", reader=broken)
    message = str(excinfo.value)
    assert "Research Material.docx" in message
    assert _TASK in message


def test_extraction_is_deterministic() -> None:
    # INVARIANT: the baked text is part of the answer key. Two builds over one revision must
    # produce identical bytes.
    body = "q" * (MIN_VIABLE_CHARS + 40)
    first = extract_reference_text(_TASK, "Ref.pdf", reader=_reader(body))
    second = extract_reference_text(_TASK, "Ref.pdf", reader=_reader(body))
    assert first == second


def test_threshold_sits_in_the_measured_gap() -> None:
    # WHY: measured over all 85 reference files of the 109 prose-only tasks (2026-08-24). The six
    # unusable extractions clustered at 0, 0, 0, 0, 81 and 106 characters; the smallest GENUINE
    # extraction was 261. Any threshold in (106, 261] separates them; this asserts the constant
    # stays inside that evidence rather than drifting to a number nobody can re-derive.
    assert 106 < MIN_VIABLE_CHARS <= 261
