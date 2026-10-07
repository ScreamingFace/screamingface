"""Prepare the MuSiQue-Ans assets: the public Cases and the private Grading Material.

    <out>/cases.json          [{id, input}]                     — public, the Candidate-facing text
    <out>/answers/<id>.json   {answer, answer_aliases,          — private, read by grading
                               supporting_idx, musique_id, hop_type}

Case Preparation runs at image build only, and is the ONLY step that touches the network:

1. download `musique_ans_v1.0_dev.jsonl` from the pinned Case Source commit;
2. refuse unless its sha256 is the reviewed one — before a single byte is parsed;
3. parse it, refuse unless it holds exactly EXPECTED_CASES Cases;
4. validate every Case (fields, all answerable, `idx` equal to position, supporting count equal
   to the hop count) — all of them before anything is written;
5. write the public Cases and one private Grading Material record per Case.

INVARIANT: `cases.json` carries NO gold. The gold answer text usually DOES appear inside a
paragraph (that is the task: find it), so the leak to guard against is any marker of WHICH
paragraphs support it, the answer field itself, and the dataset's id, whose `2hop`/`3hop1` prefix
tells a model how many paragraphs to cite.

Dev row shape: `id` · `paragraphs[idx, title, paragraph_text, is_supporting]` · `question` ·
`question_decomposition` · `answer` · `answer_aliases` · `answerable`.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, TypedDict

from screamingface_engine.benchmarks.deployment import BenchmarkAssetPreparationError
from screamingface_engine.benchmarks.musique.prompts import Paragraph, render_case_input
from screamingface_engine.benchmarks.musique.revision_inputs import (
    DATASET,
    DATASET_FILE,
    DATASET_REVISION,
    DATASET_SHA256,
    EXPECTED_CASES,
)

#: Every field a dev row carries. `question_decomposition` is unused, but its absence would mean
#: the file is not the one reviewed, so it is required like the rest.
_REQUIRED_FIELDS = (
    "id",
    "paragraphs",
    "question",
    "question_decomposition",
    "answer",
    "answer_aliases",
    "answerable",
)

#: The six composition shapes in the dev file (paper Table 2), keyed by the id prefix, each with
#: its hop count. INVARIANT on the pinned file: a Case has exactly hop-count supporting paragraphs.
_HOP_COUNTS: dict[str, int] = {
    "2hop": 2,
    "3hop1": 3,
    "3hop2": 3,
    "4hop1": 4,
    "4hop2": 4,
    "4hop3": 4,
}

#: The id is `<hop type>__<single-hop ids>`, e.g. `2hop__460946_294723`.
_HOP_TYPE_SEPARATOR = "__"


class PrepareError(BenchmarkAssetPreparationError):
    """The MuSiQue dev file could not be prepared — the build stops rather than serving it."""


class CaseRecord(TypedDict):
    """One public Case: its 1-based position and the rendered Candidate input."""

    id: int
    input: str


class AnswerRecord(TypedDict):
    """One Case's private Grading Material — what the official scorer needs, plus its origin."""

    answer: str
    answer_aliases: list[str]
    supporting_idx: list[int]
    musique_id: str
    hop_type: str


def download_dev_file() -> bytes:
    """Fetch the pinned dev file's bytes. Build time only — `huggingface_hub` is imported lazily."""

    try:
        hub: Any = importlib.import_module("huggingface_hub")
    except ModuleNotFoundError as exc:
        raise PrepareError(
            "the `huggingface_hub` package is required to prepare MuSiQue — "
            "install the engine's `benchmarks` extra in the build environment"
        ) from exc
    try:
        path: str = hub.hf_hub_download(
            repo_id=DATASET, filename=DATASET_FILE, revision=DATASET_REVISION, repo_type="dataset"
        )
        return Path(path).read_bytes()
    # WHY OSError: huggingface_hub's HTTP, not-found and offline errors all subclass it, as does a
    # failed read of the cached file. Anything else is a defect and keeps its traceback.
    except OSError as exc:
        raise PrepareError(
            f"could not download {DATASET_FILE} from {DATASET}@{DATASET_REVISION}: {exc}"
        ) from exc


def verify_sha256(data: bytes) -> None:
    """Refuse bytes that are not the reviewed dev file (spec F1)."""

    actual: str = hashlib.sha256(data).hexdigest()
    if actual != DATASET_SHA256:
        raise PrepareError(
            f"{DATASET_FILE} has sha256 {actual}, expected {DATASET_SHA256} — the Case Source "
            "changed since review; refusing to serve unreviewed Cases"
        )


def parse_rows(data: bytes, *, expected_count: int = EXPECTED_CASES) -> list[dict[str, Any]]:
    """Parse the JSON-lines file into one dict per Case, refusing a file of the wrong size."""

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(data.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row: object = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PrepareError(f"{DATASET_FILE} line {line_number} is not JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise PrepareError(f"{DATASET_FILE} line {line_number} is not a JSON object")
        rows.append(row)
    # INVARIANT: the file holds exactly the benchmark this benchmark declares. Without this, a
    # resized file prepares cleanly while `case_count` still declares the old size, and every
    # Coverage percentage divides by a denominator nobody verified.
    if len(rows) != expected_count:
        raise PrepareError(
            f"{DATASET_FILE} holds {len(rows)} Cases, but this benchmark is built for "
            f"{expected_count} — bump EXPECTED_CASES deliberately, with the revision"
        )
    return rows


def validate_row(row: dict[str, Any]) -> None:
    """Refuse a Case whose shape is not the reviewed one, naming it (spec F3)."""

    missing: list[str] = [field for field in _REQUIRED_FIELDS if field not in row]
    if missing:
        raise PrepareError(f"Case {row.get('id', '<no id>')!r} is missing fields {missing}")
    musique_id: str = _text(row["id"], "a Case", "id")
    _text(row["question"], musique_id, "question")
    _text(row["answer"], musique_id, "answer")
    _aliases(row["answer_aliases"], musique_id)
    if row["answerable"] is not True:
        raise PrepareError(
            f"{musique_id}: answerable is {row['answerable']!r}; MuSiQue-Ans holds only "
            "answerable Cases, so this is the wrong file"
        )
    hop_type: str = _hop_type(musique_id)
    supporting: int = _supporting_count(row["paragraphs"], musique_id)
    if supporting != _HOP_COUNTS[hop_type]:
        raise PrepareError(
            f"{musique_id}: {supporting} supporting paragraphs, but a {hop_type} question rests "
            f"on {_HOP_COUNTS[hop_type]}"
        )


def case_records(rows: list[dict[str, Any]]) -> tuple[list[CaseRecord], dict[int, AnswerRecord]]:
    """Validate the pinned rows into public Cases and the private Grading Material."""

    cases: list[CaseRecord] = []
    answers: dict[int, AnswerRecord] = {}
    for case_id, row in enumerate(rows, start=1):
        validate_row(row)
        # WHY the dataset's idx and order, not a renumbering (spec D4): support F1 compares the
        # numbers the model cites with these same idx values.
        paragraphs: list[Paragraph] = [
            Paragraph(idx=p["idx"], title=p["title"], text=p["paragraph_text"])
            for p in row["paragraphs"]
        ]
        cases.append({"id": case_id, "input": render_case_input(row["question"], paragraphs)})
        answers[case_id] = {
            "answer": row["answer"],
            "answer_aliases": list(row["answer_aliases"]),
            # WHY sorted: the record's bytes stay stable; the official metric takes a set anyway.
            "supporting_idx": sorted(p["idx"] for p in row["paragraphs"] if p["is_supporting"]),
            # WHY stored: the only link back to the dataset Case, and the Report's per-hop view
            # groups by hop_type (spec D12). Both stay private — see the module INVARIANT.
            "musique_id": row["id"],
            "hop_type": _hop_type(row["id"]),
        }
    return cases, answers


def emit(out: Path, cases: list[CaseRecord], answers: dict[int, AnswerRecord]) -> dict[str, Any]:
    """Write the public Cases and the private Grading Material. Returns the audit summary."""

    answers_dir: Path = out / "answers"
    answers_dir.mkdir(parents=True, exist_ok=True)
    for case_id, record in answers.items():
        (answers_dir / f"{case_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    (out / "cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    hop_types: Counter[str] = Counter(record["hop_type"] for record in answers.values())
    return {
        "cases": len(cases),
        # WHY published: a reader checks the 2/3/4-hop split against the paper's Table 2.
        "hop_types": dict(sorted(hop_types.items())),
        "dataset_revision": DATASET_REVISION,
        "dataset_file": DATASET_FILE,
        "out": str(out),
    }


def prepare(out: Path) -> dict[str, Any]:
    """Prepare the MuSiQue-Ans assets into ``out``, returning the audit summary."""

    data: bytes = download_dev_file()
    verify_sha256(data)
    # WHY the keyword at call time: the count pin is read when prepare runs, not when the module
    # was imported, so the build and its tests read the same name.
    rows: list[dict[str, Any]] = parse_rows(data, expected_count=EXPECTED_CASES)
    cases, answers = case_records(rows)
    return emit(out, cases, answers)


def main(argv: list[str] | None = None) -> int:
    """The `python -m ...musique.prepare --out <dir>` entry point the SDK spawns."""

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="musique-prepare", description=__doc__
    )
    parser.add_argument("--out", type=Path, required=True)
    args: argparse.Namespace = parser.parse_args(argv)
    try:
        summary: dict[str, Any] = prepare(args.out)
    except PrepareError as exc:
        print(f"musique prepare failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0


def _hop_type(musique_id: str) -> str:
    """The composition shape a dataset id names, e.g. `2hop` for `2hop__460946_294723`."""

    hop_type: str = musique_id.split(_HOP_TYPE_SEPARATOR, 1)[0]
    if hop_type not in _HOP_COUNTS:
        raise PrepareError(f"{musique_id}: unknown hop type {hop_type!r}")
    return hop_type


def _text(value: object, musique_id: str, field: str) -> str:
    """Return ``value`` when it is non-empty text, else refuse the Case naming the field."""

    if not isinstance(value, str) or not value.strip():
        raise PrepareError(f"{musique_id}: {field} must be non-empty text")
    return value


def _aliases(value: object, musique_id: str) -> None:
    """Refuse an `answer_aliases` that is not a list of non-empty strings (it may be empty)."""

    if not isinstance(value, list):
        raise PrepareError(f"{musique_id}: answer_aliases must be a list")
    for alias in value:
        _text(alias, musique_id, "every answer_aliases entry")


def _supporting_count(paragraphs: object, musique_id: str) -> int:
    """Validate the paragraph list and count its supporting paragraphs."""

    if not isinstance(paragraphs, list) or not paragraphs:
        raise PrepareError(f"{musique_id}: paragraphs must be a non-empty list")
    supporting: int = 0
    for position, paragraph in enumerate(paragraphs):
        if not isinstance(paragraph, dict):
            raise PrepareError(f"{musique_id}: paragraph {position} is not an object")
        # INVARIANT (spec D4): idx IS the position on the pinned file. The prompt shows idx and
        # the gold support set is idx, so if they ever diverge the build stops. `type() is int`
        # because a JSON `true` would otherwise compare equal to position 1.
        if type(paragraph.get("idx")) is not int or paragraph["idx"] != position:
            raise PrepareError(
                f"{musique_id}: paragraph {position} has idx {paragraph.get('idx')!r}; "
                "idx must equal its position"
            )
        _text(paragraph.get("title"), musique_id, f"paragraph {position} title")
        _text(paragraph.get("paragraph_text"), musique_id, f"paragraph {position} paragraph_text")
        if not isinstance(paragraph.get("is_supporting"), bool):
            raise PrepareError(f"{musique_id}: paragraph {position} is_supporting must be a bool")
        supporting += paragraph["is_supporting"]
    return supporting


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = [
    "DATASET_REVISION",
    "AnswerRecord",
    "CaseRecord",
    "PrepareError",
    "case_records",
    "download_dev_file",
    "emit",
    "main",
    "parse_rows",
    "prepare",
    "validate_row",
    "verify_sha256",
]
