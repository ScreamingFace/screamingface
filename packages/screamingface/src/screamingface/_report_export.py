"""Incremental report.v1 serialization for JSON strings and durable disk export."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from screamingface._atomic_file import write_atomic

if TYPE_CHECKING:
    from screamingface.report import Report


def iter_report_json(report: Report) -> Iterator[str]:
    candidates = (
        candidate._export_fields(cases=(case.to_dict() for case in candidate.cases))
        for candidate in report.candidates
    )
    yield from _chunks(report._export_fields(candidates=candidates))


def _chunks(value: object) -> Iterator[str]:
    # WHY: only the Report/Candidate envelopes contain our lazy array iterators.
    # Ordinary fields (including a complete Case) already fit in memory; let the
    # standard encoder handle them in one chunk rather than encoding every scalar.
    if isinstance(value, dict) and any(isinstance(item, Iterator) for item in value.values()):
        yield "{"
        for index, (key, item) in enumerate(value.items()):
            yield ("," if index else "") + json.dumps(key, ensure_ascii=False) + ":"
            yield from _chunks(item)
        yield "}"
    elif isinstance(value, Iterator):
        yield "["
        for index, item in enumerate(value):
            yield "," if index else ""
            yield from _chunks(item)
        yield "]"
    else:
        yield json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def write_report(report: Report, path: Path) -> None:
    """Replace an export only after the complete new snapshot reaches disk."""

    def write(stream: BinaryIO) -> None:
        for chunk in iter_report_json(report):
            stream.write(chunk.encode("utf-8"))

    write_atomic(path, write)
