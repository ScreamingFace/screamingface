"""Bake the imported proof boards' assets: public prompts and private targets.

Run at IMAGE BUILD time, never at run time (OME-925): a Job's rootfs is read-only and
holds no HuggingFace credential, so every artifact exists before a run starts. HF
downloads happen here once; upstream gating or drift cannot change a published board.

Emits, per board::

    <out>/cases.json         [{"id", "case_id", "input"}] — ALL a client sees
    <out>/targets/<id>.json  {"target": ..., "choices": [...]?} — private; read by the
                             aggregate (the shim's grading material) and the check surface

INVARIANT — prompt formatting is baked HERE, reproducing the solver chain's prompt as a
string (spec §5.3: we import no solver, so their templates render at import time). The
formatting functions are inspect's OWN (their MATH_PROMPT_TEMPLATE, their
multiple-choice ``prompt``) — copied bytes, never a reimplementation.

INVARIANT — ``cases.json`` carries NO target. The client receives ids and prompts; the
answer key stays in the image.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from screamingface_engine.benchmarks.deployment import BenchmarkAssetPreparationError
from screamingface_engine_inspect.pins import (
    GSM8K_DATA_DIR,
    GSM8K_DATASET,
    GSM8K_DATASET_REVISION,
    GSM8K_SPLIT,
    MMLU_CONFIG,
    MMLU_DATASET,
    MMLU_DATASET_REVISION,
    MMLU_SHUFFLE_SEED,
    MMLU_SPLIT,
)

#: mmlu targets are index 0..3 into the row's four choices (their record_to_sample).
_MMLU_LETTERS = "ABCD"


class PrepareError(BenchmarkAssetPreparationError):
    """The build refuses to bake these assets. Always says which row and why."""


def gsm8k_prompt(question: str) -> str:
    """The exact prompt their solver chain renders — their template over the raw question."""

    from inspect_evals.gsm8k.gsm8k import MATH_PROMPT_TEMPLATE

    return MATH_PROMPT_TEMPLATE.format(prompt=question)


def mmlu_prompt(row: dict[str, Any]) -> str:
    """Their 0-shot MCQ prompt — their SINGLE_ANSWER template, their formatter."""

    from inspect_ai.solver import Choices, MultipleChoiceTemplate
    from inspect_ai.solver._multiple_choice import prompt as choice_prompt

    return choice_prompt(
        question=str(row["question"]),
        choices=Choices([str(choice) for choice in row["choices"]]),
        template=str(MultipleChoiceTemplate.SINGLE_ANSWER.value),
    )


def emit_gsm8k(rows: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    """Bake gsm8k rows: templated prompt public, the ``####`` tail as the private target."""

    cases: list[dict[str, Any]] = []
    targets: dict[int, dict[str, Any]] = {}
    for case_id, row in enumerate(rows, start=1):
        question: object = row.get("question")
        if not isinstance(question, str) or not question.strip():
            raise PrepareError(f"case {case_id}: question is empty or not text")
        # Their record_to_sample: the target is the text after "####", stripped.
        _, delimiter, tail = str(row.get("answer", "")).rpartition("####")
        target: str = tail.strip()
        if not delimiter or not target:
            raise PrepareError(f"case {case_id}: answer carries no '####'-delimited target")
        cases.append({"id": case_id, "case_id": str(case_id), "input": gsm8k_prompt(question)})
        targets[case_id] = {"target": target}
    return _emit(cases, targets, out, dataset_revision=GSM8K_DATASET_REVISION)


def emit_mmlu(rows: list[dict[str, Any]], out: Path) -> dict[str, Any]:
    """Bake mmlu rows: seeded shuffle, their MCQ prompt public, letter + choices private."""

    # INVARIANT: the shuffle is part of the exam identity — same rows, same seed, same
    # order (the seed rides the revision hash). WHY shuffle at all: the HF split is
    # subject-grouped, so a limit=N run over the raw order would examine one subject.
    shuffled: list[dict[str, Any]] = list(rows)
    random.Random(MMLU_SHUFFLE_SEED).shuffle(shuffled)
    cases: list[dict[str, Any]] = []
    targets: dict[int, dict[str, Any]] = {}
    for case_id, row in enumerate(shuffled, start=1):
        choices: object = row.get("choices")
        if not isinstance(choices, list) or len(choices) != len(_MMLU_LETTERS):
            raise PrepareError(f"case {case_id}: choices must be a list of 4 options")
        answer: object = row.get("answer")
        if isinstance(answer, bool) or not isinstance(answer, int) or not 0 <= answer <= 3:
            raise PrepareError(f"case {case_id}: answer must be an index 0..3")
        cases.append({"id": case_id, "case_id": str(case_id), "input": mmlu_prompt(row)})
        # The letter (their record_to_sample) plus the choice texts the shim needs to
        # replay their answer-marking step (state.choices).
        targets[case_id] = {
            "target": _MMLU_LETTERS[answer],
            "choices": [str(choice) for choice in choices],
        }
    return _emit(cases, targets, out, dataset_revision=MMLU_DATASET_REVISION)


def _emit(
    cases: list[dict[str, Any]],
    targets: dict[int, dict[str, Any]],
    out: Path,
    *,
    dataset_revision: str,
) -> dict[str, Any]:
    targets_dir: Path = out / "targets"
    targets_dir.mkdir(parents=True, exist_ok=True)
    for case_id, record in targets.items():
        (targets_dir / f"{case_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
    (out / "cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return {"cases": len(cases), "dataset_revision": dataset_revision, "out": str(out)}


def prepare_gsm8k(out: Path) -> dict[str, Any]:
    """Snapshot the pinned gsm8k split and bake its assets (build time only)."""

    return emit_gsm8k(
        _load_rows(GSM8K_DATASET, GSM8K_DATA_DIR, GSM8K_SPLIT, GSM8K_DATASET_REVISION), out
    )


def prepare_mmlu(out: Path) -> dict[str, Any]:
    """Snapshot the pinned mmlu split and bake its assets (build time only)."""

    return emit_mmlu(_load_rows(MMLU_DATASET, MMLU_CONFIG, MMLU_SPLIT, MMLU_DATASET_REVISION), out)


def _load_rows(dataset: str, config: str, split: str, revision: str) -> list[dict[str, Any]]:
    """Load one pinned HF split — ``datasets`` is a build-environment dependency only."""

    try:
        import datasets  # noqa: PLC0415 — build-time-only dependency, by design
    except ModuleNotFoundError as exc:
        raise PrepareError(
            "the `datasets` package is required to prepare a benchmark — "
            "`uv pip install datasets` in the build environment"
        ) from exc
    loaded = datasets.load_dataset(dataset, config, revision=revision, split=split)
    return [dict(row) for row in loaded]


__all__ = [
    "PrepareError",
    "emit_gsm8k",
    "emit_mmlu",
    "gsm8k_prompt",
    "mmlu_prompt",
    "prepare_gsm8k",
    "prepare_mmlu",
]
