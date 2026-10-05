"""Incremental report.v1 serialization, shared by disk export and bounded previews."""

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
    if isinstance(value, dict):
        yield "{"
        for index, (key, item) in enumerate(value.items()):
            yield ("," if index else "") + json.dumps(key, ensure_ascii=False) + ":"
            yield from _chunks(item)
        yield "}"
    elif isinstance(value, list | tuple | Iterator):
        yield "["
        for index, item in enumerate(value):
            yield "," if index else ""
            yield from _chunks(item)
        yield "]"
    else:
        yield from json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).iterencode(value)


def inline_json(report: Report, limit: int = 65536) -> str | None:
    chunks: list[str] = []
    size = 0
    for chunk in iter_report_json(report):
        size += len(chunk.encode("utf-8"))
        if size > limit:
            return None
        chunks.append(chunk)
    return "".join(chunks)


def write_report(report: Report, path: Path) -> None:
    """Replace an export only after the complete new snapshot reaches disk."""

    def write(stream: BinaryIO) -> None:
        for chunk in iter_report_json(report):
            stream.write(chunk.encode("utf-8"))

    from screamingface._results.lifecycle import report_operation

    with report_operation(report, "exporting"):
        write_atomic(path, write)
