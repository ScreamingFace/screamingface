"""Bake the MedXpertQA (Text) assets: the public questions and the private answer key.

Run at IMAGE BUILD time, never at run time: a Job's rootfs is read-only apart from ``/tmp`` and
holds no HuggingFace credential, so every benchmark artifact must exist before the Job starts.

    uv run --with datasets python -m screamingface_engine.benchmarks.medxpert.prepare \
        --out /opt/benchmarks/medxpert

Emits::

    <out>/cases.json        [{"id": 1..2450, "input": <question>}] — ALL a client sees
    <out>/answers/<id>.json {source_id, label, options_count, metadata} — private, read by
                            runtime.py (check) and aggregate.py only

INVARIANT — ``cases.json`` carries NO label. The client receives Case ids and questions while the
answer key stays in the image. (The dataset is public on HF; this boundary keeps the ENGINE
honest, it is not anti-cheat.)

INVARIANT — the baked ``input`` is the question VERBATIM. MedXpertQA embeds its own choice list
in the question text, so rendering ``options`` into the prompt as well would duplicate every
choice and quietly change what each model is asked.

INVARIANT — Engine Case ids are 1-based positions in the pinned split. The dataset's own ``id``
("Text-0") is preserved in the private record so a row can still be traced upstream.
"""

from __future__ import annotations

import argparse
import importlib
import json
import string
import sys
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.deployment import BenchmarkAssetPreparationError
from screamingface_engine.benchmarks.medxpert.pins import (
    DATASET,
    DATASET_CONFIG,
    DATASET_REVISION,
    DATASET_SPLIT,
)

#: Dataset columns preserved so per-slice sub-scores can be cut the way the official leaderboard
#: cuts them.
METADATA_COLUMNS = ("question_type", "medical_task", "body_system")

_MAX_OPTIONS = 10


class PrepareError(BenchmarkAssetPreparationError):
    """The build refuses to bake these assets. Always says which row and why.

    WHY this base: OME-925 made asset preparation auditable, and this is the orchestrator's
    exit-1 channel for dataset drift — reported to an operator without a traceback. A row whose
    label is not among its own options is exactly that, not a programming defect.
    """


def case_records(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, dict]]:
    """Validate the pinned rows into public cases and the private answer key."""

    cases: list[dict[str, Any]] = []
    answers: dict[int, dict[str, Any]] = {}
    for case_id, row in enumerate(rows, start=1):
        question = row.get("question")
        if not isinstance(question, str) or not question.strip():
            raise PrepareError(f"case {case_id}: question is empty or not text")
        options_count = _options_count(row.get("options"), case_id)
        label = row.get("label")
        options = row["options"]
        if not isinstance(label, str) or label not in options:
            raise PrepareError(
                f"case {case_id}: label {label!r} is not one of its own options — the row is "
                f"unanswerable and every candidate would be marked wrong on it"
            )
        # INVARIANT: verbatim. See the module docstring.
        cases.append({"id": case_id, "input": question})
        answers[case_id] = {
            "source_id": str(row.get("id", "")),
            "label": label,
            "options_count": options_count,
            "metadata": {
                column: row[column] for column in METADATA_COLUMNS if row.get(column) is not None
            },
        }
    return cases, answers


def _options_count(options: object, case_id: int) -> int:
    """The row's option count, refusing anything that is not a contiguous A.. letter map.

    WHY strict: the trigger says "among A through {end}", and the answer-time parser only accepts
    letters inside that range. A gapped or over-long map would produce a trigger that does not
    describe the choices the model was actually shown.
    """

    if not isinstance(options, dict) or not options:
        raise PrepareError(f"case {case_id}: options must be a non-empty object keyed by letter")
    count = len(options)
    if count > _MAX_OPTIONS or set(options) != set(string.ascii_uppercase[:count]):
        last = string.ascii_uppercase[count - 1] if 0 < count <= 26 else "?"
        raise PrepareError(
            f"case {case_id}: options keys {sorted(options)} are not the contiguous "
            f"letters A..{last}"
        )
    return count


def emit(rows: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    """Write the public cases file and the private answer key. Returns the audit summary."""

    cases, answers = case_records(rows)
    answers_dir = out / "answers"
    answers_dir.mkdir(parents=True, exist_ok=True)
    for case_id, record in answers.items():
        (answers_dir / f"{case_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    (out / "cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return {
        "cases": len(cases),
        "dataset_revision": DATASET_REVISION,
        "config": DATASET_CONFIG,
        "split": DATASET_SPLIT,
        "out": str(out),
    }


def load_rows() -> list[dict[str, Any]]:
    """Load the pinned split. Build time only — ``datasets`` is not an engine dependency."""

    try:
        datasets_mod = importlib.import_module("datasets")
    except ModuleNotFoundError as exc:
        raise PrepareError(
            "the `datasets` package is required to prepare a benchmark — "
            "`uv pip install datasets` in the build environment"
        ) from exc
    loaded = datasets_mod.load_dataset(
        DATASET, DATASET_CONFIG, revision=DATASET_REVISION, split=DATASET_SPLIT
    )
    return [dict(row) for row in loaded]


def prepare(out: Path) -> dict[str, Any]:
    """Bake the MedXpertQA assets into ``out``, returning the audit summary."""

    return emit(load_rows(), out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="medxpert-prepare", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = prepare(args.out)
    except PrepareError as exc:
        print(f"medxpert prepare failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())
