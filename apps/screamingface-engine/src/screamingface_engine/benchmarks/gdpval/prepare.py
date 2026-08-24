"""Bake the GDPval text-subset assets: the public Cases and the private rubrics.

Run at IMAGE BUILD time, never at run time: a Job's rootfs is read-only apart from ``/tmp`` and
holds no HuggingFace credential, so every benchmark artifact must exist before the Job starts.

    uv run --with datasets --with pdfplumber --with python-docx \
        python -m screamingface_engine.benchmarks.gdpval.prepare --out /opt/benchmarks/gdpval

Emits::

    <out>/cases.json          [{"id": 1..102, "input": <candidate-input envelope>}]
    <out>/rubrics/<id>.json   {"task_id", "items": [{"rubric_id", "criterion", "points"}]}

INVARIANT — ``cases.json`` carries NO rubric. The client receives Case ids and inputs while the
answer key stays in the image.

INVARIANT — Engine Case ids are 1-based positions in ``subset.TEXT_SUBSET_TASK_IDS``, not in the
upstream row order. GDPval rows carry stable ``task_id``s, so the selection is addressed by id
and the build ASSERTS every frozen id is present; a dataset that dropped or renamed one fails the
build rather than silently baking a smaller exam under the same identity.

INVARIANT — container criteria are stripped HERE, so no scoring path can include one. A rubric
left with no positive points after stripping fails the build: its score would divide by zero.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA
from screamingface_engine.benchmarks.gdpval.ingestion import (
    IngestionError,
    docx_reader,
    extract_reference_text,
    pdf_reader,
)
from screamingface_engine.benchmarks.gdpval.pins import DATASET, DATASET_REVISION
from screamingface_engine.benchmarks.gdpval.rubric_filter import strip_format_criteria
from screamingface_engine.benchmarks.gdpval.subset import TEXT_SUBSET_TASK_IDS

# WHY a stable delimiter: the reference block is part of the Case input and therefore part of the
# answer key. Its exact bytes must not drift between builds.
_REFERENCE_HEADER = "--- Reference file: {name} ---"

#: ``(task_id, file_name) -> text``. Injected so the policy is testable without the build-time
#: parsing libraries; ``prepare`` supplies the real one.
ReferenceReader = Callable[[str, str], str]


class PrepareError(RuntimeError):
    """The build refuses to bake these assets. Always says which task and why."""


def select_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the frozen selection, in frozen order.

    INVARIANT: order comes from ``TEXT_SUBSET_TASK_IDS``, never from the upstream file — Engine
    Case ids are positions in that tuple, so inheriting upstream order would renumber the exam
    whenever HuggingFace reshuffled.
    """

    by_id = {str(row["task_id"]): row for row in rows}
    missing = [task_id for task_id in TEXT_SUBSET_TASK_IDS if task_id not in by_id]
    if missing:
        raise PrepareError(
            f"{len(missing)} frozen task id(s) are absent from {DATASET}@{DATASET_REVISION}, "
            f"first {missing[0]!r} — the dataset moved under the frozen selection; refusing to "
            f"bake a different exam under this identity"
        )
    return [by_id[task_id] for task_id in TEXT_SUBSET_TASK_IDS]


def rubric_items(row: Mapping[str, Any], case_id: int) -> list[dict[str, Any]]:
    """The scored criteria for one Case, container checks removed and shapes validated."""

    raw = row.get("rubric_json")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise PrepareError(f"case {case_id}: rubric_json is not JSON: {exc}") from exc
    if not isinstance(parsed, list) or not parsed:
        raise PrepareError(f"case {case_id}: rubric_json must be a non-empty array")

    items: list[dict[str, Any]] = []
    for index, item in enumerate(strip_format_criteria(parsed), start=1):
        if not isinstance(item, dict):
            raise PrepareError(f"case {case_id}: rubric item {index} must be an object")
        criterion = item.get("criterion")
        points = item.get("score")
        if not isinstance(criterion, str) or not criterion.strip():
            raise PrepareError(f"case {case_id}: rubric item {index} lacks a criterion")
        if isinstance(points, bool) or not isinstance(points, int):
            # INVARIANT: ints only — the judge must see "[7]", never "[7.0]", or the grader
            # prompt's bytes change for every future run.
            raise PrepareError(
                f"case {case_id}: rubric item {index} score must be an integer, got {points!r}"
            )
        # INVARIANT: rubric_id is the 1-BASED position. `scoring.case_score` indexes points
        # with `enumerate(points, start=1)` and `verdict.binding_key` refuses anything below 1,
        # so a 0-based id here would silently misalign every criterion with its point value.
        items.append({"rubric_id": index, "criterion": criterion, "points": points})

    if not any(item["points"] > 0 for item in items):
        raise PrepareError(
            f"case {case_id}: no positive-points criterion survives the container filter — "
            f"the score's denominator would be zero"
        )
    return items


def case_input(row: Mapping[str, Any], *, reader: ReferenceReader) -> str:
    """The candidate-input envelope as PLAIN JSON — prompt followed by every reference.

    WHY plain JSON rather than a url4 struct: a value baked into ``cases.json`` is substituted
    into the Candidate call VERBATIM as data, so it must already be what the Runner's envelope
    decoder ``json.loads``es.
    """

    task_id = str(row["task_id"])
    parts = [str(row["prompt"]).strip()]
    for file_name in row.get("reference_files") or []:
        name = str(file_name)
        parts.append(_REFERENCE_HEADER.format(name=name))
        parts.append(reader(task_id, name))
    content = "\n\n".join(parts)
    return json.dumps(
        {"schema": CANDIDATE_INPUT_SCHEMA, "messages": [{"role": "user", "content": content}]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def emit(rows: list[dict[str, Any]], out: Path, *, reader: ReferenceReader) -> int:
    """Write the public cases file and the private rubric assets. Returns the Case count."""

    selected = select_rows(rows)
    rubric_dir = out / "rubrics"
    rubric_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for case_id, row in enumerate(selected, start=1):
        cases.append({"id": case_id, "input": case_input(row, reader=reader)})
        (rubric_dir / f"{case_id}.json").write_text(
            json.dumps(
                {"task_id": str(row["task_id"]), "items": rubric_items(row, case_id)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    (out / "cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(cases)


def load_rows() -> list[dict[str, Any]]:
    """Load the pinned dataset revision. Build time only — ``datasets`` is not a dependency."""

    try:
        datasets_mod = importlib.import_module("datasets")
    except ModuleNotFoundError as exc:
        raise PrepareError(
            "the `datasets` package is required to prepare a benchmark — "
            "`uv pip install datasets` in the build environment"
        ) from exc
    loaded = datasets_mod.load_dataset(DATASET, revision=DATASET_REVISION)
    rows: list[dict[str, Any]] = []
    for split in loaded:
        rows.extend(dict(row) for row in loaded[split])
    return rows


def _build_reader(root: Path) -> ReferenceReader:
    """Dispatch a reference to the reader for its extension, applying the viability floor."""

    readers = {".pdf": pdf_reader(root), ".docx": docx_reader(root), ".doc": docx_reader(root)}

    def read(task_id: str, file_name: str) -> str:
        suffix = Path(file_name).suffix.casefold()
        chosen = readers.get(suffix)
        if chosen is None:
            raise IngestionError(
                f"task {task_id}: reference {file_name!r} has no reader for {suffix!r} — the "
                f"selection should contain only prose formats"
            )
        return extract_reference_text(task_id, file_name, reader=chosen)

    return read


def prepare(out: Path, *, assets_root: Path | None = None) -> int:
    """Bake the GDPval text-subset assets into ``out``."""

    return emit(load_rows(), out, reader=_build_reader(assets_root or out))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--references", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        count = prepare(args.out, assets_root=args.references)
    except (PrepareError, IngestionError) as exc:
        print(f"gdpval prepare failed: {exc}", file=sys.stderr)
        return 1
    print(f"gdpval: baked {count} cases into {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
